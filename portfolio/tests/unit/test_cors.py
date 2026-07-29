"""CORS configuration, which is a security boundary once a browser UI exists.

These assert on `Settings` construction rather than on live responses: the dangerous
combination is rejected before an app is ever built, and that is the property worth
pinning. A response-level test would only prove Starlette behaves as Starlette does.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def test_wildcard_origins_are_allowed_without_credentials() -> None:
    """Today's default. Inert because a browser can't attach `x-api-key` cross-origin
    unless it's allow-listed, so nothing authenticated is reachable.
    """
    settings = Settings(cors_allow_origins=["*"], cors_allow_credentials=False)

    assert settings.cors_allow_origins == ["*"]


def test_credentials_with_wildcard_origins_is_refused() -> None:
    """The combination Starlette answers by reflecting the caller's own Origin back with
    `Access-Control-Allow-Credentials: true` -- i.e. any site can read authenticated
    responses. Must fail at construction, not at request time.
    """
    with pytest.raises(ValueError, match="any origin read authenticated responses"):
        Settings(cors_allow_origins=["*"], cors_allow_credentials=True)


def test_credentials_with_explicit_origins_is_allowed() -> None:
    """The shape a real frontend needs: named origins, credentials on."""
    settings = Settings(
        cors_allow_origins=["https://app.example.com"],
        cors_allow_credentials=True,
    )

    assert settings.cors_allow_credentials is True


def test_wildcard_buried_among_explicit_origins_is_still_refused() -> None:
    """`["https://app.example.com", "*"]` is exactly as permissive as `["*"]` alone --
    Starlette checks `"*" in allow_origins`, so one stray entry re-opens everything. A
    naive guard that only compared the list to `["*"]` would pass this.
    """
    with pytest.raises(ValueError, match="any origin read authenticated responses"):
        Settings(cors_allow_origins=["https://app.example.com", "*"], cors_allow_credentials=True)
