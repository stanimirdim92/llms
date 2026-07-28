"""`resolve_tenant` against a real database.

Uses in-memory SQLite rather than Postgres so it runs in the normal unit suite. That is
also what makes these tests worth having: SQLite returns *naive* datetimes because it has
no timezone-aware type, which is precisely the case that broke `_touch` when its
normalization was removed as "dead code". A Postgres-only test would have passed.
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

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    SessionFactory = Callable[[], AsyncSession]

TENANT_ID = "a" * 32


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Callable[[], AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    monkeypatch.setattr(service, "get_session", _session)
    yield factory
    await engine.dispose()


async def _seed(factory: Callable[[], AsyncSession], *, revoked: bool = False) -> str:
    key = generate_key()
    async with factory() as session:
        session.add(Tenant(id=TENANT_ID, name="Acme"))
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


async def test_repeated_use_does_not_raise_on_naive_timestamps(db: SessionFactory) -> None:
    """The regression this module exists for: the second call compares a stored
    `last_used_at` against `datetime.now(UTC)`, which raises TypeError if the stored value
    is naive and not normalized.
    """
    key = await _seed(db)

    assert await service.resolve_tenant(key) == TENANT_ID
    assert await service.resolve_tenant(key) == TENANT_ID


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
    time, would be pure overhead -- so the second resolve inside the window must not write.
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
        assert service._as_aware(stored.last_used_at) > datetime.now(UTC) - timedelta(minutes=1)
