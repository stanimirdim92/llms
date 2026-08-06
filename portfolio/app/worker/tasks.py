"""Background job definitions. One task today: ingest an uploaded document.

Status ownership is split deliberately. This task owns `processing` and `failed`;
`ingest_document` itself owns the terminal `ingested` write, which is now the version flip
(`activate_document_version`) rather than an upsert -- it has to stay there because Streamlit calls
`ingest_document` directly and not through a queue. One writer per state, no duplicated logic.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import structlog

from app.config import require_provider_credentials
from app.db import get_session, init_db
from app.ingestion.pipeline import ingest_document
from app.registry.db import mark_document_failed, mark_document_processing
from app.vectorstore.qdrant_store import QdrantStore
from app.worker.app import INGEST_QUEUE, INGEST_RETRY, INGEST_TASK_NAME, app

log = structlog.get_logger(__name__)


@lru_cache
def _store() -> QdrantStore:
    """One store per worker process, built on first use rather than at import.

    Same reasoning as the routers' cached getters: constructing it at import time would open
    a Qdrant connection in the parent before any fork, which is exactly what the api's
    `--preload` comment warns against.
    """
    return QdrantStore()


@app.task(name=INGEST_TASK_NAME, queue=INGEST_QUEUE, retry=INGEST_RETRY)
async def ingest_document_task(doc_id: str, tenant_id: str, file_path: str, expected_digest: str | None = None) -> int:
    """Parse, chunk, embed and store one already-uploaded file.

    Takes `file_path` as a string because job arguments are JSON in Postgres -- a `Path`
    isn't serializable and would fail at defer time, not here.

    On failure this **tries** to record `status="failed"` with the message, and then re-raises.
    Both halves matter: without the record the API cannot tell a failed ingest from a document
    that was never uploaded (they look identical -- an absent or stale row), and without the
    re-raise procrastinate marks the job succeeded and never retries the transient cases.

    "Tries", stated precisely, because two paths still end with the row on `pending` and it is
    worse to believe otherwise:

    - **Postgres unreachable.** Then the `failed` write fails too, and the guarded handler below
      logs `worker.status_write_failed` and re-raises the original. The row keeps whatever status
      it had. Nothing else is possible from inside this task -- recording a database failure
      needs the database -- so the visible symptom is a `pending` row plus a worker log line,
      and the fix is the stuck-job sweeper in `docs/IDEAS.md`, not more code here.
    - **Cancellation.** `except Exception` does not catch `asyncio.CancelledError`, which is a
      `BaseException`, so a worker shut down mid-job leaves `pending`. Deliberate: swallowing
      cancellation to write a status would delay shutdown and mark as *failed* a job
      procrastinate will legitimately retry.

    A retry re-enters here and sets `processing` again, so a job that fails once and then
    succeeds moves failed -> processing -> ingested. Status always describes the latest
    attempt rather than the worst one, which is what a UI should show.
    """
    path = Path(file_path)
    # `expected_digest` defaults to None, and that default is a **compatibility boundary rather
    # than a convenience**. Job arguments are JSON rows already sitting in `procrastinate_jobs`
    # when a deploy lands, so a job enqueued before this parameter existed carries no
    # `expected_digest`; a required parameter would make every one of those fail permanently with
    # a TypeError that names nothing. Rule 8: absent data has to mean the pre-existing behaviour,
    # which here is "ingest without the integrity check" -- what it did before.
    #
    # It is logged at warning level rather than passed silently, because the pre-existing behaviour
    # is the one with the known defect. Anything still hitting this line weeks from now is a stuck
    # job, not a legacy one.
    if expected_digest is None:
        log.warning("worker.ingest_without_digest", doc_id=doc_id, tenant_id=tenant_id, path=file_path)
    log.info("worker.ingest_start", doc_id=doc_id, tenant_id=tenant_id)
    try:
        # `init_db` and the `processing` write are inside the try, not ahead of it. They were
        # ahead of it, and that left one path with no `failed` row at all: anything raised
        # while marking the row -- a pool timeout, a schema not yet applied, procrastinate's
        # own `DuplicateObject` on a racing boot -- skipped the handler below, so the document
        # stayed `pending` forever while procrastinate exhausted its retries and gave up.
        # `pending` is indistinguishable from "queued, worker busy", so the UI shows a
        # spinner that never resolves and nothing anywhere says why.
        await init_db()
        async with get_session() as session:
            await mark_document_processing(session, doc_id=doc_id)

        # Inside the try, and after the row is marked, so a missing key lands in
        # `error_message` like any other failure -- the person who uploaded the document reads
        # "ANTHROPIC_API_KEY not configured" instead of watching it sit in `pending`.
        # Deliberately per-job rather than at worker startup: raising on import would take down
        # the whole worker and break CI's import check, which runs without keys.
        require_provider_credentials()
        chunk_count = await ingest_document(
            doc_id=doc_id, file_path=path, store=_store(), tenant_id=tenant_id, expected_digest=expected_digest
        )
    except Exception as exc:
        # Broad on purpose: any failure must be visible in the row, and the specific
        # exception types span Docling, Anthropic, Voyage, Qdrant and psycopg.
        log.exception("worker.ingest_failed", doc_id=doc_id, tenant_id=tenant_id)
        try:
            async with get_session() as session:
                await mark_document_failed(session, doc_id=doc_id, error=f"{type(exc).__name__}: {exc}")
        except Exception:
            # The recording of a failure must not replace the failure. Now that the database
            # writes above are inside the try, the commonest reason to arrive here at all is
            # that Postgres is unreachable -- in which case this write fails too, and without
            # this guard the exception that propagates (and lands in the worker log as the
            # cause) is the *second* database error, with the real one demoted to a chained
            # __context__ nobody reads. The original is re-raised below either way.
            log.exception("worker.status_write_failed", doc_id=doc_id, tenant_id=tenant_id)
        raise

    log.info("worker.ingest_done", doc_id=doc_id, tenant_id=tenant_id, chunk_count=chunk_count)
    return chunk_count
