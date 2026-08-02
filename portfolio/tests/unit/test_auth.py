"""Key handling and the shape of the auth boundary.

The database-backed parts of `resolve_tenant` need Postgres, so they belong in an
integration suite rather than here. What *is* testable without I/O -- and worth pinning --
is the key format, the hashing contract, and the fact that the request schemas no longer
accept a caller-supplied scope.
"""

import pytest
from pydantic import ValidationError

from app.api.schemas import AskRequest
from app.auth.keys import (
    _SECRET_BITS,
    _SECRET_LENGTH,
    EXPECTED_KEY_LENGTH,
    KEY_HASH_LENGTH,
    KEY_PREFIX,
    _checksum,
    checksum_matches,
    display_prefix,
    generate_key,
    hash_key,
    looks_like_key,
)


def test_generated_keys_are_unique_and_prefixed() -> None:
    keys = {generate_key() for _ in range(100)}

    assert len(keys) == 100
    assert all(key.startswith(KEY_PREFIX) for key in keys)


def test_generated_keys_have_real_entropy() -> None:
    """Guards against a refactor that makes keys predictable while still "working" -- the
    hashing choice in keys.py is only safe because the secret is high-entropy.
    """
    key = generate_key()
    secret = key.removeprefix(KEY_PREFIX)

    assert len(secret) >= 40


def test_the_random_part_carries_the_advertised_entropy() -> None:
    """An off-by-one in `_SECRET_LENGTH` silently truncates entropy and nothing else notices:
    keys still generate, still validate, still authenticate. Only this bound catches it.
    """
    assert 62**_SECRET_LENGTH > 2**_SECRET_BITS > 62 ** (_SECRET_LENGTH - 1)


def test_keys_are_alphanumeric_after_the_prefix() -> None:
    """Base62, not base64url. `-` terminates a double-click selection in most editors and
    terminals, so a user copying their key that way would get a fragment of it and see an
    opaque 401. The prefix's underscores are the only non-alphanumeric characters, and
    underscore does not break the selection -- which is why GitHub chose it as their separator.
    """
    assert all(generate_key().removeprefix(KEY_PREFIX).isalnum() for _ in range(200))


def test_hash_is_stable_and_key_specific() -> None:
    key, other = generate_key(), generate_key()

    assert hash_key(key) == hash_key(key)
    assert hash_key(key) != hash_key(other)
    assert len(hash_key(key)) == KEY_HASH_LENGTH


def test_the_hash_function_is_frozen() -> None:
    """A known input and its expected digest.

    `hash_key` is effectively immutable: the plaintext keys are never stored, so no digest can
    be recomputed, and swapping the function invalidates every row in `apikey` at once. A
    length check alone would not catch a change to another 512-bit hash, so this pins the
    exact bytes. If this test fails, the change is a re-key of every tenant -- not a refactor.

    The input is a hardcoded literal rather than one built from the format constants, so that
    changing the *key format* -- a different concern with its own cost -- does not force this
    digest to be recomputed and quietly rewritten.
    """
    digest = hash_key("pf_live_the-quick-brown-fox")

    assert digest == (
        "f47e0264038b1f3ea95e7bfb607e2927a34a145fdfb251c872af532b12c5d09b"
        "82d731e415d048eaaed67cf6530837bd340b4845e49e61fc9d8054ddaea823c3"
    )


def test_hash_does_not_contain_the_key() -> None:
    """A stored hash must not leak the secret it came from."""
    key = generate_key()

    assert key.removeprefix(KEY_PREFIX) not in hash_key(key)


def test_display_prefix_is_not_enough_to_authenticate() -> None:
    """The prefix is stored in plaintext to identify keys in a list, so it must be a small
    fraction of the secret -- not a usable credential.
    """
    key = generate_key()

    assert display_prefix(key) != key
    assert len(display_prefix(key)) < len(key) / 2


