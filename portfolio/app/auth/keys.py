"""Generating and hashing API keys. Pure functions, no I/O, so the security-relevant part
is testable without a database.

Key format, modelled on GitHub's 2021 token redesign and Stripe's prefix convention:

    pf_live_ <43 base62 chars>            <6 base62 chars>
    └ prefix └ 256 bits of CSPRNG output  └ CRC32 checksum

Three properties, each earning its place:

- **The prefix makes a leak detectable.** A bare random string is indistinguishable from a
  hash or an id, which is precisely why GitHub replaced their 40-char hex tokens: scanners
  could not find them. `pf_live_` is greppable, and it is what a gitleaks or GitHub
  secret-scanning rule matches on.
- **Base62 rather than base64url** so the only non-alphanumeric characters in the whole key
  are the prefix's underscores. Base64url's alphabet includes `-`, which terminates a
  double-click selection in most editors and terminals -- a user copying their key would
  silently get a fragment of it. Underscore does not, which is why GitHub chose it as their
  separator.
- **The checksum makes a key verifiable offline.** See `checksum_matches`.
"""

from __future__ import annotations

import hashlib
import secrets
import zlib

KEY_PREFIX = "pf_live_"
"""Fixed, non-secret marker. Two reasons it exists: a leaked key is greppable in logs and
scannable by secret-detection tooling, and a value that doesn't start with it can be
rejected before touching the database.

The `live` half is forward-looking and currently a promise the system does not keep -- there
is no `pf_test_`, because there is no sandbox to issue one for. Adding one means a column on
`ApiKey` and a check at the boundary, not just a second prefix string; a test key that is
accepted by production endpoints is worse than no test key at all."""

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
"""Base62. Deliberately not base64url -- see the module docstring on double-click selection."""

_SECRET_BITS = 256
"""Entropy of the random part. Both of the guides this format draws on suggest 128 bits as
sufficient; 256 costs nothing here and is what `hash_key`'s choice of a plain digest over a
slow KDF depends on -- see `hash_key`."""

_SECRET_LENGTH = 43
"""Base62 characters needed to carry `_SECRET_BITS`: 62**43 > 2**256 > 62**42. Pinned by a
test that checks both bounds, because an off-by-one here silently truncates entropy."""

_CHECKSUM_LENGTH = 6
"""Base62 characters for a CRC32. 62**6 (~5.7e10) comfortably exceeds 2**32 (~4.3e9), so the
digest always fits. GitHub uses the same six."""

EXPECTED_KEY_LENGTH = len(KEY_PREFIX) + _SECRET_LENGTH + _CHECKSUM_LENGTH
"""Every key this system issues is exactly this long (57).

**Changing any component invalidates every key already in the database**, because stored
digests are of the old format and presented keys of the new one would fail `looks_like_key`
before the lookup. Rotating the format is therefore a migration, not a constant edit: widen
the check to accept both shapes, let the old keys age out, then narrow it again."""

KEY_HASH_LENGTH = 128
"""Length of a `hash_key` result: SHA-512 as hex. Pinned by a test that hashes and measures,
so a change of hash function cannot slip through as a passing suite -- it would silently
invalidate every stored digest."""

PREFIX_DISPLAY_LENGTH = len(KEY_PREFIX) + 8
"""How much of a key is safe to store for display. 8 random characters is enough to tell
keys apart in a list while leaving the remaining ~200 bits unguessable."""


def _to_base62(value: int, length: int) -> str:
    """Left-zero-padded base62. Raises rather than truncating if `value` does not fit."""
    if value >= 62**length:
        msg = f"{value} does not fit in {length} base62 characters"
        raise ValueError(msg)
    digits = []
    for _ in range(length):
        value, remainder = divmod(value, 62)
        digits.append(_ALPHABET[remainder])
    return "".join(reversed(digits))


def _checksum(body: str) -> str:
    """CRC32 of everything before the checksum, base62-encoded.

    Covers the prefix as well as the random part, so a key whose prefix was mangled -- or one
    minted for a different environment -- fails the check too.
    """
    return _to_base62(zlib.crc32(body.encode("ascii")), _CHECKSUM_LENGTH)


def generate_key() -> str:
    """A fresh API key. Shown to the user exactly once -- only its hash is persisted.

    `secrets.randbits` then base62-encoded, rather than sampling the alphabet character by
    character: encoding one integer is uniform by construction, whereas a per-character
    `randbelow(62)` loop is easy to write with modulo bias and impossible to spot afterwards.
    """
    body = f"{KEY_PREFIX}{_to_base62(secrets.randbits(_SECRET_BITS), _SECRET_LENGTH)}"
    return f"{body}{_checksum(body)}"


