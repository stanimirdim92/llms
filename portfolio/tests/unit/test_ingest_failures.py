"""What happens when an ingest goes wrong: the empty-document refusal, and the worker's
status bookkeeping around a failure.

No database and no Qdrant here, on purpose. `test_worker_enqueue.py` covers the parts that
*are* Postgres -- whether the row and the job commit together -- and it needs a real server for
that. What is left over, and what was untested, is pure control flow: which branch runs, what
gets recorded, and what propagates. Stubbing the recorders is the right instrument for that,
and it is also the only one that can express "the database write itself failed", which is the
case this module exists for.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

import pytest

from app.ingestion import pipeline
from app.ingestion.pipeline import EmptyDocumentError, ingest_document
from app.worker import tasks

if TYPE_CHECKING:
    from pathlib import Path

    from app.registry.models import DocumentRecord
    from app.vectorstore.qdrant_store import QdrantStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

DOC_ID = "d" * 32
TENANT = "t" * 32


class _RecordingStore:
    """Stands in for `QdrantStore`. Records rather than asserts, so a test can say *nothing*
    was written -- which is the interesting half of the empty-document case.
    """

    def __init__(self) -> None:
        self.upserted: list[list[object]] = []

    def upsert(self, chunks: list[object]) -> None:
        self.upserted.append(chunks)


@pytest.fixture
def store() -> _RecordingStore:
    return _RecordingStore()


# ---------------------------------------------------------------------------------------------
# The empty-document refusal
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def no_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A parse that succeeds and yields nothing -- a scanned, image-only PDF."""
    monkeypatch.setattr(pipeline, "_parse_and_chunk", lambda *_args: ([], "hash", 2048))


async def test_a_document_with_no_chunks_is_refused_not_recorded(
    no_chunks: None, store: _RecordingStore, tmp_path: Path
) -> None:
    """`ingested` with `chunk_count=0` is a lie the uploader can only discover by asking a
    question and getting someone else's document back. A real 2MB scanned flyer produced 30
    characters of text; recording that as a success is what this refusal replaced.
    """
    with pytest.raises(EmptyDocumentError):
        await ingest_document(
            doc_id=DOC_ID, file_path=tmp_path / "scan.pdf", store=cast("QdrantStore", store), tenant_id=TENANT
        )


async def test_the_refusal_happens_before_anything_is_written(
    no_chunks: None, store: _RecordingStore, tmp_path: Path
) -> None:
    """The order matters, and it is not obvious from reading the function top to bottom: the
    raise sits between the chunking and the upsert. If it moved below, an empty document would
    delete every point for its own `doc_id` -- `upsert` deletes first -- and so a re-upload of a
    document that had ingested correctly once could empty its own index.
    """
    with pytest.raises(EmptyDocumentError):
        await ingest_document(
            doc_id=DOC_ID, file_path=tmp_path / "scan.pdf", store=cast("QdrantStore", store), tenant_id=TENANT
        )

    assert store.upserted == []


async def test_the_refusal_names_the_file_and_no_setting(
    no_chunks: None, store: _RecordingStore, tmp_path: Path
) -> None:
    """The message used to tell the operator to enable `DO_OCR`, which does not exist and
    describes something already on -- so following the advice changed nothing and the second
    upload failed identically. It must name the file (a bulk upload fails one document at a
    time) and must not name a knob.
    """
    with pytest.raises(EmptyDocumentError) as excinfo:
        await ingest_document(
            doc_id=DOC_ID, file_path=tmp_path / "scan.pdf", store=cast("QdrantStore", store), tenant_id=TENANT
        )

    message = str(excinfo.value)
    assert "scan.pdf" in message
    assert "DO_OCR" not in message


# ---------------------------------------------------------------------------------------------
# The worker task's status bookkeeping
# ---------------------------------------------------------------------------------------------


