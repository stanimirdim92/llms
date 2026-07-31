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
import time
import uuid

__all__ = ["new_id"]

_UNIX_TS_MS_BITS = 48
_VERSION = 0x7
_VARIANT = 0b10


def _uuid7_fallback() -> uuid.UUID:
    """RFC 9562 §5.7 layout: 48-bit big-endian unix ms, version, 12 random, variant, 62 random."""
    timestamp_ms = time.time_ns() // 1_000_000
    random_bits = secrets.randbits(74)  # 12 for rand_a + 62 for rand_b

    value = (timestamp_ms & ((1 << _UNIX_TS_MS_BITS) - 1)) << 80
    value |= _VERSION << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= _VARIANT << 62
    value |= random_bits & ((1 << 62) - 1)
    return uuid.UUID(int=value)


def new_id() -> str:
    """A fresh time-ordered id as 32 hex characters.

    Hex, not the dashed form, because these become filesystem path segments
    (`tenant_upload_dir`) and are validated as 32 hex chars there.
    """
    generator = getattr(uuid, "uuid7", _uuid7_fallback)
    return generator().hex
