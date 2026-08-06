"""Flat table recording every ingested document, kept intentionally free of graph-shaped
columns -- this is groundwork for an eventual Neo4j sync job, not a graph model itself.
See docs/TECHNICAL_DECISIONS.md's "Database: Postgres, and only Postgres" section.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- must stay a runtime import; see below

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel

# `datetime` was previously imported under TYPE_CHECKING, and that was a real bug rather than a
# style question: `registry/db.py` calls `record.model_dump()`, and pydantic resolves the
# stringified annotations (`from __future__ import annotations` above) against this module's
# *runtime* globals at that point. With the name absent it raises
#   PydanticUserError: `DocumentRecord` is not fully defined; you should define `datetime`
# from inside model_dump -- so every registry write raised, after the Qdrant upsert had already
# succeeded. The visible symptom was a document searchable in Qdrant with no row in Postgres,
# which reads like a database problem rather than a missing import.
#
# The `sa_column=Column(DateTime(timezone=True))` on the fields below is still required and
# solves a *different* problem (see CLAUDE.md): it stops SQLModel inferring the column type from
# an unresolvable annotation at class-definition time. That one fails loudly at import; this one
# only failed when a row was actually written, which is why it survived.

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_INGESTED = "ingested"
STATUS_FAILED = "failed"


class DocumentRecord(SQLModel, table=True):
    doc_id: str = Field(primary_key=True)
    tenant_id: str = Field(index=True)
    """The owning tenant. Every row has a real one -- there is no shared/global tenant."""
    filename: str
    content_hash: str
    file_extension: str
    file_size_bytes: int
    chunk_count: int = Field(default=0)
    """0 until ingestion finishes -- a queued document has no chunks yet. Defaulted rather than
    nullable so callers don't have to handle None for a count.
    """
    ingestion_version: str | None = Field(default=None, index=True)
    """Which generation of this document's Qdrant points is live, or None if none is.

    Nullable because a `pending` row genuinely has no generation yet. **None means "not
    searchable"** -- `list_active_versions` requires it, and the retrieval filter admits only
    active versions, so a null here excludes the document rather than admitting all of its
    generations. The opposite reading would readmit every superseded point ever written.

    Set by `registry.db.activate_document_version`, which is the single UPDATE that publishes an
    ingest. Indexed because it is read on the `/ask` path for every request.
    """
    status: str = Field(default=STATUS_INGESTED, index=True)
    """One of the four constants above.

    `pending` -> queued, written by the upload route in the same transaction as the job.
    `processing` -> a worker has picked it up. `ingested` / `failed` are terminal for a given
    attempt; a retry moves a `failed` row back to `processing`, so this describes the latest
    attempt rather than the worst one.

    The default stays `ingested` because the one caller that bypasses the queue entirely --
    Streamlit, which runs the pipeline in process -- only ever writes a row once the work is
    already done. It said "two callers" and named one: the second was `scripts/ingest.py`, deleted
    with the curated corpus. Do not read the surviving single caller as making the default
    vestigial; it is still the only thing that makes the bypass path correct.

    Indexed because the natural queries are status-shaped: "what is still pending for this
    tenant", "what failed".
    """
    error_message: str | None = Field(default=None)
    """Set with `status="failed"`, cleared on a later success (the upsert overwrites it).

    Without this a failed ingest is indistinguishable from one that never happened -- the UI sees
    an absent or stale row either way and can only say "not there". Storing the exception type
    and message is the difference between "your PDF is encrypted" and silence.
    """
    uploaded_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    """Left unset on the Python side -- the DB's `server_default=now()` fills it in on
    first insert. Deliberately excluded from the upsert's UPDATE clause (see `db._upsert`) so a
    re-ingested document keeps its original ingestion timestamp rather than looking freshly
    created every time.
    """
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
    )
    """Maintained by the database, not by callers: `onupdate` fires on any UPDATE, so every status
    transition stamps it without each call site remembering to. This is what makes a stuck job
    detectable -- `processing` alone says nothing, `processing` since 40 minutes ago says the
    worker died.
    """
