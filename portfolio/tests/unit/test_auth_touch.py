"""`resolve_tenant` against a real Postgres.

Skipped when no Postgres is reachable, so the suite still runs on a machine without one --
but deliberately *not* substituted with SQLite. The app runs on exactly one engine, and
testing auth against a different one is how a backend-specific bug hides: the tz-comparison
bug these tests originally caught only reproduced because SQLite returns naive datetimes,
which is a fact about SQLite, not about this application. Better to skip honestly than to
pass against an engine that is never deployed.

Runs against `DATABASE_URL` with `_test` appended to the database name, created on demand,
so it cannot touch development data. CI provides the server (see portfolio-ci.yml).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth import service
from app.auth.keys import display_prefix, generate_key, hash_key
from app.auth.models import ApiKey, Tenant
from app.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    SessionFactory = Callable[[], AsyncSession]

TENANT_ID = "a" * 32


def _test_database_url() -> str:
    """The configured database with `_test` appended -- never the development database."""
    url = get_settings().database_url
    base, _, name = url.rpartition("/")
    return f"{base}/{name}_test"


async def _postgres_reachable(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect():
            return True
    except Exception:  # noqa: BLE001 -- any connection failure means "skip", not "fail"
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SessionFactory]:
    url = _test_database_url()
    if not await _postgres_reachable(url):
        pytest.skip(f"no Postgres at {url.rsplit('@', 1)[-1]} -- start it with docker compose")

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        # Drop first: a previous failed run may have left rows that would collide on the
        # fixed TENANT_ID primary key.
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    monkeypatch.setattr(service, "get_session", _session)
    yield factory
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


async def _seed(factory: SessionFactory, *, revoked: bool = False) -> str:
    """Insert a tenant and one key for it.

    The tenant is committed *before* the key, in a separate transaction, because
    `ApiKey.tenant_id` is a real foreign key and the models declare no ORM
    `relationship()` -- so SQLAlchemy has no dependency information to order the inserts
    with, and flushing both together violates the constraint. (SQLite accepted it: it does
    not enforce foreign keys by default. Postgres does, which is why these tests run on
    Postgres.)
    """
    key = generate_key()
    async with factory() as session:
        session.add(Tenant(id=TENANT_ID, name="Acme"))
        await session.commit()
    async with factory() as session:
        session.add(
            ApiKey(
                id=uuid.uuid4().hex,
                tenant_id=TENANT_ID,
                key_hash=hash_key(key),
                prefix=display_prefix(key),
                name="test",
                revoked_at=datetime.now(UTC) if revoked else None,
            )
        )
        await session.commit()
    return key


async def test_valid_key_resolves_to_its_tenant(db: SessionFactory) -> None:
    key = await _seed(db)

    assert await service.resolve_tenant(key) == TENANT_ID


async def test_repeated_use_does_not_raise(db: SessionFactory) -> None:
    """The second call compares the stored `last_used_at` against `datetime.now(UTC)`, so
    it exercises the arithmetic that a naive/aware mismatch would break.
    """
    key = await _seed(db)

    assert await service.resolve_tenant(key) == TENANT_ID
    assert await service.resolve_tenant(key) == TENANT_ID


async def test_stored_timestamps_come_back_timezone_aware(db: SessionFactory) -> None:
    """Pins the assumption `_as_aware` rests on: `DateTime(timezone=True)` on Postgres
    round-trips an aware value. If a schema change ever drops `timezone=True`, this fails
    here rather than as a TypeError deep in an authenticated request.
    """
    key = await _seed(db)
    await service.resolve_tenant(key)

    async with db() as session:
        stored = (await session.exec(select(ApiKey))).first()

    assert stored is not None
    assert stored.last_used_at is not None
    assert stored.last_used_at.tzinfo is not None


async def test_revoked_key_is_refused(db: SessionFactory) -> None:
    key = await _seed(db, revoked=True)

    assert await service.resolve_tenant(key) is None


async def test_unknown_and_malformed_keys_are_refused(db: SessionFactory) -> None:
    await _seed(db)

    assert await service.resolve_tenant(generate_key()) is None
    assert await service.resolve_tenant("garbage") is None
    assert await service.resolve_tenant(None) is None
    assert await service.resolve_tenant("") is None


async def test_first_use_records_last_used_at(db: SessionFactory) -> None:
    key = await _seed(db)
    await service.resolve_tenant(key)

    async with db() as session:
        stored = (await session.exec(select(ApiKey).where(ApiKey.key_hash == hash_key(key)))).first()

    assert stored is not None
    assert stored.last_used_at is not None


async def test_last_used_at_is_not_rewritten_within_the_window(db: SessionFactory) -> None:
    """A database write on every authenticated request, for a field nothing reads in real
    time, would be pure overhead -- so a second resolve inside the window must not write.
    """
    key = await _seed(db)
    await service.resolve_tenant(key)

    async with db() as session:
        stored = (await session.exec(select(ApiKey))).first()
        assert stored is not None
        first_write = stored.last_used_at

    await service.resolve_tenant(key)

    async with db() as session:
        stored = (await session.exec(select(ApiKey))).first()
        assert stored is not None
        assert stored.last_used_at == first_write


async def test_stale_last_used_at_is_refreshed(db: SessionFactory) -> None:
    key = await _seed(db)
    async with db() as session:
        stored = (await session.exec(select(ApiKey))).first()
        assert stored is not None
        stored.last_used_at = datetime.now(UTC) - timedelta(hours=1)
        session.add(stored)
        await session.commit()

    await service.resolve_tenant(key)

    async with db() as session:
        stored = (await session.exec(select(ApiKey))).first()
        assert stored is not None
        assert stored.last_used_at is not None
        assert stored.last_used_at > datetime.now(UTC) - timedelta(minutes=1)
