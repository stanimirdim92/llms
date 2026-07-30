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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncConnection

# Advisory-lock key serializing schema creation across processes. Arbitrary, but must be
# identical in every process: Postgres advisory locks are bare int64 keys in one global
# namespace per database, so this only has to avoid colliding with another user of the same
# database. Nothing else in this project takes advisory locks.
_SCHEMA_LOCK_KEY = 8_242_197_531_004_112


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

    Still no Alembic for our own tables. That's a real simplification rather than a shrug --
    with three tables a schema change means dropping the volume and re-ingesting. Revisit when
    there is data worth migrating rather than recreating. (procrastinate's tables are the
    exception; see `_apply_procrastinate_schema`.)
    """
    global _initialized  # noqa: PLW0603
    if _initialized:
        return

    async with _init_lock:
        if _initialized:  # another coroutine won the race while we waited
            return
        from app.auth import models as _auth_models  # noqa: F401, PLC0415
        from app.registry import models as _registry_models  # noqa: F401, PLC0415

        # The asyncio lock above only serializes coroutines *within one process*, which is not
        # the concurrency that matters here: gunicorn boots GUNICORN_WORKERS processes at once,
        # each running this lifespan, and the `worker` container runs it too. All of them raced
        # the DDL below. `create_all`'s checkfirst and procrastinate's existence check are both
        # check-then-create, so the loser gets a DuplicateObject/DuplicateTable at startup --
        # observed as `type "procrastinate_job_status" already exists`, which crashed a gunicorn
        # worker and read as a database fault rather than a race.
        #
        # A Postgres advisory lock is the cross-process equivalent. Transaction-scoped
        # (`_xact_`), so it releases when this block exits even if the DDL raises -- a
        # session-level lock leaked by a crashed process would deadlock every later boot.
        async with get_engine().begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEMA_LOCK_KEY})
            await conn.run_sync(SQLModel.metadata.create_all)
            # Inside the lock on purpose: a process that waited here must re-check rather than
            # act on what it saw before the winner ran.
            await _apply_procrastinate_schema(conn)
        _initialized = True


async def _apply_procrastinate_schema(conn: AsyncConnection) -> None:
    """Create procrastinate's tables/functions on first run.

    Must be called while holding `_SCHEMA_LOCK_KEY` -- it takes the passed-in connection rather
    than opening its own so the caller's lock genuinely covers the check and the apply.

    Done here rather than as a documented `procrastinate schema --apply` deploy step because a
    forgotten deploy step fails at runtime as "relation procrastinate_jobs does not exist" --
    the same confusing shape this module's docstring already warns about for un-imported model
    modules. One less thing to remember, failing at startup instead of on first upload.

    Guarded by an existence check because `procrastinate/sql/schema.sql` uses bare
    `CREATE TABLE`, not `IF NOT EXISTS` -- calling `apply_schema_async` unconditionally would
    fail on every start after the first. Checked, not assumed.

    **This covers the initial install only, not version upgrades.** Bumping procrastinate to a
    release that changes its schema still needs `procrastinate schema --migrate` (or the
    per-version SQL under `procrastinate/sql/migrations/`); this function will see the tables
    already there and do nothing. That's the honest boundary of the convenience.
    """
    from app.worker.app import app as procrastinate_app  # noqa: PLC0415 -- avoids an import cycle

    if (await conn.execute(text("SELECT to_regclass('procrastinate_jobs')"))).scalar() is not None:
        return

    # Runs on procrastinate's own pool, not `conn` -- its schema SQL is a single multi-statement
    # script its connector executes itself. That's a second connection, so the ordering matters:
    # this is awaited to completion (and its DDL committed) before the caller's transaction ends
    # and releases the advisory lock, which is what makes the next process see a finished schema
    # rather than a half-built one.
    async with procrastinate_app.open_async():
        await procrastinate_app.schema_manager.apply_schema_async()


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
