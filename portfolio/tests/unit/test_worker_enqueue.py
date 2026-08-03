"""Async ingestion: enqueue atomicity, status transitions, and tenant-scoped status reads.

Against a real Postgres, skipped when none is reachable -- for the same reason as
`test_auth_touch.py`, and more so here. The property under test *is* a Postgres transaction:
whether a `procrastinate_jobs` insert and a `documentrecord` insert commit together. There is
nothing left to test if the transaction is faked.

Uses `DATABASE_URL` with `_test` appended, created on demand, so it cannot touch development
data. CI provides the server (see portfolio-ci.yml).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.ingestion.models import GLOBAL_TENANT
from app.registry.db import (
    get_document_record,
    list_document_records,
    list_scope_candidates,
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
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from fastapi import UploadFile

    SessionFactory = Callable[[], AsyncSession]

TENANT_A = "a" * 32
TENANT_B = "b" * 32
DOC_ID = "d" * 32


def _test_database_url() -> str:
    url = get_settings().database_url.get_secret_value()
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


async def _truncate(engine: AsyncEngine) -> None:
    """Empty every SQLModel table without dropping it.

    Row-level isolation is all these suites need, and unlike `drop_all` it cannot pull the
    schema out from under a sibling suite. CASCADE because `apikey.tenant_id` is a real
    foreign key, and RESTART IDENTITY so nothing carries a sequence across tests.
    """
    tables = ", ".join(f'"{table.name}"' for table in reversed(SQLModel.metadata.sorted_tables))
    if not tables:
        return
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


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
        # `create_all` only, never `drop_all`. Three suites here build the schema on the same
        # `portfolio_test` database, and a drop in one wipes the tables the next one relies on
        # `init_db` having created -- which surfaces as `relation "documentrecord" does not
        # exist` in a test that has nothing to do with whoever dropped it. Isolation comes from
        # truncating rows below, which is what these tests actually need.
        await conn.run_sync(SQLModel.metadata.create_all)
    # Truncate at *setup* as well as teardown. A test that errors mid-way skips its own
    # teardown, and the next test's fixture then collides inserting the same seed rows --
    # which reports as a setup ERROR in an innocent test and hides the original failure.
    await _truncate(engine)

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

    await _truncate(engine)
    async with engine.begin() as conn:
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
    """`doc_id` arrives from the client, so one tenant can paste another's -- out of a log, a
    screenshot, a support thread. (Not because ids collide: `upload_doc_id` salts with
    `tenant_id`.) A
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


async def test_concurrent_processes_can_initialise_the_schema() -> None:
    """`init_db` must survive several processes running it at once on an empty database.

    This is the failure that crashed a gunicorn worker on the first real boot: with
    GUNICORN_WORKERS=2, both workers ran `to_regclass('procrastinate_jobs')`, both saw nothing,
    and both applied procrastinate's schema. The loser got
    `DuplicateObject: type "procrastinate_job_status" already exists` and exited, which reads as
    a database fault rather than a race. The `worker` container runs `init_db` too, so it's three
    racers, not two.

    Uses real subprocesses because the bug is *cross-process*: `init_db`'s asyncio lock already
    serializes coroutines inside one process, so an `asyncio.gather` version of this test passes
    even with the advisory lock removed. Confirmed by removing it.
    """
    # Dropping the `db` fixture to get isolation also dropped its reachability check, so
    # without Postgres this failed instead of skipping -- contradicting the module docstring
    # and turning "no database here" into a red suite.
    if not await _postgres_reachable(_test_database_url()):
        pytest.skip("no Postgres reachable -- start it with docker compose")

    # A throwaway database of its own, not the shared `portfolio_test`. This test has to start
    # from an *empty* schema, and the only reliable way to get one is to drop everything --
    # procrastinate's schema.sql has 3 CREATE TYPE, 4 CREATE TABLE and 18 CREATE FUNCTION,
    # none `OR REPLACE`, so a hand-written drop list silently misses objects (an earlier
    # version left `procrastinate_job_event_type` behind and every subprocess failed on it,
    # which looked like the advisory lock not working).
    #
    # Doing that to the shared database is what made the whole suite flaky: three subprocesses
    # race to rebuild the schema, and whichever sibling suite ran next could observe it
    # half-built and die on `relation "documentrecord" does not exist` -- a failure that names
    # the registry and has nothing to do with it. Isolation, not ordering, is the fix.
    async with _scratch_database() as url:
        await _assert_concurrent_init_succeeds(url)


