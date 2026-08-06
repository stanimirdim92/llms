"""Document-registry writes. The engine/session they run on lives in `app/db.py`, which
`app/auth/` shares -- see that module's docstring for why it moved out of here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select

from app.registry.models import STATUS_FAILED, STATUS_INGESTED, STATUS_PROCESSING, DocumentRecord

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
    `ingest_document`'s terminal write, and Streamlit.
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


async def list_ingested_doc_ids(session: AsyncSession, *, tenant_id: str) -> list[str]:
    """The tenant's documents that are actually searchable: `status == ingested`.

    Postgres is authoritative about that; Qdrant cannot be. The two are written in sequence
    (`ingest_document` upserts points, *then* the registry row), so a crash between them leaves
    retrievable chunks whose row says `processing` or `failed`. Without this, an unscoped `/ask`
    searched every point the tenant owned and could answer from a document reported as failed.

    Returns `[]` for a tenant with nothing ingested. That is a real answer, not a missing one --
    see `Retriever.retrieve`, which must not turn it into "search everything".
    """
    statement = (
        select(DocumentRecord.doc_id)
        .where(col(DocumentRecord.tenant_id) == tenant_id)
        .where(col(DocumentRecord.status) == STATUS_INGESTED)
    )
    return list((await session.exec(statement)).all())


async def list_document_records(session: AsyncSession, *, tenant_id: str, limit: int = 100) -> list[DocumentRecord]:
    """Every document this tenant owns, newest first.

    Exists because "what documents do I have?" is a *metadata* question, and asking it through
    /ask cannot work: retrieval matches chunks semantically, so a meta-question about a
    collection retrieves whatever happens to be nearest in embedding space and the answer is
    grounded in that. A real user asked exactly this and got a confident summary of one
    document's chunks.

    **This also serves `/ask`'s document scoping**, which used to need a separate
    `list_scope_candidates`. That function existed only because the curated corpus was readable
    by every tenant, so "what may I scope to" (`tenant_id IN (caller, 'global')`) was a strictly
    wider question than "what do I own". With the corpus removed the two are the same query, and
    keeping both would be two names for one thing -- which is how they came to disagree in the
    first place. Their disagreement was a real defect: `/ask`'s docs promised the `doc_id=`
    marker worked for the corpus, and it 404'd, because the candidate set came from the
    my-documents query.

    Callers that resolve a *name* pass a larger `limit` than callers that render a list; the
    scoping path asks for 200 where `GET /v1/documents` asks for 100. That is the only surviving
    difference, and it lives at the call site where it can be seen.
    """
    statement = (
        select(DocumentRecord)
        .where(DocumentRecord.tenant_id == tenant_id)
        .order_by(col(DocumentRecord.uploaded_at).desc())
        .limit(limit)
    )
    result = await session.exec(statement)
    return list(result.all())


async def get_document_record(session: AsyncSession, *, tenant_id: str, doc_id: str) -> DocumentRecord | None:
    """Fetch one document, scoped to its owning tenant.

    `tenant_id` is in the WHERE clause rather than checked against the result afterwards, and
    the reason is not the one this docstring used to give. It claimed `doc_id` is a content hash
    so two tenants uploading the same file share an id -- false: `upload_doc_id` salts the digest
    with `tenant_id` precisely so they do not, and a test asserts it.

    The real reason is simpler and does not depend on how ids are generated: `doc_id` arrives
    from the client. `GET /v1/documents/{doc_id}` passes through whatever was typed, and one
    tenant can paste another's id -- out of a shared log, a screenshot, a support thread. Without
    the tenant in the WHERE clause that returns tenant A's filename, size and status to tenant B,
    while looking entirely correct. With it, it is a 404.
    """
    statement = select(DocumentRecord).where(
        DocumentRecord.doc_id == doc_id,
        DocumentRecord.tenant_id == tenant_id,
    )
    result = await session.exec(statement)
    return result.first()
