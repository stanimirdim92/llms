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
    """Cheap shape check so obvious non-keys never reach a database round-trip."""
    return value.startswith(KEY_PREFIX) and len(value) > PREFIX_DISPLAY_LENGTH
