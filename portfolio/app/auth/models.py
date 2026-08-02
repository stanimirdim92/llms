"""Tenant and API-key tables.

`Tenant.id` replaces the old client-supplied `session_id` as the retrieval scope, so it is
server-generated and never accepted from a request. Keys are stored hashed and can be
revoked individually, which is why they are a separate table rather than a column on
`Tenant`: one tenant holds many keys (laptop, CI, prod) and revoking one must not disturb
the others.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Column, DateTime, String, func
from sqlmodel import Field, SQLModel

if TYPE_CHECKING:
    from datetime import datetime

TENANT_ID_PATTERN = r"^[0-9a-f]{32}$"
"""`uuid7().hex`. Enforced wherever a tenant id becomes a filesystem path segment --
belt and braces, since ids are server-generated, but path building should never trust an
identifier's shape implicitly."""


class Tenant(SQLModel, table=True):
    id: str = Field(primary_key=True)
    """`uuid.uuid7().hex` -- time-ordered, so ids sort by creation and index well."""
    name: str
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )


class ApiKey(SQLModel, table=True):
    id: str = Field(primary_key=True)
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    key_hash: str = Field(index=True, unique=True)
    """SHA-512 hex of the full key (128 chars). Indexed because authentication is a single lookup
    on it -- see `keys.py` for why a plain digest rather than a password KDF, and why the
    function is frozen once keys exist."""
    prefix: str
    """The key's first few characters, kept so a key can be *identified* in a list without
    storing anything that could authenticate as it."""
    name: str
    """Human label ("ci", "laptop") -- the only way to tell keys apart once the secret is
    unrecoverable."""
    created_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    # Every datetime column here declares `sa_column` explicitly, and that is load-bearing
    # twice over. Without it SQLModel infers the column type from the annotation, which
    # `from __future__ import annotations` has turned into the string "datetime | None" --
    # unresolvable at runtime because `datetime` is imported only under TYPE_CHECKING, and
    # it fails as a confusing `issubclass() arg 1 must be a class` at import time. It also
    # pins `timezone=True`, so values read back are aware and compare correctly against
    # `datetime.now(UTC)` in `service.py` rather than raising on naive/aware mixing.
    last_used_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    revoked_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    """Revocation is a timestamp, not a delete: an audit trail of which key was used when
    is worth more than a clean table, and a deleted row can't answer "was this leaked key
    ever used?"."""
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String), nullable=False, server_default="{}"),
    )
    """What the holder of this key may do. **An empty list means every scope, not none** --
    see `auth/scopes.py::UNRESTRICTED` for why, and resist "fixing" it.

    A Postgres `ARRAY` rather than a join table: the set is tiny, fixed, and read on every
    authenticated request, so a second query to assemble a five-element list would be pure
    overhead. It is also never queried *by* scope -- the question is always "what may this
    key do", never "which keys may do X" -- which is the query shape that would justify
    normalising."""
    expires_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), index=True))
    """When the key stops working on its own. `NULL` means never.

    Separate from `revoked_at` on purpose, and the distinction is not cosmetic: revocation is
    a decision someone made, expiry is a deadline that was always going to arrive. Collapsing
    them into one column would make "did a human kill this key?" unanswerable, which is the
    first question asked after an incident.

    Indexed so a future sweep for keys about to lapse is a range scan rather than a table
    scan. Authentication itself doesn't need the index -- that lookup is already anchored on
    the unique `key_hash` -- but the column has to be *checked* there, which is the point:
    `NULL` was chosen as "never" so that keys minted before this column existed keep working
    rather than all expiring at once the moment it was added."""
