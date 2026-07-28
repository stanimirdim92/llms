"""Shared async SQLAlchemy engine and session, via psycopg 3's native asyncio support
(`postgresql+psycopg` + `create_async_engine` -- no separate async driver package needed,
unlike MySQL's psycopg2/aiomysql split).

Lives here rather than in `registry/db.py` (its previous home) because it is no longer
registry-specific: `app/auth/` needs the same engine, and having auth import from a module
named for the document registry would be misleading about what owns what.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    # Postgres' own client encoding is negotiated automatically by psycopg 3 and matches
    # the server's (UTF8, per docker-compose.yml's postgres POSTGRES_INITDB_ARGS) -- there
    # isn't a `charset` connect param the way MySQL needs `utf8mb4` to opt into full
    # 4-byte Unicode; plain Postgres UTF8 already covers that, so nothing to set here.
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,  # reconnect instead of surfacing a dead-connection error
        pool_recycle=settings.db_pool_recycle,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


_init_lock = asyncio.Lock()
_initialized = False


async def init_db() -> None:
    """Create tables that don't exist yet. Cheap to call repeatedly -- it does real work
    once per process and returns immediately afterwards.

    The run-once guard is not just tidiness: callers include `ingest_document`, so without
    it every single document ingest would pay a `create_all` metadata round-trip. The lock
    makes concurrent first calls (two uploads racing on a fresh process) do the DDL once
    rather than both attempting it.

    The imports below are load-bearing too: `SQLModel.metadata` is populated as a side
    effect of importing a model module, so a table whose module has never been imported is
    silently absent from `create_all` and only fails later, at query time, as a confusing
    "relation does not exist". Every table module must be imported here.

    Still no Alembic. That's a real simplification rather than a shrug -- with three tables
    a schema change means dropping the volume and re-ingesting. Revisit when there is data
    worth migrating rather than recreating.
    """
    global _initialized  # noqa: PLW0603
    if _initialized:
        return

    async with _init_lock:
        if _initialized:  # another coroutine won the race while we waited
            return
        from app.auth import models as _auth_models  # noqa: F401, PLC0415
        from app.registry import models as _registry_models  # noqa: F401, PLC0415

        async with get_engine().begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        _initialized = True


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
