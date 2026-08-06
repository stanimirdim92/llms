"""Document-registry writes. The engine/session they run on lives in `app/db.py`, which
`app/auth/` shares -- see that module's docstring for why it moved out of here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import update
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
    """Write the row **and commit it**. For a caller with nothing to commit alongside it.

    That is Streamlit, and it is the only one: it bypasses the queue, so it has no job insert to be
    atomic with, but it still has to leave a real `pending` row behind because `ingest_document`
    publishes by *updating* one.

    **Deleted 2026-08-06 and restored the same day**, which is the part worth keeping. It was
    removed as dead code after `ingest_document`'s terminal write became an UPDATE -- a reverse
    search found only tests calling it, so it looked like production code kept alive by its own test
    suite. The reverse search was right and the conclusion was wrong: the caller existed, in
    `streamlit_app/Home.py`, and it was calling `stage_document_record` instead. So every Streamlit
    upload wrote points to Qdrant and then died on the flip with `DocumentNotFoundError`, because the
    staged row was never committed and vanished when the session closed. The missing caller was a
    *symptom of the bug*, not evidence there was no caller.

    Two lessons, both cheap to state and expensive to relearn: a function whose only callers are
    tests may mean a broken caller rather than a dead function, and Streamlit is the one write path
    with no test, so "nothing references this" is weakest exactly where it is least verifiable.
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


async def list_active_versions(session: AsyncSession, *, tenant_id: str) -> dict[str, str]:
    """The tenant's searchable documents, mapped to the generation of points that is live.

    Postgres is authoritative about both halves and Qdrant can know neither. A document is
    searchable when `status == ingested` **and** it has an `ingestion_version`, because the version
    is what the retrieval filter admits: points from any other generation are unreadable.

    `ingestion_version IS NOT NULL` is not belt-and-braces. A `pending` row has no version yet, and
    a row could in principle be `ingested` with none -- which must mean "not searchable" rather than
    "search every generation", since the second reading readmits every superseded point ever
    written.

    Returns `{}` for a tenant with nothing searchable. A real answer, not a missing one -- see
    `Retriever.retrieve`, which must not turn it into "search everything".
    """
    statement = (
        select(DocumentRecord.doc_id, DocumentRecord.ingestion_version)
        .where(col(DocumentRecord.tenant_id) == tenant_id)
        .where(col(DocumentRecord.status) == STATUS_INGESTED)
        .where(col(DocumentRecord.ingestion_version).is_not(None))
    )
    rows = (await session.exec(statement)).all()
    return {doc_id: version for doc_id, version in rows if version is not None}


class DocumentNotFoundError(Exception):
    """The row a write expected is not there."""


async def activate_document_version(
    session: AsyncSession, *, doc_id: str, tenant_id: str, ingestion_version: str, chunk_count: int
) -> None:
    """Make `ingestion_version` the live generation; this single UPDATE is the commit point.

    Points for this version are already in Qdrant and unreadable until this lands; nothing before
    it published anything, and nothing after it is required for correctness. One statement, so a
    reader in another transaction sees the old version or the new one and never a document that is
    searchable at no version.

    **Raises rather than no-oping on a missing row**, unlike `_set_status`. There the silence is
    right -- a job whose document write was rolled back should not resurrect it. Here silence would
    leave a freshly inserted generation permanently inactive *and* uncollected: invisible to every
    reader, real to RAM and disk, with nothing to indicate it. `tenant_id` is in the WHERE clause,
    not checked afterwards, for the same reason every other read here carries it.
    """
    statement = (
        update(DocumentRecord)
        .where(col(DocumentRecord.doc_id) == doc_id)
        .where(col(DocumentRecord.tenant_id) == tenant_id)
        .values(
            ingestion_version=ingestion_version,
            chunk_count=chunk_count,
            status=STATUS_INGESTED,
            error_message=None,
        )
    )
    result = await session.exec(statement)
    if result.rowcount == 0:
        msg = f"no document row for {doc_id} in tenant {tenant_id}: refusing to leave a generation unpublished"
        raise DocumentNotFoundError(msg)
    await session.commit()


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
