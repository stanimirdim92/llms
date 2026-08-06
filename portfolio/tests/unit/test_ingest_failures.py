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
from structlog.testing import capture_logs

from app.ingestion import pipeline
from app.ingestion.pipeline import EmptyDocumentError, ingest_document
from app.worker import tasks

if TYPE_CHECKING:
    from pathlib import Path

    from app.vectorstore.qdrant_store import QdrantStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

DOC_ID = "d" * 32
TENANT = "t" * 32


class _RecordingStore:
    """Stands in for `QdrantStore`. Records rather than asserts, so a test can say *nothing*
    was written -- which is the interesting half of the empty-document case.

    `prune_error` injects a failure into `delete_superseded`, which is the one store call
    `ingest_document` is allowed to swallow.
    """

    def __init__(self) -> None:
        self.upserted: list[tuple[list[object], str]] = []
        self.pruned: list[tuple[str, str, str]] = []
        self.prune_error: Exception | None = None

    def upsert(self, chunks: list[object], ingestion_version: str) -> None:
        self.upserted.append((chunks, ingestion_version))

    def delete_superseded(self, doc_id: str, tenant_id: str, keep_version: str) -> None:
        if self.prune_error is not None:
            raise self.prune_error
        self.pruned.append((doc_id, tenant_id, keep_version))


@pytest.fixture
def store() -> _RecordingStore:
    return _RecordingStore()


