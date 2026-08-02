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
    return datetime.now(UTC) + timedelta(days=days) if days else None
