"""The expiry menu. Pure -- no database, no request.

The interesting failure here is drift, not logic. `CreateKeyRequest.expires_in_days` spells its
choices as a `Literal` because that is what puts a real enum in the OpenAPI schema, while the
CLI builds its `--expires-in` choices from `EXPIRY_CHOICES` directly. Two spellings of one
list, so one test holds them together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args, get_type_hints

from app.api.schemas import CreateKeyRequest
from app.auth.expiry import DEFAULT_EXPIRY_DAYS, EXPIRY_CHOICES, deadline


def test_the_default_is_one_of_the_choices() -> None:
    """A default outside the menu is a lifetime no client could ever ask for again."""
    assert DEFAULT_EXPIRY_DAYS in EXPIRY_CHOICES


def test_the_api_offers_exactly_the_choices_the_cli_does() -> None:
    annotation = get_type_hints(CreateKeyRequest)["expires_in_days"]
    offered = tuple(arg for arg in get_args(get_args(annotation)[0]))

    assert offered == EXPIRY_CHOICES
    assert type(None) in get_args(annotation), "`null` must stay available -- it is how 'never' is spelled"


def test_the_api_default_is_a_deadline_not_never() -> None:
    """Both are defensible; only one of them is safe as the value people get by *not*
    thinking about it. A credential handed to CI in 2026 should not still be live in 2030.
    """
    assert CreateKeyRequest(name="ci").expires_in_days == DEFAULT_EXPIRY_DAYS


def test_no_days_means_no_deadline() -> None:
    """`None` maps to `NULL`, and `NULL` means never -- the same rule as an empty scope list
    meaning every scope: absent data has to mean the pre-existing behaviour.
    """
    assert deadline(None) is None


def test_a_deadline_is_that_many_days_ahead_and_timezone_aware() -> None:
    """Aware, because it is compared against a Postgres `timestamptz`. A naive value would
    raise "can't subtract offset-naive and offset-aware datetimes" at authentication time.
    """
    before = datetime.now(UTC)

    result = deadline(30)

    assert result is not None
    assert result.tzinfo is not None
    assert 29.9 < (result - before).total_seconds() / 86400 < 30.1
