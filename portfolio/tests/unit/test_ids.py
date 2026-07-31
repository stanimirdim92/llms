"""Pins `new_id` to a genuine RFC 9562 version-7 UUID on both code paths.

The fallback exists because `uuid.uuid7()` is 3.14 stdlib and this project's floor is
3.13. A fallback that quietly returned a `uuid4` would still produce a valid id and
still pass a "looks like 32 hex chars" check, while silently dropping the time-ordering
that makes these usable as primary keys. These tests fail on that substitution.
"""

from __future__ import annotations

import time
import uuid

from app import ids


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
