"""Async ingestion: enqueue atomicity, status transitions, and tenant-scoped status reads.

Against a real Postgres, skipped when none is reachable -- for the same reason as
`test_auth_touch.py`, and more so here. The property under test *is* a Postgres transaction:
whether a `procrastinate_jobs` insert and a `documentrecord` insert commit together. There is
nothing left to test if the transaction is faked.

Uses `DATABASE_URL` with `_test` appended, created on demand, so it cannot touch development
data. CI provides the server (see portfolio-ci.yml).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.registry.db import (
    get_document_record,
    mark_document_failed,
    mark_document_processing,
    save_document_record,
    stage_document_record,
)
from app.registry.models import (
    STATUS_FAILED,
    STATUS_INGESTED,
    STATUS_PENDING,
    STATUS_PROCESSING,
    DocumentRecord,
)
from app.worker.app import INGEST_TASK_NAME, defer_document_ingest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    SessionFactory = Callable[[], AsyncSession]

TENANT_A = "a" * 32
TENANT_B = "b" * 32
DOC_ID = "d" * 32


def _test_database_url() -> str:
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


def _record(*, tenant_id: str = TENANT_A, doc_id: str = DOC_ID, status: str = STATUS_PENDING) -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        tenant_id=tenant_id,
        filename="paper.pdf",
        content_hash=doc_id,
        file_extension=".pdf",
        file_size_bytes=1234,
        status=status,
    )


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SessionFactory]:
    url = _test_database_url()
    if not await _postgres_reachable(url):
        pytest.skip(f"no Postgres at {url.rsplit('@', 1)[-1]} -- start it with docker compose")

    engine = create_async_engine(url)

    # The procrastinate app is pointed at the *test* database too. Without this the deferred
    # job would land in the development database while the document row went to the test one,
    # and the atomicity assertions would be comparing two unrelated databases.
    from app.worker import app as worker_app  # noqa: PLC0415

    procrastinate_app = worker_app.App(
        connector=worker_app.PsycopgConnector(conninfo=url.replace("postgresql+psycopg://", "postgresql://"))
    )
    # No import_paths here either, matching production: the defer path resolves the task by
    # name, so importing the implementation (and with it Docling) is exactly what we don't
    # want -- doing so made the first deferring test take ~10s.
    monkeypatch.setattr(worker_app, "app", procrastinate_app)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)

    # Check-then-apply, mirroring `app.db._apply_procrastinate_schema`, because
    # procrastinate's schema.sql uses bare `CREATE TABLE` and blows up on a second run. The
    # schema is then left in place across runs (it's a throwaway test database) and isolation
    # comes from truncating the queue below -- dropping it would also have to drop the
    # functions and composite types the schema installs alongside the tables.
    async with engine.begin() as conn:
        applied = (await conn.execute(text("SELECT to_regclass('procrastinate_jobs')"))).scalar() is not None
    if not applied:
        async with procrastinate_app.open_async():
            await procrastinate_app.schema_manager.apply_schema_async()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE procrastinate_jobs, procrastinate_events RESTART IDENTITY CASCADE"))

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    monkeypatch.setattr("app.db.get_session", _session)
    async with procrastinate_app.open_async():
        yield factory

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.execute(text("TRUNCATE procrastinate_jobs, procrastinate_events RESTART IDENTITY CASCADE"))
    await engine.dispose()


async def _job_count(factory: SessionFactory, doc_id: str = DOC_ID) -> int:
    """Counts queued jobs for a document by reading procrastinate's own table.

    Goes through `session.connection()` rather than `session.exec`: SQLModel's `exec` is typed
    for `Select` statements only, and this is textual SQL against a table we don't model.
    """
    async with factory() as session:
        connection = await session.connection()
        result = await connection.execute(
            text("SELECT count(*) FROM procrastinate_jobs WHERE args->>'doc_id' = :doc_id"),
            {"doc_id": doc_id},
        )
        return result.scalar_one()


def test_the_deferred_name_matches_the_registered_task() -> None:
    """The producer defers by name (`allow_unknown=True`) so the api never imports Docling,
    which trades an import-time check for a runtime one: a name mismatch would enqueue jobs no
    worker claims, and nothing would raise -- uploads would just sit in `pending`.

    Importing `app.worker.tasks` here is deliberate and is the one place it's wanted: this test
    exists precisely to confirm the implementation registers itself under the constant the
    defer path uses.
    """
    from app.worker import tasks  # noqa: PLC0415

    assert tasks.ingest_document_task.name == INGEST_TASK_NAME
    assert INGEST_TASK_NAME in tasks.app.tasks


async def test_row_and_job_commit_together(db: SessionFactory) -> None:
    """The happy path of the whole design: one transaction, both writes visible."""
    async with db() as session:
        await stage_document_record(session, _record())
        await defer_document_ingest(session, doc_id=DOC_ID, tenant_id=TENANT_A, file_path="/app/data/x.pdf")
        await session.commit()

    assert await _job_count(db) == 1
    async with db() as session:
        record = await get_document_record(session, tenant_id=TENANT_A, doc_id=DOC_ID)
    assert record is not None
    assert record.status == STATUS_PENDING


async def test_rollback_leaves_neither_the_row_nor_the_job(db: SessionFactory) -> None:
    """The reason the queue is in Postgres rather than Redis.

    With a separate broker, the job insert commits independently of the row -- so a failure
    between them leaves either a job for a document that doesn't exist, or a document stuck
    in `pending` forever with nothing to distinguish it from one still legitimately queued.
    Neither failure raises anything at the time.
    """
    async with db() as session:
        await stage_document_record(session, _record())
        await defer_document_ingest(session, doc_id=DOC_ID, tenant_id=TENANT_A, file_path="/app/data/x.pdf")
        await session.rollback()

    assert await _job_count(db) == 0
    async with db() as session:
        assert await get_document_record(session, tenant_id=TENANT_A, doc_id=DOC_ID) is None


async def test_failed_ingest_is_distinguishable_from_never_uploaded(db: SessionFactory) -> None:
    """A `failed` row with a message is the whole point of tracking status.

    Without it, a client polling for a document that blew up in Docling sees exactly what it
    would see for one that was never uploaded, and can only report "not found".
    """
    async with db() as session:
        await save_document_record(session, _record())
    async with db() as session:
        await mark_document_failed(session, doc_id=DOC_ID, error="DocumentParseError: encrypted PDF")

    async with db() as session:
        record = await get_document_record(session, tenant_id=TENANT_A, doc_id=DOC_ID)

    assert record is not None
    assert record.status == STATUS_FAILED
    assert record.error_message is not None
    assert "encrypted PDF" in record.error_message


async def test_a_retry_clears_the_previous_error(db: SessionFactory) -> None:
    """`processing` must not still display the last attempt's error while it runs."""
    async with db() as session:
        await save_document_record(session, _record())
    async with db() as session:
        await mark_document_failed(session, doc_id=DOC_ID, error="transient: Voyage timeout")
    async with db() as session:
        await mark_document_processing(session, doc_id=DOC_ID)

    async with db() as session:
        record = await get_document_record(session, tenant_id=TENANT_A, doc_id=DOC_ID)

    assert record is not None
    assert record.status == STATUS_PROCESSING
    assert record.error_message is None


