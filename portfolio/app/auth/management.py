"""Creating, listing, and revoking API keys.

Lives here rather than in `api/routers/keys.py` because the Streamlit UI manages keys too, and
it calls this code *in process* -- the FastAPI dependency never runs for it. Two copies of the
privilege-escalation guard is one copy too many; that is the same reasoning as
`ingestion/uploads.py`, and the same reasoning that made Streamlit authenticate through
`auth.service` rather than mint a tenant id.

HTTP-agnostic, following that module's precedent: these raise their own exceptions and the
router translates them into status codes. A `KeyManagementError` reaching a client as a 500
means a route forgot to translate one, which is louder than a UI accidentally rendering an
`APIError` it had no business importing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import col, select

from app.auth.expiry import deadline
from app.auth.keys import display_prefix, generate_key, hash_key
from app.auth.models import ApiKey
from app.auth.scopes import ALL_SCOPES, exceeds, granted, unknown_scopes
from app.db import get_session, init_db
from app.ids import new_id

if TYPE_CHECKING:
    from app.auth.service import Principal


class KeyManagementError(Exception):
    """Base for the three refusals below, so a caller can catch them as one."""


class UnknownScopeError(KeyManagementError):
    """A scope this system does not define. Rejected rather than stored and ignored: a typo'd
    `documents:wrote` would otherwise produce a key that authenticates fine and silently
    cannot do the one thing it was created for.
    """

    def __init__(self, scopes: list[str]) -> None:
        self.scopes = scopes
        super().__init__(f"Unknown scope: {', '.join(scopes)}. Valid: {', '.join(ALL_SCOPES)}")


class ScopeEscalationError(KeyManagementError):
    """A key tried to grant something it does not hold. Without this, `keys:write` is
    equivalent to every scope and the vocabulary is decorative.
    """

    def __init__(self, scopes: list[str]) -> None:
        self.scopes = scopes
        super().__init__(f"Your key cannot grant a scope it lacks: {', '.join(scopes)}")


class NoSuchKeyError(KeyManagementError):
    """No key with that id *in this tenant*. Deliberately does not distinguish "not yours"
    from "does not exist" -- that would confirm a given key id is real.
    """

    def __init__(self) -> None:
        super().__init__("No such key in your tenant")


async def create_key(
    principal: Principal, name: str, scopes: list[str], expires_in_days: int | None
) -> tuple[str, ApiKey]:
    """Mint a key for the caller's own tenant. Returns the plaintext and the stored row.

    The plaintext is returned once and never stored -- only its hash -- so a lost key is
    revoked and replaced, never recovered.
    """
    if unknown := unknown_scopes(scopes):
        raise UnknownScopeError(unknown)
    if escalated := exceeds(scopes, principal.scopes):
        raise ScopeEscalationError(escalated)

    # An omitted scope list is written out as the caller's own scopes, never stored empty.
    # Storing it empty would mean *unrestricted*, so a key holding only `keys:write` could
    # mint itself an unrestricted one -- `exceeds([], holder)` is vacuously empty, so the
    # guard above never sees it. Materialising the set here is what closes that.
    held = granted(principal.scopes)
    resolved = scopes or [scope for scope in ALL_SCOPES if scope in held]

    key = generate_key()
    record = ApiKey(
        id=new_id(),
        tenant_id=principal.tenant_id,
        key_hash=hash_key(key),
        prefix=display_prefix(key),
        name=name,
        scopes=resolved,
        expires_at=deadline(expires_in_days),
    )
    await init_db()
    async with get_session() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)
    return key, record


async def list_keys(tenant_id: str) -> list[ApiKey]:
    """Every key belonging to one tenant, newest first.

    Revoked and expired keys included: the audit question is almost always about a key that
    no longer works.
    """
    await init_db()
    async with get_session() as session:
        # tenant_id in the WHERE clause, not an `if` afterwards -- the rule the whole codebase
        # follows, because filtering after the read means the other tenant's rows were read.
        statement = select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(col(ApiKey.created_at).desc())
        return list((await session.exec(statement)).all())


async def revoke_key(tenant_id: str, key_id: str) -> None:
    """Revoke one key, looked up by tenant *and* id. Idempotent -- revoking twice is not an
    error, because the second caller wanted the same end state as the first.

    Records a timestamp rather than deleting the row: a deleted row cannot answer "was this
    leaked key ever used?".
    """
    await init_db()
    async with get_session() as session:
        statement = select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
        api_key = (await session.exec(statement)).first()
        if api_key is None:
            raise NoSuchKeyError
        if api_key.revoked_at is None:
            api_key.revoked_at = datetime.now(UTC)
            session.add(api_key)
            await session.commit()