@pytest.mark.parametrize("value", ["", "nonsense", KEY_PREFIX, "sk-ant-something", KEY_PREFIX + "short"])
def test_malformed_values_are_rejected_before_any_lookup(value: str) -> None:
    assert not looks_like_key(value)


def test_real_key_passes_the_shape_check() -> None:
    assert all(looks_like_key(generate_key()) for _ in range(200))


def test_the_checksum_catches_a_single_altered_character() -> None:
    """What the checksum is actually for: a mistyped or truncated-and-repadded key is rejected
    offline, with no database round-trip and no ambiguous 401.
    """
    key = generate_key()
    for index in range(len(KEY_PREFIX), len(key)):
        swapped = "0" if key[index] != "0" else "1"
        assert not looks_like_key(key[:index] + swapped + key[index + 1 :]), index


def test_a_correctly_shaped_fabrication_is_rejected() -> None:
    """Right prefix, right length, right alphabet -- and still refused, because the checksum
    does not agree. This is the property a secret scanner uses to avoid false positives.
    """
    assert not looks_like_key(KEY_PREFIX + "A" * (EXPECTED_KEY_LENGTH - len(KEY_PREFIX)))


def test_the_checksum_covers_the_prefix() -> None:
    """So a key re-labelled for another environment fails rather than silently passing. There
    is no `pf_test_` yet, but the check must not be the thing that has to change when there is.
    """
    key = generate_key()

    assert not checksum_matches("pf_test_" + key.removeprefix(KEY_PREFIX))


def test_the_checksum_is_not_treated_as_authentication() -> None:
    """A guard against the dangerous misreading of `checksum_matches`. CRC32 is not
    cryptographic -- anyone can mint a string that passes it. It says "not mistyped", never
    "issued by us", and only the database lookup can say the latter.
    """
    forged = f"{KEY_PREFIX}{'z' * _SECRET_LENGTH}"

    assert looks_like_key(forged + _checksum(forged)), "a forgery passes the offline check"


def test_expected_length_matches_what_generate_key_actually_produces() -> None:
    """`EXPECTED_KEY_LENGTH` is a sum of three format constants, and if it disagreed with what
    `generate_key` emits, `looks_like_key` would reject every real key -- authentication would
    fail closed for everyone. Measured against generated keys, not asserted.
    """
    assert {len(generate_key()) for _ in range(200)} == {EXPECTED_KEY_LENGTH}


def test_an_oversized_value_is_rejected_without_being_hashed() -> None:
    """The reason the check is an exact length rather than a minimum.

    A prefixed multi-megabyte body used to satisfy the old `len(value) > 16` test, so
    `resolve_tenant` would hash the whole thing before discovering it matched nothing --
    unbounded work per unauthenticated request. nginx bounds request headers at 8KB on the
    proxied path, but Streamlit calls `resolve_tenant` in process with no such ceiling.
    """
    assert not looks_like_key(KEY_PREFIX + "A" * 10_000_000)


def test_a_correct_length_non_ascii_value_is_rejected() -> None:
    """The random part is base62, so a non-ASCII character cannot be one of our keys."""
    padding = "A" * (EXPECTED_KEY_LENGTH - len(KEY_PREFIX) - 1)

    assert not looks_like_key(KEY_PREFIX + padding + "é")


def test_ask_request_has_no_tenant_or_session_field() -> None:
    """Scope must come from the API key, never the body."""
    assert "tenant_id" not in AskRequest.model_fields
    assert "session_id" not in AskRequest.model_fields


@pytest.mark.parametrize("field", ["session_id", "tenant_id"])
def test_ask_request_rejects_a_smuggled_scope(field: str) -> None:
    """Rejected loudly, not ignored: a stale client passing the old field gets a 422 rather
    than silently receiving corpus-only answers and appearing to work.
    """
    with pytest.raises(ValidationError):
        AskRequest.model_validate({"question": "q", field: "someone-elses-tenant"})