@asynccontextmanager
async def _scratch_database() -> AsyncIterator[str]:
    """Create an empty database for the duration, and drop it afterwards.

    `AUTOCOMMIT` because CREATE/DROP DATABASE cannot run inside a transaction block. The
    maintenance connection goes to `postgres`, which always exists.
    """
    base, _, _name = _test_database_url().rpartition("/")
    scratch = f"initdb_scratch_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{scratch}"'))
        yield f"{base}/{scratch}"
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        await admin.dispose()


async def _assert_concurrent_init_succeeds(url: str) -> None:
    code = "import asyncio, app.db; asyncio.run(app.db.init_db())"
    env = {**os.environ, "DATABASE_URL": url}

    async def _run_init() -> tuple[int | None, str]:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        return process.returncode, stderr.decode()

    # Spawned together and awaited together, so all three are inside init_db at once. Sequential
    # runs would pass with or without the lock.
    outcomes = await asyncio.gather(*(_run_init() for _ in range(3)))

    failures = [(code_, err.strip().splitlines()[-1] if err.strip() else "") for code_, err in outcomes if code_ != 0]
    assert not failures, f"concurrent init_db failed: {failures}"

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT to_regclass('procrastinate_jobs')"))).scalar() is not None
    finally:
        await engine.dispose()


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


async def test_listing_returns_only_this_tenants_documents(db: SessionFactory) -> None:
    """The endpoint behind "what documents do I have?".

    That question cannot be answered by /ask: retrieval matches chunks semantically, so a
    meta-question about the corpus gets grounded in whatever text is nearest in embedding space.
    A real user asked it and received a confident summary of one document's chunks -- including
    four figure "chunks" that were the vision model saying it couldn't see an image.
    """
    async with db() as session:
        await save_document_record(session, _record(tenant_id=TENANT_A, doc_id="a" * 32))
    async with db() as session:
        await save_document_record(session, _record(tenant_id=TENANT_B, doc_id="b" * 32))

    async with db() as session:
        mine = await list_document_records(session, tenant_id=TENANT_A)

    assert [record.doc_id for record in mine] == ["a" * 32]


async def test_listing_excludes_the_shared_corpus(db: SessionFactory) -> None:
    """Listing means uploads. Corpus documents are readable by every tenant and owned by
    none, so listing them as the tenant's own would misrepresent what they uploaded.
    """
    async with db() as session:
        await save_document_record(session, _record(tenant_id=GLOBAL_TENANT, doc_id="c" * 32))
    async with db() as session:
        await save_document_record(session, _record(tenant_id=TENANT_A, doc_id="a" * 32))

    async with db() as session:
        mine = await list_document_records(session, tenant_id=TENANT_A)

    assert [record.doc_id for record in mine] == ["a" * 32]


async def test_listing_respects_the_limit(db: SessionFactory) -> None:
    for index in range(5):
        async with db() as session:
            await save_document_record(session, _record(tenant_id=TENANT_A, doc_id=f"{index:032d}"))

    async with db() as session:
        limited = await list_document_records(session, tenant_id=TENANT_A, limit=2)

    assert len(limited) == 2


async def test_scope_candidates_include_the_shared_corpus(db: SessionFactory) -> None:
    """The integration half of finding H1, and the assertion whose absence let it ship.

    `/ask`'s own OpenAPI text and the README both promise that `doc_id=<bare arXiv id>` is
    how you scope a question to a curated paper. It resolved against `list_document_records`,
    which deliberately excludes `GLOBAL_TENANT` -- so following the README's copy-pasteable
    example returned 404 for one of the six papers the project ships. Unit tests on the
    resolver all passed, because their fixtures used a made-up tenant id.
    """
    async with db() as session:
        await save_document_record(session, _record(tenant_id=GLOBAL_TENANT, doc_id="c" * 32))
    async with db() as session:
        await save_document_record(session, _record(tenant_id=TENANT_A, doc_id="a" * 32))

    async with db() as session:
        candidates = await list_scope_candidates(session, tenant_id=TENANT_A)

    assert sorted(record.doc_id for record in candidates) == ["a" * 32, "c" * 32]


