"""The expiry menu. Pure -- no database, no request.

The interesting failure here is drift, not logic. `CreateKeyRequest.expires_in_days` spells its
choices as a `Literal` because that is what puts a real enum in the OpenAPI schema, while the
CLI builds its `--expires-in` choices from `EXPIRY_CHOICES` directly. Two spellings of one
list, so one test holds them together.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import get_args, get_type_hints

import pytest

from app.api.schemas import CreateKeyRequest
from app.auth.expiry import DEFAULT_EXPIRY_DAYS, EXPIRY_CHOICES, day_or_never, deadline, describe_state


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


def test_zero_days_is_refused_rather_than_meaning_never() -> None:
    """The falsy trap, pointing the wrong way: `deadline(0)` returned None, so the value that
    reads as "expire immediately" minted an eternal key. Unreachable through the API and the
    CLI, both of which offer a fixed choice set -- but `deadline` is a plain function and the
    next caller need not come through either.
    """
    with pytest.raises(ValueError, match="positive number of days"):
        deadline(0)
    with pytest.raises(ValueError, match="positive number of days"):
        deadline(-30)


# ---------------------------------------------------------------------------------------------
# How a key's state is *described*. One implementation, two consumers -- the CLI's `--list` and
# the Streamlit key page -- which is the point: it was written twice, with different wording, and
# the two are read side by side by the same person debugging the same key.
# ---------------------------------------------------------------------------------------------


def test_a_key_with_no_deadline_reads_as_active() -> None:
    """`expires_at IS NULL` means never, so this must not call it expired."""
    assert describe_state(revoked_at=None, expires_at=None) == "active"


def test_a_lapsed_deadline_is_shouted() -> None:
    """Uppercase on purpose: the whole point of the column is that a lapsed key is visible in a
    list of twenty, and "expired" in lower case reads like a heading.
    """
    assert describe_state(revoked_at=None, expires_at=datetime.now(UTC) - timedelta(days=1)).startswith("EXPIRED")


def test_a_live_deadline_reports_the_date() -> None:
    state = describe_state(revoked_at=None, expires_at=datetime.now(UTC) + timedelta(days=30))

    assert state.startswith("active until")


def test_revocation_wins_over_expiry() -> None:
    """A key that was revoked and has *since* lapsed is still a revocation story -- the
    deliberate act is the one worth reporting. Reversing these two branches turns "we cut this
    customer off" into "it aged out", which is a different conversation to have with them.
    """
    state = describe_state(
        revoked_at=datetime.now(UTC) - timedelta(days=2),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    assert state.startswith("revoked")


def test_a_missing_timestamp_renders_as_never_not_none() -> None:
    """`last_used_at` is NULL for a key that has never authenticated, and `str(None)` in a table
    column reads as a bug in the tool rather than a fact about the key.
    """
    assert day_or_never(None) == "never"
    assert day_or_never(datetime(2026, 8, 3, tzinfo=UTC)) == "2026-08-03"
