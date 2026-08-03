"""How long a new key lives. One list of choices, two consumers (the API and the CLI).

A fixed menu rather than a free integer, and that is the whole point of the module. An
arbitrary `--expires-in 4000` is not a lifetime anyone chose; it is a typo that reads as a
decision. Four durations cover the real cases -- a month for a laptop, a quarter for CI, a
year for something embedded in a deployment -- and `never` stays available because some keys
genuinely outlive any deadline someone would set for them.

The default is 30 days, not "never". Both are defensible; only one of them is safe as the
value people get by *not* thinking about it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

EXPIRY_CHOICES: tuple[int, ...] = (30, 60, 90, 365)
"""Selectable lifetimes in days, shortest first -- the order the API enum, the CLI, and the
UI all present them in."""

DEFAULT_EXPIRY_DAYS = 30
"""What you get by omission. Must stay a member of `EXPIRY_CHOICES`; `tests/unit/test_key_expiry.py`
pins that, because a default outside the menu is a value no client can ask for again."""

NEVER = "never"
"""The CLI spelling for "no deadline". Over the wire the same thing is `null`, because JSON
has a word for absent and inventing a magic string would make the field a union of an integer
and a sentinel for no reason."""


def deadline(days: int | None) -> datetime | None:
    """The instant a key minted *now* should stop working, or None for never.

    Computed in the application rather than as a Postgres `now() + interval` because the value
    is written once at creation, where a second of clock skew is meaningless. Enforcement is
    the opposite case and uses the database clock deliberately -- see `auth/service.py`.
    """
    # `is None`, not a falsy test. `deadline(0)` used to mean "never expires" -- the same as
    # omitting it -- which is the falsy trap rule 8 warns about, pointing the wrong way: the
    # value that reads as "expire immediately" granted an eternal key. Unreachable through the
    # API today because the schema is a fixed `Literal`, but `deadline` is a plain function
    # and the next caller need not come through the schema.
    if days is None:
        return None
    if days <= 0:
        msg = f"expiry must be a positive number of days, got {days}; pass None for a key that never expires"
        raise ValueError(msg)
    return datetime.now(UTC) + timedelta(days=days)


def day_or_never(value: datetime | None) -> str:
    """A date for display, or the word "never".

    `str(None)` in a table column reads as a bug in the tool rather than a fact about the key,
    which is what "never" is: `NULL` means no deadline, the same rule as an empty scope list
    meaning every scope.
    """
    return f"{value:%Y-%m-%d}" if value else "never"


def describe_state(*, revoked_at: datetime | None, expires_at: datetime | None, with_dates: bool = True) -> str:
    """One phrase answering "can this key authenticate right now, and if not why not".

    Lives here, in the module that owns the expiry vocabulary, because it had been implemented
    twice -- once in `scripts/create_tenant.py` and once in the Streamlit key page. Both were
    correct; both were free to drift on the next edit to either, and the two are read side by side
    by the same person debugging the same key.

    **`with_dates` exists because the two implementations differed in content, not only in
    wording**, and the first version of this function flattened that difference. The CLI embeds
    dates (`revoked 2026-08-01`) because a fixed-width text table has nowhere else to put them;
    the Streamlit page returned bare `revoked`/`expired`/`active` because its dataframe already has
    `expires` and `last used` as separate columns. Unifying on the CLI wording printed the expiry
    date twice per row and put a shouty `EXPIRED` inside a dataframe cell. Rule 6: the conflict was
    real, so it is surfaced as a parameter rather than averaged away.

    Takes the two timestamps rather than an `ApiKey`, so nothing in `app/auth/` has to import a
    table model to render a string, and so a caller holding an API *response* (which has the
    same two fields and is not an `ApiKey`) can use it too.

    **Order matters.** Revocation is reported ahead of expiry because it is the deliberate act:
    a key that was revoked *and* has since lapsed is still a revocation story, and reversing
    these two turns "we cut this customer off" into "it aged out", which is a different
    conversation to have with them.

    Wall-clock `now()` here, unlike enforcement in `auth/service.py`, which uses the *database*
    clock. Deliberate: this is display, and a second of skew in a rendered table costs nothing,
    whereas "expired" as an authorization outcome has to mean one thing across several api
    processes.
    """
    if revoked_at:
        return f"revoked {day_or_never(revoked_at)}" if with_dates else "revoked"
    if expires_at is None:
        return "active"
    if expires_at <= datetime.now(UTC):
        return f"EXPIRED {day_or_never(expires_at)}" if with_dates else "expired"
    return f"active until {day_or_never(expires_at)}" if with_dates else "active"
