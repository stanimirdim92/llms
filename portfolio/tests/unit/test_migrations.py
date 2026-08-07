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

from app import db as app_db
from app.auth import models as _auth_models  # noqa: F401 -- populates SQLModel.metadata
from app.config import get_settings
from app.registry import models as _registry_models  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy import Connection
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
    except Exception:
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


def _head_revision() -> str:
    """The latest revision on disk, read from `migrations/`, never hardcoded.

    Asserting `is not None` was enough while there was exactly one revision, because then
    "versioned at all", "at head" and "at `_INITIAL_REVISION`" were the same statement. The second
    revision separated them, and the interesting one is `head`: a stamp that landed and then failed
    to apply anything on top still leaves a non-null version row.
    """
    from alembic.config import Config  # noqa: PLC0415
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    head = ScriptDirectory.from_config(Config(str(app_db._ALEMBIC_INI))).get_current_head()
    assert head is not None, "no revisions on disk: migrations/versions is empty"
    return head


async def _has_column(engine: AsyncEngine, table: str, column: str) -> bool:
    async with engine.connect() as conn:
        columns = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_columns(table))
    return any(col["name"] == column for col in columns)


async def _build_schema_at(engine: AsyncEngine, revision: str) -> None:
    """Materialise the schema exactly as of `revision`, then forget Alembic was ever involved.

    `SQLModel.metadata.create_all` was the obvious way to fake a pre-Alembic database, and it is
    wrong the moment a second revision exists: it builds *today's* models, so the table it created
    already had `ingestion_version` and the revision adding that column failed with
    `DuplicateColumn`. A fake right about the tables and wrong about the columns is the worst
    possible shape here, because a missing column is precisely what this suite exists to catch.
    Upgrading and dropping the version row leaves the real historical schema and stays correct as
    more revisions land.
    """
    from alembic import command  # noqa: PLC0415
    from alembic.config import Config  # noqa: PLC0415

    def _run(sync_conn: Connection) -> None:
        config = Config(str(app_db._ALEMBIC_INI))
        config.attributes["connection"] = sync_conn
        command.upgrade(config, revision)

    async with engine.begin() as conn:
        await conn.run_sync(_run)
        await conn.execute(text("DROP TABLE alembic_version"))


async def test_a_fresh_database_is_migrated_to_head(engine: AsyncEngine) -> None:
    await app_db.init_db()

    for table in _OUR_TABLES:
        assert await _has(engine, table), f"{table} missing after init_db"
    assert await _revision(engine) == _head_revision(), "the schema is not at the latest revision"


async def test_a_pre_alembic_database_is_stamped_rather_than_recreated(engine: AsyncEngine) -> None:
    """The upgrade path that would otherwise fail every boot.

    A database built by the old `create_all` has the tables and no `alembic_version`. Delete the
    stamp branch in `_migrate_to_head` and this goes red with
    `DuplicateTable: relation "documentrecord" already exists` -- confirmed by mutation.

    The stamp is at `_INITIAL_REVISION`, but the assertion is on **head**: stamping is only half the
    job, and a stamp that pinned a later revision would claim migrations had run that never did. The
    column check is what proves the revisions *after* the stamp actually applied -- `_OUR_TABLES`
    checks tables only, and a table that already exists is exactly what a missing column hides
    behind.
    """
    await _build_schema_at(engine, app_db._INITIAL_REVISION)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO tenant (id, name) VALUES ('t-existing', 'Acme')"))
    assert await _revision(engine) is None, "precondition: this simulates a database with no alembic_version"
    assert not await _has_column(engine, "documentrecord", "ingestion_version"), (
        "precondition: the pre-Alembic schema is the *initial* revision's, not today's models'"
    )

    await app_db.init_db()

    assert await _revision(engine) == _head_revision()
    assert await _has_column(engine, "documentrecord", "ingestion_version"), (
        "stamped but not upgraded: the revisions after the stamp did not apply"
    )
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