class _Recorder:
    """Captures the sequence of status writes the task makes, and can be told to fail one."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_on: str | None = None

    async def processing(self, _session: object, *, doc_id: str) -> None:
        self._record("processing", doc_id)

    async def failed(self, _session: object, *, doc_id: str, error: str) -> None:
        self._record("failed", error)

    def _record(self, kind: str, detail: str) -> None:
        self.calls.append((kind, detail))
        if self.fail_on == kind:
            msg = f"the database is unreachable (while writing {kind})"
            raise RuntimeError(msg)

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.calls]


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """The task with every collaborator but its own control flow replaced."""
    recorder = _Recorder()

    @asynccontextmanager
    async def _session() -> AsyncIterator[object]:
        yield object()

    async def _init_db() -> None:
        return None

    def _a_store() -> object:
        return object()

    monkeypatch.setattr(tasks, "init_db", _init_db)
    monkeypatch.setattr(tasks, "get_session", _session)
    monkeypatch.setattr(tasks, "mark_document_processing", recorder.processing)
    monkeypatch.setattr(tasks, "mark_document_failed", recorder.failed)
    monkeypatch.setattr(tasks, "require_provider_credentials", lambda: None)
    monkeypatch.setattr(tasks, "_store", _a_store)
    return recorder


def _ingest_returning(count: int) -> Callable[..., Coroutine[None, None, int]]:
    async def _ingest(**_kwargs: object) -> int:
        return count

    return _ingest


def _ingest_raising(exc: Exception) -> Callable[..., Coroutine[None, None, int]]:
    async def _ingest(**_kwargs: object) -> int:
        raise exc

    return _ingest


async def test_a_successful_job_marks_processing_and_records_no_failure(
    worker: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "ingest_document", _ingest_returning(7))

    assert await tasks.ingest_document_task(doc_id=DOC_ID, tenant_id=TENANT, file_path="/tmp/a.pdf") == 7
    assert worker.kinds == ["processing"]


async def test_a_failing_ingest_is_recorded_and_re_raised(worker: _Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both halves. Without the record, a failed ingest and a document that was never uploaded
    look identical -- an absent or stale row. Without the re-raise, procrastinate marks the job
    succeeded and never retries the transient cases.
    """
    monkeypatch.setattr(tasks, "ingest_document", _ingest_raising(ValueError("bad pdf")))

    with pytest.raises(ValueError, match="bad pdf"):
        await tasks.ingest_document_task(doc_id=DOC_ID, tenant_id=TENANT, file_path="/tmp/a.pdf")

    assert worker.kinds == ["processing", "failed"]