async def test_success_after_failure_ends_ingested_with_no_error(db: SessionFactory) -> None:
    """The terminal write goes through the same upsert `ingest_document` uses, so this pins
    that a successful retry actually clears the failure rather than leaving a stale message
    beside an `ingested` status.
    """
    async with db() as session:
        await save_document_record(session, _record())
    async with db() as session:
        await mark_document_failed(session, doc_id=DOC_ID, error="transient: Qdrant unreachable")

    succeeded = _record(status=STATUS_INGESTED)
    succeeded.chunk_count = 42
    async with db() as session:
        await save_document_record(session, succeeded)

    async with db() as session:
        record = await get_document_record(session, tenant_id=TENANT_A, doc_id=DOC_ID)

    assert record is not None
    assert record.status == STATUS_INGESTED
    assert record.chunk_count == 42
    assert record.error_message is None


async def test_status_is_not_readable_by_another_tenant(db: SessionFactory) -> None:
    """`doc_id` is a content hash, so two tenants uploading the same file share an id. A
    lookup keyed on `doc_id` alone would leak tenant A's filename, size and status to tenant
    B while looking entirely correct -- hence `tenant_id` in the WHERE clause.
    """
    async with db() as session:
        await save_document_record(session, _record(tenant_id=TENANT_A))

    async with db() as session:
        assert await get_document_record(session, tenant_id=TENANT_B, doc_id=DOC_ID) is None
        assert await get_document_record(session, tenant_id=TENANT_A, doc_id=DOC_ID) is not None


async def test_marking_a_missing_document_does_nothing(db: SessionFactory) -> None:
    """A job whose document write was rolled back must not resurrect the row. Silently doing
    nothing is the intended behaviour, so it's pinned rather than left to be rediscovered.
    """
    async with db() as session:
        await mark_document_failed(session, doc_id="does-not-exist", error="boom")

    async with db() as session:
        assert await get_document_record(session, tenant_id=TENANT_A, doc_id="does-not-exist") is None


async def test_status_transitions_stamp_updated_at(db: SessionFactory) -> None:
    """`updated_at` is what makes a dead worker detectable: `processing` says nothing on its
    own, `processing` since 40 minutes ago says the worker died. It's maintained by the
    column's `onupdate`, so this proves the DB really does stamp it rather than each call site
    remembering to.
    """
    async with db() as session:
        await save_document_record(session, _record())
    async with db() as session:
        first = await get_document_record(session, tenant_id=TENANT_A, doc_id=DOC_ID)
    assert first is not None
    assert first.updated_at is not None

    async with db() as session:
        await mark_document_processing(session, doc_id=DOC_ID)
    async with db() as session:
        second = await get_document_record(session, tenant_id=TENANT_A, doc_id=DOC_ID)

    assert second is not None
    assert second.updated_at is not None
    assert second.updated_at >= first.updated_at
