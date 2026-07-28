"""Resolving a presented API key to a tenant. Separate from `deps.py` so the lookup can be
tested without FastAPI's dependency machinery.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

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


async def resolve_tenant(presented_key: str | None) -> str | None:
    """Return the tenant a live key belongs to, or None.

    Returns None for every failure -- absent, malformed, unknown, and revoked -- so callers
    cannot accidentally tell a client *which* of those happened. Distinguishing "no such
    key" from "revoked key" leaks whether a key was ever valid.
    """
    if not presented_key or not looks_like_key(presented_key):
        return None

    digest = hash_key(presented_key)
    async with get_session() as session:
        # `col()` because at class level SQLModel types the attribute as its Python value
        # (`datetime | None`), which has no `.is_()`; col() surfaces the SQLAlchemy column.
        statement = select(ApiKey).where(ApiKey.key_hash == digest, col(ApiKey.revoked_at).is_(None))
        api_key = (await session.exec(statement)).first()
        if api_key is None:
            return None
        await _touch(session, api_key)
        return api_key.tenant_id


def _as_aware(value: datetime) -> datetime:
    """Normalize a datetime read back from the database to timezone-aware UTC.

    `models.py` declares these columns `DateTime(timezone=True)`, which is enough on
    Postgres -- but that is a per-backend guarantee, not a Python one. SQLite has no
    tz-aware type and hands back naive values, so subtracting `datetime.now(UTC)` raises
    "can't subtract offset-naive and offset-aware datetimes" on the *second* request with
    a given key. Verified, not assumed: see `test_auth_touch.py`.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _touch(session: AsyncSession, api_key: ApiKey) -> None:
    """Bump `last_used_at`, but only past the resolution window -- see the constant."""
    now = datetime.now(UTC)
    previous = api_key.last_used_at
    if previous is not None and (now - _as_aware(previous)).total_seconds() < _LAST_USED_RESOLUTION_SECONDS:
        return
    api_key.last_used_at = now
    session.add(api_key)
    await session.commit()