def hash_key(key: str) -> str:
    """SHA-512 hex of the key, deliberately *not* argon2/bcrypt.

    Slow KDFs exist to make brute-forcing *low-entropy* secrets expensive -- passwords are
    guessable, so each guess must cost something. An API key here is 256 bits of CSPRNG
    output: there is no guessable structure to attack, so a KDF adds latency to every
    authenticated request while buying no security. It would also break the indexed-lookup
    property below.

    A plain digest keeps authentication O(1): hash the presented key and look the digest up
    on an indexed column. A KDF with a per-row salt cannot be looked up, forcing a scan and
    a verify against every stored key.

    **SHA-512 rather than SHA-256 is margin, not a fix.** The property that protects a stolen
    `key_hash` is the *input* entropy -- 256 bits of CSPRNG output is not invertible under
    either function, and neither has a practical preimage attack. The wider digest buys a
    larger cryptanalytic reserve against a future nobody can see, and costs ~0.25us per
    authentication and 64 extra characters per row, both of which round to nothing here. It
    was chosen while the `apikey` table was empty; changing the function later invalidates
    every stored digest at once, because the plaintext keys are deliberately not kept and no
    digest can be recomputed. **Treat this function as frozen** -- changing it is a re-key of
    every tenant, not a refactor.

    Rejected alternatives, so they aren't reproposed: SHA-512/256 is the better fit on paper
    (256-bit output, immune to length extension) but is **not** in `hashlib`'s guaranteed set
    -- it comes from OpenSSL, so a rebuild on a trimmed OpenSSL would break authentication
    everywhere at once, which is an unacceptable trade for a persisted digest. SHA-3 is
    guaranteed and sponge-based, but slower here for no benefit we rely on: length extension
    needs an `H(secret || message)` construction, and this hashes a whole key and compares
    digests.

    Passwords are a different problem with a different answer -- when Phase 5 adds password
    login, that path must use argon2id, not this function.
    """
    return hashlib.sha512(key.encode("utf-8")).hexdigest()


def display_prefix(key: str) -> str:
    return key[:PREFIX_DISPLAY_LENGTH]


def checksum_matches(value: str) -> bool:
    """Whether the trailing CRC32 agrees with the rest of the key.

    **This is an integrity check, not a security control, and must never be treated as one.**
    CRC32 is not cryptographic: anyone can compute a valid checksum for a string they chose.
    It proves a key was not mistyped or fabricated by accident. It proves nothing about
    whether the key was ever issued -- only the database lookup does that.

    What it buys is offline rejection. A secret scanner, a client library, or this service can
    discard a candidate that is merely *shaped* like a key without a round-trip, and the
    false-accept rate for a random 43-character string is 1 in 2**32. GitHub's stated reason
    was secret-scanning precision; the effect is smaller for us, because `pf_live_` is already
    a distinctive prefix, whereas the 40-char hex tokens they were replacing were
    indistinguishable from SHAs. The offline-validation property is what earns its place here.
    """
    body, checksum = value[:-_CHECKSUM_LENGTH], value[-_CHECKSUM_LENGTH:]
    return _checksum(body) == checksum


def looks_like_key(value: str) -> bool:
    """Cheap shape check so obvious non-keys never reach a database round-trip -- or a hash.

    Exact length, not a minimum. A minimum accepts an arbitrarily large body as a candidate
    key, and `resolve_tenant` would then hash all of it before finding nothing: unbounded
    work per unauthenticated request. nginx caps request *headers* at 8KB, which bounds it on
    the proxied path, but Streamlit calls `resolve_tenant` in process with no such ceiling.

    `isascii()` because base62 and the prefix are ASCII, so anything else cannot be one of our
    keys. It also makes `hash_key`'s `.encode()` total: for ASCII input, UTF-8 and ASCII
    encode to identical bytes, so this narrows the input space without changing any digest.

    Order matters. Length and prefix are compared first because they are the cheapest, and
    `checksum_matches` slices and CRCs the value -- there is no reason to do that work for a
    string that was never the right shape.

    This stays a boolean at the caller rather than a `raise` inside `hash_key`. `hash_key` is
    also called on freshly *generated* keys, where validating is pointless, and a raise there
    would turn a malformed header into an unhandled 500 instead of the 401 it should be.
    """
    return (
        value.isascii()
        and len(value) == EXPECTED_KEY_LENGTH
        and value.startswith(KEY_PREFIX)
        and checksum_matches(value)
    )
