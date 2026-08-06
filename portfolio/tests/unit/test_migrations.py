"""Alembic owns our tables. These pin the three boots that have to work.

`create_all` created missing *tables* and never missing *columns*, so adding a field changed nothing,
`init_db` reported success, and the next query failed with `column ... does not exist`. Dropping the
volume was the workaround and it stopped being acceptable once Postgres held tenants and API keys,
which are not rebuildable. External review P0 #3, 2026-08-05.

Real Postgres, and these skip without it -- like every other service-backed suite here. CI asserts
they did not skip.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from app import db as app_db
from app.auth import models as _auth_models  # noqa: F401 -- populates SQLModel.metadata
from app.config import get_settings
from app.registry import models as _registry_models  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

_OUR_TABLES = ("tenant", "apikey", "documentrecord")


def _test_database_url() -> str:
    url = get_settings().database_url.get_secret_value()
    return url.rsplit("/", 1)[0] + "/portfolio_migrations_test"


async def _reachable(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect():
            return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def engine(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncEngine]:
    """An empty database per test, and `init_db`'s module state reset around it.

    `_initialized` is a module global that makes `init_db` a no-op after the first call. Without
    resetting it, the second test in this file silently asserts nothing.
    """
    url = _test_database_url()
    if not await _reachable(url):
        pytest.skip(f"no Postgres at {url.rsplit('@', 1)[-1]} -- create it with `createdb`, or start compose")

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    monkeypatch.setattr(app_db, "_initialized", False)
    monkeypatch.setattr(app_db, "get_engine", lambda: engine)

    # Point procrastinate at this database too. `_apply_procrastinate_schema` checks for its tables on
    # the connection it is handed but applies the schema on procrastinate's *own* pool -- fine in
    # production, where both are the same database, but without this the check runs here and the apply
    # lands on the development database, which already has the schema: `DuplicateObject: type
    # "procrastinate_job_status" already exists`.
    from app.worker import app as worker_app  # noqa: PLC0415

    monkeypatch.setattr(
        worker_app,
        "app",
        worker_app.App(
            connector=worker_app.PsycopgConnector(conninfo=url.replace("postgresql+psycopg://", "postgresql://"))
        ),
    )
    yield engine
    await engine.dispose()


async def _has(engine: AsyncEngine, table: str) -> bool:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(table))


async def _revision(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        if not await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table("alembic_version")):
            return None
        return (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()


async def test_a_fresh_database_is_migrated_to_head(engine: AsyncEngine) -> None:
    await app_db.init_db()

    for table in _OUR_TABLES:
        assert await _has(engine, table), f"{table} missing after init_db"
    assert await _revision(engine) is not None, "no alembic_version row: the schema is unversioned"


async def test_a_pre_alembic_database_is_stamped_rather_than_recreated(engine: AsyncEngine) -> None:
    """The upgrade path that would otherwise fail every boot.

    A database built by the old `create_all` has the tables and no `alembic_version`. Delete the
    stamp branch in `_migrate_to_head` and this goes red with
    `DuplicateTable: relation "documentrecord" already exists` -- confirmed by mutation.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.execute(text("INSERT INTO tenant (id, name) VALUES ('t-existing', 'Acme')"))
    assert await _revision(engine) is None, "precondition: this simulates a database with no alembic_version"

    await app_db.init_db()

    assert await _revision(engine) == app_db._INITIAL_REVISION
    async with engine.connect() as conn:
        survived = (await conn.execute(text("SELECT name FROM tenant WHERE id = 't-existing'"))).scalar()
    assert survived == "Acme", "existing rows must survive -- tenants and API keys are not rebuildable"


async def test_init_db_is_idempotent(engine: AsyncEngine) -> None:
    """It is called from `ingest_document` and every request path, so it runs constantly."""
    await app_db.init_db()
    first = await _revision(engine)

    app_db._initialized = False
    await app_db.init_db()

    assert await _revision(engine) == first


async def test_procrastinates_tables_are_left_alone(engine: AsyncEngine) -> None:
    """`migrations/env.py::include_object` filters them out of every comparison.

    Without that filter, autogenerate sees four tables absent from `SQLModel.metadata` and writes
    `drop_table` for each -- verified by removing the filter and regenerating, which produced
    exactly that. This asserts the runtime half: a migration run must not remove them.
    """
    await app_db.init_db()

    assert await _has(engine, "procrastinate_jobs")
    app_db._initialized = False
    await app_db.init_db()
    assert await _has(engine, "procrastinate_jobs"), "a second migration run dropped the job queue"


async def test_concurrent_first_boots_do_not_race_the_migration(engine: AsyncEngine) -> None:
    """Coroutines only, deliberately -- and it is explicitly *not* the guard for the real race.

    The cross-process race is covered by the concurrent-boot test in `test_worker_enqueue.py`,
    which spawns real subprocesses because an `asyncio.gather` version passes even with the
    advisory lock removed. This asserts the narrower
    thing that the per-process `asyncio.Lock` still serialises callers after the `create_all` to
    Alembic switch, so a second coroutine cannot see a half-migrated schema.
    """
    await asyncio.gather(*(app_db.init_db() for _ in range(4)))

    for table in _OUR_TABLES:
        assert await _has(engine, table)