async def test_the_recorded_error_names_the_exception_type(worker: _Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """`error_message` is what the uploader reads. A bare `str(exc)` is often empty -- a
    `KeyError` stringifies to just the key, a timeout to nothing at all -- so the type is
    prepended and must stay there.
    """
    monkeypatch.setattr(tasks, "ingest_document", _ingest_raising(TimeoutError()))

    with pytest.raises(TimeoutError):
        await tasks.ingest_document_task(doc_id=DOC_ID, tenant_id=TENANT, file_path="/tmp/a.pdf")

    assert worker.calls[-1][1].startswith("TimeoutError")


async def test_a_failure_while_marking_processing_still_lands_in_the_row(
    worker: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M6. `init_db` and the `processing` write used to sit *above* the try, so anything they
    raised skipped the handler entirely: no `failed` row, the document stuck on `pending`
    forever, and procrastinate quietly exhausting its retries. `pending` is indistinguishable
    from "queued, worker busy", so the only symptom was a spinner that never resolved.

    Move those two lines back above the `try` and this test goes red.
    """
    worker.fail_on = "processing"
    monkeypatch.setattr(tasks, "ingest_document", _ingest_returning(3))

    with pytest.raises(RuntimeError, match="while writing processing"):
        await tasks.ingest_document_task(doc_id=DOC_ID, tenant_id=TENANT, file_path="/tmp/a.pdf")

    assert worker.kinds == ["processing", "failed"]


async def test_the_original_error_survives_a_failure_to_record_it(
    worker: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Now that the database writes are inside the try, the commonest way to reach the handler
    is that Postgres is unreachable -- in which case recording the failure fails too. What
    propagates has to be the original: it is what the worker log names as the cause, and a
    second connection error there tells nobody why the ingest failed.
    """
    worker.fail_on = "failed"
    monkeypatch.setattr(tasks, "ingest_document", _ingest_raising(ValueError("the real problem")))

    with pytest.raises(ValueError, match="the real problem"):
        await tasks.ingest_document_task(doc_id=DOC_ID, tenant_id=TENANT, file_path="/tmp/a.pdf")


async def test_missing_provider_credentials_fail_the_job_not_the_worker(
    worker: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checked per job rather than at startup: raising at import would take down the whole
    worker (and break CI's import check, which runs without keys), whereas this way the reason
    reaches `error_message` and the person who uploaded the document reads it.
    """

    def _missing() -> None:
        msg = "ANTHROPIC_API_KEY not configured"
        raise RuntimeError(msg)

    monkeypatch.setattr(tasks, "require_provider_credentials", _missing)
    monkeypatch.setattr(tasks, "ingest_document", _ingest_returning(1))

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await tasks.ingest_document_task(doc_id=DOC_ID, tenant_id=TENANT, file_path="/tmp/a.pdf")

    assert worker.kinds == ["processing", "failed"]
    assert "ANTHROPIC_API_KEY" in worker.calls[-1][1]


# ---------------------------------------------------------------------------------------------
def test_the_parse_stage_computes_the_shared_content_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Where `content_hash`'s terminal value is actually produced.

    The first version of this test stubbed `_parse_and_chunk` and then asserted the digest it had
    itself supplied -- so reintroducing a second inline `hashlib.sha256(...)[:32]` in the real
    function left it green. Docling and the vision call are stubbed; the digest line is not.
    """
    from app.ingestion.uploads import content_digest  # noqa: PLC0415

    payload = b"%PDF-1.4 the parsed bytes"
    file_path = tmp_path / "paper.pdf"
    file_path.write_bytes(payload)
    monkeypatch.setattr(pipeline, "parse_document", lambda _path: object())
    monkeypatch.setattr(pipeline, "save_parsed_document", lambda _doc, _path: None)
    monkeypatch.setattr(pipeline, "extract_figures", lambda _doc, _dir: [])
    monkeypatch.setattr(pipeline, "chunk_document", lambda *_args, **_kwargs: [object()])
    monkeypatch.setattr(pipeline.get_settings(), "processed_dir", tmp_path)

    _chunks, content_hash, file_size = pipeline._parse_and_chunk(DOC_ID, file_path, TENANT)

    assert content_hash == content_digest(payload)
    assert len(content_hash) == 16
    assert file_size == len(payload)


async def test_the_terminal_write_records_the_same_content_digest_as_the_router(
    store: _RecordingStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the `content_hash` unification, and the half that decides what the column
    actually holds -- `ingest_document`'s write is the one that wins on a successful ingest.

    Reintroducing a second inline `hashlib.sha256(...)[:32]` here left the whole suite green, so
    only the router side was pinned. `test_worker_enqueue.py` covers the router; this covers the
    terminal write, and both assert against the same `content_digest`.
    """
    from app.ingestion.uploads import content_digest  # noqa: PLC0415

    payload = b"%PDF-1.4 the ingested bytes"
    file_path = tmp_path / "paper.pdf"
    file_path.write_bytes(payload)
    monkeypatch.setattr(pipeline, "_parse_and_chunk", lambda *_args: ([object()], content_digest(payload), 27))

    recorded: list[DocumentRecord] = []

    @asynccontextmanager
    async def _session() -> AsyncIterator[object]:
        yield object()

    async def _save(_session: object, record: DocumentRecord) -> None:
        recorded.append(record)

    monkeypatch.setattr(pipeline, "get_session", _session)
    monkeypatch.setattr(pipeline, "save_document_record", _save)
    monkeypatch.setattr(pipeline, "init_db", _noop)

    await ingest_document(doc_id=DOC_ID, file_path=file_path, store=cast("QdrantStore", store), tenant_id=TENANT)

    assert recorded, "the terminal registry write must happen"
    assert recorded[0].content_hash == content_digest(payload)
    assert len(recorded[0].content_hash) == 16


async def _noop() -> None:
    return None
