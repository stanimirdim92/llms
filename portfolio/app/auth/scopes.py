"""The permission vocabulary, and the rules for comparing sets of it.

Deliberately five strings. A scope list you can hold in your head is one people use
correctly; a taxonomy is one people paste from an example and stop reading.

Scopes hang off the **key**, not the tenant. The tenant already decides *what data* is
reachable -- that is the retrieval filter, and it is not negotiable per key. A scope decides
*what the holder may do with it*. Anything of the form `tenant.scopes` is a plan, not a
permission, and belongs somewhere else entirely.

Pure functions and constants only, no I/O and no FastAPI, so the rules below are testable
without a database or a request.
"""

from __future__ import annotations

ASK = "ask"
DOCUMENTS_READ = "documents:read"
DOCUMENTS_WRITE = "documents:write"
KEYS_READ = "keys:read"
KEYS_WRITE = "keys:write"

ALL_SCOPES: tuple[str, ...] = (ASK, DOCUMENTS_READ, DOCUMENTS_WRITE, KEYS_READ, KEYS_WRITE)
"""Every scope this system understands. The order is the order the UI and CLI list them in.

`keys:*` exist because key management is a capability like any other. Without them, any key
could mint any other key and the whole vocabulary would be decorative -- a read-only
dashboard key could issue itself a writer and nothing would have been restricted."""

UNRESTRICTED: list[str] = []
"""An empty scope list means **every** scope, not none.

This is the load-bearing back-compatibility decision and the one most likely to be
"corrected" by someone reading `if not key.scopes` and assuming it denies. Keys minted before
scopes existed have no list; the alternative reading would have revoked all of them the
moment the column shipped. Same rule as `expires_at IS NULL` meaning *never expires*: absent
data must mean the pre-existing behaviour, or adding a column becomes an outage.

The cost is that "unrestricted" and "not yet configured" are the same value. That is
acceptable while a key is minted by a human who sees the scope list; it stops being
acceptable if keys are ever created by an automated flow that could omit the field by
accident, and at that point the fix is a NOT NULL default rather than a new sentinel."""


def granted(scopes: list[str] | None) -> frozenset[str]:
    """Resolve a stored scope list to the set of scopes it actually confers."""
    return frozenset(ALL_SCOPES) if not scopes else frozenset(scopes)


def has_scope(scopes: list[str] | None, required: str) -> bool:
    return required in granted(scopes)


def unknown_scopes(requested: list[str]) -> list[str]:
    """Requested scopes this system does not define, in the order given.

    Rejecting these matters more than it looks: a typo'd `documents:wrote` would otherwise be
    stored happily and simply never match anything, producing a key that is silently unable
    to do the one thing it was created for.
    """
    known = frozenset(ALL_SCOPES)
    return [scope for scope in requested if scope not in known]


def exceeds(requested: list[str], holder: list[str] | None) -> list[str]:
    """Scopes in `requested` that `holder` cannot confer, in the order given.

    The privilege-escalation guard. A key may only grant what it already holds, so a
    `documents:read` key cannot mint a `documents:write` one and quietly promote itself. An
    unrestricted holder can grant anything, which follows from `granted` and is intended:
    that is what the human-minted bootstrap key is for.
    """
    held = granted(holder)
    return [scope for scope in requested if scope not in held]