async def test_scope_candidates_still_exclude_other_tenants(db: SessionFactory) -> None:
    """Widening the candidate set to include the corpus must not widen it to everyone. The
    IN-list is two named values, so no crafted id can satisfy it -- same shape as the Qdrant
    filter, which is what keeps the two agreeing about what is readable.
    """
    async with db() as session:
        await save_document_record(session, _record(tenant_id=TENANT_B, doc_id="b" * 32))
    async with db() as session:
        await save_document_record(session, _record(tenant_id=TENANT_A, doc_id="a" * 32))

    async with db() as session:
        candidates = await list_scope_candidates(session, tenant_id=TENANT_A)

    assert [record.doc_id for record in candidates] == ["a" * 32]


async def test_the_shared_corpus_survives_a_tenant_with_more_documents_than_the_limit(
    db: SessionFactory,
) -> None:
    """The corpus gets its own budget, not a share of the caller's.

    One `IN (tenant, 'global') ORDER BY uploaded_at DESC LIMIT n` looks equivalent and is not:
    the curated corpus is the *oldest* content in the table, so a tenant with more recent
    uploads than the limit pushes every corpus row past the cut and gets H1's 404 back on
    every curated paper -- silently, and only for the busiest tenants.
    """
    async with db() as session:
        await save_document_record(session, _record(tenant_id=GLOBAL_TENANT, doc_id="c" * 32))
    for index in range(6):
        async with db() as session:
            await save_document_record(session, _record(tenant_id=TENANT_A, doc_id=f"{index:032d}"))

    async with db() as session:
        candidates = await list_scope_candidates(session, tenant_id=TENANT_A, limit=3)

    assert len(candidates) == 4, "3 of the tenant's own newest, plus the corpus on its own budget"
    assert "c" * 32 in [record.doc_id for record in candidates], "the corpus was crowded out"


async def test_the_staged_row_stores_a_content_digest_not_the_doc_id(
    db: SessionFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`content_hash` had two incompatible meanings in one column.

    The router wrote the tenant-salted 32-char `doc_id` here; `ingest_document` overwrote it with
    a plain 16-char digest on the terminal write. Same column, two values of different lengths and
    meanings, reconciled only by whichever write happened last -- harmless while nothing reads the
    field, which is exactly the state in which a column quietly becomes unusable.

    Driven through the route function rather than over HTTP because the assertion is about what
    the *staged* row holds, before any worker runs. `test_upload_paths.py` covers `content_digest`
    itself; this is the wiring, which is the half that was wrong.
    """
    monkeypatch.setattr(get_settings(), "upload_dir", tmp_path)
    payload = b"%PDF-1.4 upload body"

    class _Upload:
        filename = "paper.pdf"

        async def read(self) -> bytes:
            return payload

    from app.api.routers import documents as documents_router  # noqa: PLC0415 -- imports Docling-free
    from app.ingestion.uploads import content_digest, upload_doc_id  # noqa: PLC0415

    # Patched on the *router* module, not on `app.db`. The router does `from app.db import
    # get_session`, which binds the name at import time -- so patching `app.db.get_session`
    # reaches it only if the router happens to be imported afterwards. It was: this test passed
    # alone and wrote to the development database in the full suite, where an earlier module had
    # already imported the router.
    monkeypatch.setattr(documents_router, "get_session", _patched_session_factory(db))
    monkeypatch.setattr(documents_router, "init_db", _already_initialised)

    accepted = await documents_router.upload_document(file=cast("UploadFile", _Upload()), tenant_id=TENANT_A)

    async with db() as session:
        stored = await get_document_record(session, tenant_id=TENANT_A, doc_id=accepted.doc_id)
    assert stored is not None
    assert stored.content_hash == content_digest(payload)
    assert stored.content_hash != upload_doc_id(TENANT_A, payload), "the doc_id is what the bug stored"


def _patched_session_factory(factory: SessionFactory) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    return _session


async def _already_initialised() -> None:
    """The `db` fixture has created the schema; the route must not re-run `init_db` against the
    *real* DATABASE_URL, which is what it would do here.
    """
    return
