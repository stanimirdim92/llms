"""Time-ordered identifiers, independent of interpreter version.

`uuid.uuid7()` is 3.14 stdlib. This project's floor is 3.13, so the one place that
needs a time-ordered id cannot call it directly. Falling back to `uuid4()` on 3.13
was rejected: tenant ids are primary keys, and `uuid7`'s leading timestamp is what
gives them index locality on insert. A fallback that silently dropped that property
would make key distribution depend on which interpreter minted the row -- the kind of
difference that shows up as an index-bloat mystery months later, not as an error.

So the fallback implements RFC 9562 §5.7 rather than substituting a different scheme.
Both paths produce a genuine version-7 UUID; `test_ids.py` asserts that by checking
the version and variant bits and the monotonicity of the timestamp field.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid

__all__ = ["new_id"]

_UNIX_TS_MS_BITS = 48
_VERSION = 0x7
_VARIANT = 0b10
_COUNTER_MAX = 0xFFF  # rand_a is 12 bits


_lock = threading.Lock()
_last_timestamp_ms = 0
_counter = 0
"""Cross-call state the naive fallback had none of.

CPython's own `uuid.uuid7` keeps a monotonic counter and clamps against clock regression, and
that ordering is the entire reason uuid7 was chosen over uuid4 here -- primary-key index
locality. Without it, two ids minted in the same millisecond sort in effectively random
order, and a backward clock step (NTP correction, a VM resuming from snapshot) can produce an
id that sorts *before* one already issued. The existing shape test only checks the leading 48
timestamp bits, so it could not catch either.

`rand_a`'s 12 bits carry the counter, per RFC 9562 §6.2 "Replace Leftmost Random Bits with
Increased Clock Precision" -- so ids stay conformant and stay sortable inside a millisecond.
"""


def _uuid7_fallback() -> uuid.UUID:
    """RFC 9562 §5.7 layout: 48-bit big-endian unix ms, version, 12 counter, variant, 62 random.

    Locked because `new_id()` is called from request handlers across threads (anything
    FastAPI runs in its threadpool) as well as from the event loop; without it two threads
    can read `_last_timestamp_ms` before either writes, and both emit the same counter value.
    Contention is a few hundred nanoseconds on an id mint, which is not a path that needs it.
    """
    global _last_timestamp_ms, _counter  # noqa: PLW0603 -- the state IS the monotonicity guard

    with _lock:
        timestamp_ms = time.time_ns() // 1_000_000
        if timestamp_ms > _last_timestamp_ms:
            _last_timestamp_ms = timestamp_ms
            _counter = secrets.randbits(10)  # seeded low so a burst has room to climb
        else:
            # Same millisecond, or the clock went backwards. Either way keep the previous
            # timestamp and advance the counter, so ordering never regresses. On counter
            # exhaustion borrow a millisecond from the future rather than repeating an id.
            _counter += 1
            if _counter > _COUNTER_MAX:
                _last_timestamp_ms += 1
                _counter = 0
        timestamp_ms, counter = _last_timestamp_ms, _counter

    value = (timestamp_ms & ((1 << _UNIX_TS_MS_BITS) - 1)) << 80
    value |= _VERSION << 76
    value |= counter << 64
    value |= _VARIANT << 62
    value |= secrets.randbits(62)
    return uuid.UUID(int=value)


def new_id() -> str:
    """A fresh time-ordered id as 32 hex characters.

    Hex, not the dashed form, because these become filesystem path segments
    (`tenant_upload_dir`) and are validated as 32 hex chars there.
    """
    generator = getattr(uuid, "uuid7", _uuid7_fallback)
    return generator().hex
