"""Document-registry writes. The engine/session they run on lives in `app/db.py`, which
`app/auth/` shares -- see that module's docstring for why it moved out of here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.registry.models import STATUS_FAILED, STATUS_PROCESSING, DocumentRecord

if TYPE_CHECKING:
    from sqlalchemy.dialects.postgresql import Insert
    from sqlmodel.ext.asyncio.session import AsyncSession


def _upsert(record: DocumentRecord) -> Insert:
    """Build the upsert keyed on `doc_id`, so re-ingesting a document updates its row
    rather than adding a second one.

    `uploaded_at`/`updated_at` are excluded from the values and from the ON CONFLICT update:
    the first keeps its original timestamp across re-ingests (see the field's docstring), and
    the second is maintained by the database's `onupdate`, so passing a Python value would
    override the very thing that makes it trustworthy.
    """
    values = record.model_dump(exclude={"uploaded_at", "updated_at"})
    stmt = pg_insert(DocumentRecord).values(**values)
    update_columns = {key: getattr(stmt.excluded, key) for key in values if key != "doc_id"}
    return stmt.on_conflict_do_update(index_elements=["doc_id"], set_=update_columns)


async def stage_document_record(session: AsyncSession, record: DocumentRecord) -> None:
    """Write the row **without committing**, so the caller can commit it alongside other work
    in the same transaction.

    This exists for exactly one caller -- the upload route, which must commit the row and the
    queue job together (see `worker/app.py::defer_document_ingest`). Split out rather than
    added as a `commit: bool` flag so the atomicity requirement stays legible at the call site
    instead of hiding in an argument.
    """
    await session.exec(_upsert(record))  # SQLModel's Session.exec (not the deprecated raw .execute())


async def save_document_record(session: AsyncSession, record: DocumentRecord) -> None:
    """Upsert and commit -- the path for everything that isn't the queued upload route:
    `ingest_document`'s terminal write, the corpus script, Streamlit.
    """
    await stage_document_record(session, record)
    await session.commit()


async def mark_document_processing(session: AsyncSession, *, doc_id: str) -> None:
    """Claim a document for a worker.

    Also clears `error_message`, because a retry still displaying the previous attempt's error
    while it runs is actively misleading.
    """
    await _set_status(session, doc_id=doc_id, status=STATUS_PROCESSING, error=None)


async def mark_document_failed(session: AsyncSession, *, doc_id: str, error: str) -> None:
    await _set_status(session, doc_id=doc_id, status=STATUS_FAILED, error=error)


async def _set_status(session: AsyncSession, *, doc_id: str, status: str, error: str | None) -> None:
    """Deliberately an UPDATE of an existing row rather than an upsert.

    If the row is missing this does nothing, which is the correct outcome rather than a
    swallowed error: the only way to get here without a row is a job whose document write was
    rolled back, and inventing a row for it would resurrect a document nobody uploaded.
    `updated_at` is left to the column's `onupdate`.
    """
    record = await session.get(DocumentRecord, doc_id)
    if record is None:
        return
    record.status = status
    record.error_message = error
    session.add(record)
    await session.commit()


async def get_document_record(session: AsyncSession, *, tenant_id: str, doc_id: str) -> DocumentRecord | None:
    """Fetch one document, scoped to its owning tenant.

    `tenant_id` is in the WHERE clause rather than checked against the result afterwards, and
    that matters here specifically: `doc_id` is a content hash, so two tenants uploading the
    same file get the *same* id. A lookup by `doc_id` alone would hand tenant B the filename,
    size, and status of tenant A's upload -- while looking entirely correct.
    """
    statement = select(DocumentRecord).where(
        DocumentRecord.doc_id == doc_id,
        DocumentRecord.tenant_id == tenant_id,
    )
    result = await session.exec(statement)
    return result.first()
