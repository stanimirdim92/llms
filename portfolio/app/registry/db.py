"""Async SQLAlchemy engine/session for the document registry, via psycopg 3's native
asyncio support (`postgresql+psycopg` + `create_async_engine` -- no separate async
driver package needed, unlike MySQL's psycopg2/aiomysql split). Async here matches
`ingest_document` now being async too, so a registry write never blocks a worker's
event loop while Postgres round-trips.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.registry.models import DocumentRecord

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


async def init_db() -> None:
    """Create tables that don't exist yet. Safe to call unconditionally on every
    process start (there are three callers: the API, Streamlit, and scripts/ingest.py)
    -- `create_all` is a no-op for tables that already exist. No Alembic for one table --
    revisit if a second table shows up.
    """
    async with get_engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def save_document_record(session: AsyncSession, record: DocumentRecord) -> None:
    """Upsert keyed on `doc_id`: re-ingesting identical content (already an idempotent
    upsert at the Qdrant layer via `upsert`-by-id) stays idempotent here too.

    `uploaded_at` is excluded from both the insert values and the ON CONFLICT update --
    see the field's docstring in `models.py` for why.
    """
    values = record.model_dump(exclude={"uploaded_at"})
    stmt = pg_insert(DocumentRecord).values(**values)
    update_columns = {key: getattr(stmt.excluded, key) for key in values if key != "doc_id"}
    stmt = stmt.on_conflict_do_update(index_elements=["doc_id"], set_=update_columns)
    await session.exec(stmt)  # SQLModel's Session.exec (not the deprecated raw .execute())
    await session.commit()
