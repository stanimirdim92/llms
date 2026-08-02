"""Pins `new_id` to a genuine RFC 9562 version-7 UUID on both code paths.

The fallback exists because `uuid.uuid7()` is 3.14 stdlib and this project's floor is
3.13. A fallback that quietly returned a `uuid4` would still produce a valid id and
still pass a "looks like 32 hex chars" check, while silently dropping the time-ordering
that makes these usable as primary keys. These tests fail on that substitution.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import TYPE_CHECKING

from app import ids

if TYPE_CHECKING:
    import pytest


def _uuid_from(hex_id: str) -> uuid.UUID:
    return uuid.UUID(hex=hex_id)


def test_new_id_is_32_hex_chars() -> None:
    """Tenant ids become filesystem path segments and are validated as 32 hex chars there."""
    value = ids.new_id()

    assert len(value) == 32
    assert all(character in "0123456789abcdef" for character in value)


def test_new_id_is_version_7() -> None:
    assert _uuid_from(ids.new_id()).version == 7


def test_fallback_is_version_7_and_rfc_variant() -> None:
    """Asserted on the fallback directly, since the stdlib path masks it on 3.14."""
    value = ids._uuid7_fallback()

    assert value.version == 7
    # RFC 9562 variant is the two high bits of octet 8 == 0b10.
    assert (value.int >> 62) & 0b11 == 0b10


def test_fallback_timestamp_is_the_leading_48_bits() -> None:
    """The whole point of v7: ids sort by creation time, so the timestamp must lead.

    Compared against `time.time_ns()` rather than a fixed constant so this does not
    rot, and with a generous window because the assertion is about *where the bits
    are*, not about clock precision.
    """
    before_ms = time.time_ns() // 1_000_000
    value = ids._uuid7_fallback()
    after_ms = time.time_ns() // 1_000_000

    embedded_ms = value.int >> 80
    assert before_ms <= embedded_ms <= after_ms


def test_fallback_ids_sort_by_creation_order() -> None:
    """Lexicographic order of the hex form must match creation order.

    This is the property a `uuid4` fallback would break, and the reason index locality
    holds. Consecutive calls can land in the same millisecond, so this asserts
    non-decreasing rather than strictly increasing.
    """
    minted = [ids._uuid7_fallback().hex for _ in range(50)]

    assert [value[:12] for value in minted] == sorted(value[:12] for value in minted)


def test_fallback_ids_are_unique_within_one_millisecond() -> None:
    """62 random bits per id, so collisions inside a millisecond must not happen."""
    minted = {ids._uuid7_fallback().hex for _ in range(1000)}

    assert len(minted) == 1000


def test_ids_minted_in_the_same_millisecond_still_sort() -> None:
    """The property uuid7 was chosen over uuid4 *for*, and the fallback did not have.

    Without a counter the 74 bits after the timestamp are pure randomness, so ids minted
    inside one millisecond sort arbitrarily -- which is index fragmentation on the hot tables,
    the exact cost uuid4 was rejected to avoid. The pre-existing shape test only inspects the
    leading 48 timestamp bits, so it passes either way.

    5000 in a tight loop is comfortably more than one millisecond's worth on any machine, so
    this exercises the same-timestamp branch rather than just the clock advancing.
    """
    minted = [ids.new_id() for _ in range(5000)]

    assert len(set(minted)) == 5000, "duplicate id"
    assert minted == sorted(minted), "ids minted in one millisecond did not sort in creation order"


def test_concurrent_mints_do_not_collide() -> None:
    """`ids.new_id()` is reachable from FastAPI's threadpool as well as the event loop, so the
    counter needs a lock: without one two threads read the previous value before either
    writes and both emit the same id, which is a primary-key collision on `apikey`/`tenant`.
    """
    minted: list[str] = []
    threads = [threading.Thread(target=lambda: minted.extend(ids.new_id() for _ in range(500))) for _ in range(8)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(minted)) == len(minted) == 4000


def test_a_clock_step_backwards_cannot_produce_a_smaller_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """NTP correction, or a VM resuming from a snapshot. RFC 9562 calls for clamping rather
    than trusting the clock; without it an id sorts *before* one already issued, and a
    time-ordered primary key stops being one.
    """
    before = ids.new_id()
    now = time.time_ns()
    monkeypatch.setattr(ids.time, "time_ns", lambda: now - 60 * 1_000_000_000)  # one minute back

    after = ids.new_id()

    assert after > before, "an id minted after a backward clock step sorted before its predecessor"
