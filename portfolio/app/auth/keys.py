"""Generating and hashing API keys. Pure functions, no I/O, so the security-relevant part
is testable without a database.
"""

from __future__ import annotations

import hashlib
import secrets

KEY_PREFIX = "pf_live_"
"""Fixed, non-secret marker. Two reasons it exists: a leaked key is greppable in logs and
scannable by secret-detection tooling, and a value that doesn't start with it can be
rejected before touching the database."""

_SECRET_BYTES = 32
"""256 bits from `secrets.token_urlsafe`. See `hash_key` for why the entropy matters."""

_TOKEN_LENGTH = (4 * _SECRET_BYTES + 2) // 3
"""Length of the random part: unpadded base64url of `_SECRET_BYTES`, so 43 for 32 bytes.
Derived rather than hardcoded so it cannot drift from `_SECRET_BYTES`, and pinned by a test
that generates keys and measures them -- the formula is easy to write down slightly wrong."""

EXPECTED_KEY_LENGTH = len(KEY_PREFIX) + _TOKEN_LENGTH
"""Every key this system issues is exactly this long (51).

**Changing `_SECRET_BYTES` invalidates every key already in the database**, because stored
digests are of the old length and presented keys of the new length would be rejected by
`looks_like_key` before the lookup. Rotating key length is therefore a migration, not a
constant edit: widen this check to accept both lengths, let the old keys age out, then
narrow it again."""

PREFIX_DISPLAY_LENGTH = len(KEY_PREFIX) + 8
"""How much of a key is safe to store for display. 8 random characters is enough to tell
keys apart in a list while leaving the remaining ~35 unguessable."""


def generate_key() -> str:
    """A fresh API key. Shown to the user exactly once -- only its hash is persisted."""
    return f"{KEY_PREFIX}{secrets.token_urlsafe(_SECRET_BYTES)}"


def hash_key(key: str) -> str:
    """SHA-256 hex of the key, deliberately *not* argon2/bcrypt.

    Slow KDFs exist to make brute-forcing *low-entropy* secrets expensive -- passwords are
    guessable, so each guess must cost something. An API key here is 256 bits of CSPRNG
    output: there is no guessable structure to attack, so a KDF adds latency to every
    authenticated request while buying no security. It would also break the indexed-lookup
    property below.

    SHA-256 also keeps authentication O(1): hash the presented key and look the digest up
    on an indexed column. A KDF with a per-row salt cannot be looked up, forcing a scan and
    a verify against every stored key.

    Passwords are a different problem with a different answer -- when Phase 5 adds password
    login, that path must use argon2id, not this function.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def display_prefix(key: str) -> str:
    return key[:PREFIX_DISPLAY_LENGTH]


def looks_like_key(value: str) -> bool:
    """Cheap shape check so obvious non-keys never reach a database round-trip -- or a hash.

    Exact length, not a minimum. A minimum accepts an arbitrarily large body as a candidate
    key, and `resolve_tenant` would then SHA-256 all of it before finding nothing: unbounded
    work per unauthenticated request. nginx caps request *headers* at 8KB, which bounds it on
    the proxied path, but Streamlit calls `resolve_tenant` in process with no such ceiling.

    `isascii()` because the random part is base64url and the prefix is ASCII, so anything else
    cannot be one of our keys. It also makes `hash_key`'s `.encode()` total: for ASCII input,
    UTF-8 and ASCII encode to identical bytes, so this narrows the input space without
    changing any digest.

    This stays a boolean at the caller rather than a `raise` inside `hash_key`. `hash_key` is
    also called on freshly *generated* keys, where validating is pointless, and a raise there
    would turn a malformed header into an unhandled 500 instead of the 401 it should be.
    """
    return value.isascii() and len(value) == EXPECTED_KEY_LENGTH and value.startswith(KEY_PREFIX)
