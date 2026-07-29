"""The procrastinate app. Background ingestion runs through this.

Why a queue at all: ingestion takes 10s-2min (Docling parsing, one Anthropic vision call
per figure, one Voyage embedding call per chunk). Holding an HTTP request open for that
long means no progress, no cancel, and one gunicorn worker occupied per upload -- and
gunicorn's `--timeout` doesn't return a 504, it SIGKILLs the worker mid-parse.

Why procrastinate rather than the originally-planned `arq`: arq is in maintenance-only mode
upstream. Of the alternatives, procrastinate is async-native (matching `ingest_document` and
the async SQLAlchemy engine, where Celery and RQ would each need `asyncio.run()` per job)
and is backed by the Postgres already running, which is what makes `defer_document_ingest`
below atomic. See TECHNICAL_DECISIONS.md for the full comparison, including the one real
argument against it (rq's fork-per-job would contain a Docling segfault better).

**This module deliberately does not import `tasks.py`, and the worker CLI is pointed at
`app.worker.tasks.app` rather than at `app.worker.app.app`.** `tasks.py` imports the
ingestion pipeline, which imports Docling and torch -- roughly ten seconds and a few hundred
MB. The api only ever *enqueues*, so it has no business paying for the ingestion stack, and
under gunicorn `--preload` that cost would be multiplied across forked workers. The producer
therefore defers **by task name** (`app.configure_task`), which needs no import of the
implementation. Measured before doing it this way: the first upload spent ~10s importing
Docling inside the request.

The trade-off is that a wrong task name is no longer an import error. `INGEST_TASK_NAME` is
the single constant used by both the `@app.task` decorator and the defer below, so the two
cannot drift, and `test_worker_enqueue.py` asserts the registered name matches it.

The app is defined at module level, not inside a function or `__main__` -- a top-level app in
`__main__` is what procrastinate warns about, since it would be re-instantiated per
subprocess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from procrastinate import App, PsycopgConnector, RetryStrategy

from app.config import get_settings

if TYPE_CHECKING:
    import psycopg
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger(__name__)

INGEST_QUEUE = "ingest"
INGEST_TASK_NAME = "ingest_document"


def _conninfo() -> str:
    """Procrastinate talks to psycopg directly, so it needs a libpq DSN -- not SQLAlchemy's
    `postgresql+psycopg://` URL, whose driver suffix libpq doesn't understand.
    """
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


# No `import_paths`: that would make `configure_task` below import `tasks.py` (it calls
# `perform_import_paths()` first), reintroducing the Docling import into the api process that
# the module docstring explains. Task registration happens because the worker is launched
# against `app.worker.tasks.app` -- importing that module both registers the task on this app
# object and exposes it for the CLI.
app = App(connector=PsycopgConnector(conninfo=_conninfo()))

# Retries exist for the transient half of the failure modes -- an Anthropic 429 on figure
# captions, a Voyage timeout, Qdrant briefly unreachable. They cannot help the other half: a
# corrupt PDF fails identically every time, so the attempt cap is deliberately low rather
# than generous. Docling's own `document_timeout` is separate and handled inside the parser.
INGEST_RETRY = RetryStrategy(max_attempts=3, wait=5, exponential_wait=2)


async def defer_document_ingest(session: AsyncSession, *, doc_id: str, tenant_id: str, file_path: str) -> None:
    """Enqueue an ingest job **inside the caller's transaction**.

    This is the reason for a Postgres-backed queue. The job INSERT runs on the same
    connection as the caller's `DocumentRecord` write, so the two commit or roll back
    together. Without that there are two failure windows, and both are silent:

    - row committed, enqueue failed -> a document stuck in `pending` forever, with nothing
      to distinguish it from one that is merely still queued;
    - enqueue committed, row rolled back -> a job whose document doesn't exist, which the
      worker can only fail on.

    Verified rather than assumed: deferring inside a SQLAlchemy transaction and rolling back
    leaves zero rows in `procrastinate_jobs`; committing leaves one. `tests/unit/
    test_worker_enqueue.py` pins it.

    The caller must still `await session.commit()` -- this deliberately doesn't, since
    committing here would defeat the point.

    Defers **by name** rather than by importing the task, so this stays callable from the api
    without dragging in Docling. See the module docstring.
    """
    await app.configure_task(
        name=INGEST_TASK_NAME,
        allow_unknown=True,  # the implementation lives in the worker process, not this one
        connection=await _raw_connection(session),
        queue=INGEST_QUEUE,
    ).defer_async(doc_id=doc_id, tenant_id=tenant_id, file_path=file_path)


async def _raw_connection(session: AsyncSession) -> psycopg.AsyncConnection:
    """Unwrap SQLAlchemy's async session down to the psycopg 3 connection underneath it,
    which is what procrastinate's connector expects for an external connection.

    Three layers, and the reason it's this indirect is that each one is a real abstraction:
    the session's `AsyncConnection` (SQLAlchemy's async facade), its raw DBAPI connection
    (SQLAlchemy's sync-driver adapter), and `driver_connection` (the actual
    `psycopg.AsyncConnection`). Only the last one has the async cursor procrastinate needs.

    The type check is not defensive noise. `DB_DRIVER` is a `Settings` field, so someone can
    point this project at `postgresql+asyncpg` -- and then `driver_connection` is an asyncpg
    connection, which procrastinate's psycopg connector would fail on somewhere deep inside
    with an error naming neither the driver nor this function. SQLAlchemy also types this as
    `Any | None`, since a pool need not expose a driver connection at all. Both cases are
    configuration mistakes worth naming at the boundary.
    """
    import psycopg  # noqa: PLC0415 -- runtime-only, needed for the isinstance check below

    sa_connection = await session.connection()
    raw = await sa_connection.get_raw_connection()
    driver_connection = raw.driver_connection
    if not isinstance(driver_connection, psycopg.AsyncConnection):
        msg = (
            f"Transactional job enqueue needs a psycopg 3 async connection, got "
            f"{type(driver_connection).__name__}. DB_DRIVER must stay 'postgresql+psycopg'."
        )
        raise TypeError(msg)
    return driver_connection