# ---------------------------------------------------------------------------------------------
# The empty-document refusal
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def no_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A parse that succeeds and yields nothing -- a scanned, image-only PDF."""
    monkeypatch.setattr(pipeline, "_parse_and_chunk", lambda *_args: [])


async def test_a_document_with_no_chunks_is_refused_not_recorded(
    no_chunks: None, store: _RecordingStore, tmp_path: Path
) -> None:
    """`ingested` with `chunk_count=0` is a lie the uploader can only discover by asking a
    question and getting someone else's document back. A real 2MB scanned flyer produced 30
    characters of text; recording that as a success is what this refusal replaced.
    """
    with pytest.raises(EmptyDocumentError):
        await ingest_document(
            doc_id=DOC_ID,
            file_path=tmp_path / "scan.pdf",
            store=cast("QdrantStore", store),
            tenant_id=TENANT,
            expected_digest=None,
        )


async def test_the_refusal_happens_before_anything_is_written(
    no_chunks: None, store: _RecordingStore, tmp_path: Path
) -> None:
    """The order matters, and it is not obvious from reading the function top to bottom: the
    raise sits between the chunking and the upsert.

    It used to matter more than it does. While `upsert` deleted the document's points before
    inserting, moving this raise below it meant an empty re-upload emptied the index of a document
    that had ingested correctly once. `upsert` deletes nothing now, so the same mistake would
    instead flip the active version to a generation with no points in it -- a document that reports
    `ingested` and returns nothing. Cheaper, still wrong, and still worth pinning.
    """
    with pytest.raises(EmptyDocumentError):
        await ingest_document(
            doc_id=DOC_ID,
            file_path=tmp_path / "scan.pdf",
            store=cast("QdrantStore", store),
            tenant_id=TENANT,
            expected_digest=None,
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
            doc_id=DOC_ID,
            file_path=tmp_path / "scan.pdf",
            store=cast("QdrantStore", store),
            tenant_id=TENANT,
            expected_digest=None,
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

    # `_parse_and_chunk` returns chunks only now -- the digest it computes is used to *verify*
    # against `expected_digest`, not handed back for storage, because the flip updates a row the
    # upload already staged with the hash. So the assertion moved to the verification: matching
    # bytes pass, and the mismatch case is covered in `test_upload_paths.py`.
    chunks = pipeline._parse_and_chunk(DOC_ID, file_path, TENANT, content_digest(payload))

    assert chunks, "matching bytes must get past the digest check"


# ---------------------------------------------------------------------------------------------
# Publishing by flipping a version, and the two failures either side of the flip
# ---------------------------------------------------------------------------------------------
#
# There used to be a test here asserting `ingest_document` recorded `content_hash`. It doesn't any
# more: the terminal write is an UPDATE of the row the upload staged, and the hash is written once,
# by the stager. `test_worker_enqueue.py::test_the_staged_row_stores_a_content_digest_not_the_doc_id`
# is now the only pin on that column, which is the right number for a value with one writer.


@pytest.fixture
def flip(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Captures the arguments of every `activate_document_version` call, and nothing else.

    No database: what these tests are about is which call happens with which version, and
    `test_worker_enqueue.py` covers the half that genuinely is a Postgres UPDATE.
    """
    calls: list[dict[str, object]] = []

    @asynccontextmanager
    async def _session() -> AsyncIterator[object]:
        yield object()

    async def _activate(_session: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(pipeline, "get_session", _session)
    monkeypatch.setattr(pipeline, "activate_document_version", _activate)
    monkeypatch.setattr(pipeline, "init_db", _noop)
    return calls


async def test_the_published_version_is_the_one_that_was_upserted(
    store: _RecordingStore, flip: list[dict[str, object]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One ingest is one version, and the flip must name *that* version.

    This is the whole load-bearing join of the design and it is a single variable, so it looks too
    obvious to test. Mint a second `new_id()` for the flip -- an easy thing to do while refactoring,
    since both lines read fine in isolation -- and the upsert writes points under version A while
    the registry publishes version B. Every point is then filtered out by the version condition and
    the document reports `ingested` while retrieval finds nothing.
    """
    file_path = tmp_path / "paper.pdf"
    file_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pipeline, "_parse_and_chunk", lambda *_args: [object(), object()])

    chunk_count = await ingest_document(
        doc_id=DOC_ID,
        file_path=file_path,
        store=cast("QdrantStore", store),
        tenant_id=TENANT,
        expected_digest=None,
    )

    assert len(store.upserted) == 1
    _chunks, upserted_version = store.upserted[0]
    assert flip == [{"doc_id": DOC_ID, "tenant_id": TENANT, "ingestion_version": upserted_version, "chunk_count": 2}]
    assert chunk_count == 2


async def test_a_failed_flip_publishes_nothing_and_prunes_nothing(
    store: _RecordingStore, flip: list[dict[str, object]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flip is the commit point, so a failure there must leave the previous generation serving.

    Two things have to hold, and only the first is obvious. The error must propagate -- swallowing
    it would report a success that published nothing. And the prune must not run: it deletes every
    version *except* the one it is told to keep, so pruning to a version that was never activated
    would delete the generation still serving reads. That is the one way this design can lose data,
    and it is invisible in a test that only checks the exception.
    """
    file_path = tmp_path / "paper.pdf"
    file_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pipeline, "_parse_and_chunk", lambda *_args: [object()])

    async def _explode(_session: object, **_kwargs: object) -> None:
        raise RuntimeError("update lost the connection")

    monkeypatch.setattr(pipeline, "activate_document_version", _explode)

    with pytest.raises(RuntimeError, match="lost the connection"):
        await ingest_document(
            doc_id=DOC_ID,
            file_path=file_path,
            store=cast("QdrantStore", store),
            tenant_id=TENANT,
            expected_digest=None,
        )

    assert flip == []
    assert store.pruned == [], "pruning to an unpublished version would delete the live generation"


async def test_a_pruning_failure_does_not_fail_a_published_ingest(
    store: _RecordingStore, flip: list[dict[str, object]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hygiene must not be able to fail a publish that already succeeded.

    Once the flip lands, the superseded points are unreadable -- they carry a version no filter
    asks for. Leftovers cost storage and nothing else, so raising here would turn a correct,
    already-visible ingest into a reported failure and (through the worker) a `failed` row for a
    document that is serving answers. The warning is the whole observable effect, so it is asserted
    rather than assumed: without it the leak is silent and nothing would ever reclaim the space.
    """
    file_path = tmp_path / "paper.pdf"
    file_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pipeline, "_parse_and_chunk", lambda *_args: [object()])
    store.prune_error = RuntimeError("qdrant said no")

    with capture_logs() as logs:
        chunk_count = await ingest_document(
            doc_id=DOC_ID,
            file_path=file_path,
            store=cast("QdrantStore", store),
            tenant_id=TENANT,
            expected_digest=None,
        )

    assert chunk_count == 1
    assert len(flip) == 1, "the publish must stand"
    warnings = [entry for entry in logs if entry["event"] == "ingestion.prune_failed"]
    assert warnings, f"a swallowed prune failure must still be reported: {logs}"
    assert warnings[0]["log_level"] == "warning"
    assert "qdrant said no" in warnings[0]["error"]


async def _noop() -> None:
    return None
