"""Resolving a presented API key to a tenant. Separate from `deps.py` so the lookup can be
tested without FastAPI's dependency machinery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, or_
from sqlmodel import col, select

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.keys import hash_key, looks_like_key
from app.auth.models import ApiKey
from app.db import get_session

_LAST_USED_RESOLUTION_SECONDS = 60
"""`last_used_at` is refreshed at most this often per key. Writing it on every request would
add a database write to every authenticated call for a field nobody reads in real time; a
minute of staleness costs nothing and turns a per-request write into a rare one."""


@dataclass(frozen=True)
class Principal:
    """Who is calling: the tenant, the specific key, and what that key may do.

    The tenant alone was enough while every key was equivalent. It stopped being enough for
    two reasons at once -- rate limits are now per *key*, so the bucket needs `key_id`, and
    authorization is per *scope*, so the route needs `scopes`. Returning all three from one
    lookup keeps that a single query; deriving them separately would mean authenticating the
    same key two or three times per request.

    `scopes` is stored verbatim, empty list included. Interpreting it is `auth/scopes.py`'s
    job, because empty means *unrestricted* and that reading must live in exactly one place.
    """

    tenant_id: str
    key_id: str
    scopes: list[str]


async def resolve_tenant(presented_key: str | None) -> str | None:
    """The tenant a live key belongs to, or None. Thin wrapper over `resolve_principal`.

    Kept because most callers genuinely only want the retrieval scope -- Streamlit, and every
    route whose only use of auth is `tenant_id`. Narrowing at the boundary means those places
    cannot accidentally start depending on a key id or a scope list they were not asking for.
    """
    principal = await resolve_principal(presented_key)
    return principal.tenant_id if principal else None


async def resolve_principal(presented_key: str | None) -> Principal | None:
    """Return the caller a live key identifies, or None.

    Returns None for every failure -- absent, malformed, unknown, revoked, and expired -- so
    callers cannot accidentally tell a client *which* of those happened. Distinguishing "no
    such key" from "revoked key" leaks whether a key was ever valid.

    Note what is *not* here: scopes are returned, never enforced. Authorization is a decision
    about a particular route, so it belongs at that route (`deps.require_scopes`), and folding
    it in here would mean an authentication failure and an authorization failure came back as
    the same `None` -- which have to be a 401 and a 403 respectively.
    """
    if not presented_key or not looks_like_key(presented_key):
        return None

    digest = hash_key(presented_key)
    async with get_session() as session:
        # `col()` because at class level SQLModel types the attribute as its Python value
        # (`datetime | None`), which has no `.is_()`; col() surfaces the SQLAlchemy column.
        #
        # Liveness is expressed in the WHERE clause rather than checked in Python after the
        # fetch, for two reasons. It keeps a dead key indistinguishable from an unknown one --
        # both simply return no row, so there is no branch that could grow a different error
        # message later. And `func.now()` is the *database's* clock, so a skewed application
        # server cannot honour a key past its deadline; with several api processes, "expired"
        # has to mean one thing.
        statement = select(ApiKey).where(
            ApiKey.key_hash == digest,
            col(ApiKey.revoked_at).is_(None),
            or_(col(ApiKey.expires_at).is_(None), col(ApiKey.expires_at) > func.now()),
        )
        api_key = (await session.exec(statement)).first()
        if api_key is None:
            return None
        principal = Principal(tenant_id=api_key.tenant_id, key_id=api_key.id, scopes=list(api_key.scopes))
        await _touch(session, api_key)
        return principal


async def _touch(session: AsyncSession, api_key: ApiKey) -> None:
    """Bump `last_used_at`, but only past the resolution window -- see the constant.

    The subtraction below requires `previous` to be timezone-aware. That holds because this
    project runs on Postgres only and `models.py` declares the column
    `DateTime(timezone=True)`, which round-trips an aware value. There is deliberately no
    defensive normalization here: an explicit test
    (`test_stored_timestamps_come_back_timezone_aware`) pins that assumption instead, so
    dropping `timezone=True` fails loudly in CI rather than being silently absorbed.
    """
    now = datetime.now(UTC)
    previous = api_key.last_used_at
    if previous is not None and (now - previous).total_seconds() < _LAST_USED_RESOLUTION_SECONDS:
        return
    api_key.last_used_at = now
    session.add(api_key)
    await session.commit()
