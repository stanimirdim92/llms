"""Key handling and the shape of the auth boundary.

The database-backed parts of `resolve_tenant` need Postgres, so they belong in an
integration suite rather than here. What *is* testable without I/O -- and worth pinning --
is the key format, the hashing contract, and the fact that the request schemas no longer
accept a caller-supplied scope.
"""

import pytest
from pydantic import ValidationError

from app.api.schemas import AskRequest
from app.auth.keys import KEY_PREFIX, display_prefix, generate_key, hash_key, looks_like_key


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


def test_hash_is_stable_and_key_specific() -> None:
    key, other = generate_key(), generate_key()

    assert hash_key(key) == hash_key(key)
    assert hash_key(key) != hash_key(other)
    assert len(hash_key(key)) == 64  # sha256 hex


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
    assert looks_like_key(generate_key())


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
