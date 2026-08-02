"""Document-registry writes. The engine/session they run on lives in `app/db.py`, which
`app/auth/` shares -- see that module's docstring for why it moved out of here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select

from app.ingestion.models import GLOBAL_TENANT
from app.registry.models import STATUS_FAILED, STATUS_PROCESSING, DocumentRecord

_CORPUS_SCOPE_LIMIT = 500
"""How many shared-corpus documents can be named in a question. Its own budget, separate
from the caller's, so a tenant's uploads can never crowd the corpus out of the candidate
set -- see `list_scope_candidates`."""

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


async def list_scope_candidates(session: AsyncSession, *, tenant_id: str, limit: int = 200) -> list[DocumentRecord]:
    """Every document a question may be *scoped to*: this tenant's, plus the shared corpus.

    Deliberately a different function from `list_document_records`, which answers "my
    documents" and must keep excluding `GLOBAL_TENANT` -- listing documents nobody uploaded
    would misrepresent what the tenant owns. Scoping is the opposite question: the corpus is
    readable by everyone, so naming one of its papers has to resolve.

    That difference was a real defect. `/ask`'s OpenAPI description and the README both said
    the `doc_id=` marker "is the only form that works for the shared corpus" -- and it never
    did, because the candidate set came from the my-documents query. Following the README's
    own copy-pasteable example returned 404 for one of the six papers the project ships.

    Still an authorization boundary, not a bypass: `IN (tenant, 'global')` is two named
    values, so no crafted id widens it. This is the same shape `QdrantStore._build_filter`
    uses for the retrieval filter, which is what makes the two agree about what is readable.
    """

    # Two queries, each with its own limit, rather than one `IN` list with a shared one. A
    # single `ORDER BY uploaded_at DESC LIMIT 200` looks equivalent and is not: the curated
    # corpus is the *oldest* content in the table, so a tenant with 200 newer uploads would
    # push every corpus row past the cut and get H1's 404 back on every curated paper --
    # invisibly, and only for the busiest tenants. Worse, a truncated own-document could
    # silently scope to a shorter filename that survived. The corpus is small and fixed, so
    # it gets its own budget instead of competing for one.
    async def _newest(owner: str, cap: int) -> list[DocumentRecord]:
        statement = (
            select(DocumentRecord)
            .where(DocumentRecord.tenant_id == owner)
            .order_by(col(DocumentRecord.uploaded_at).desc())
            .limit(cap)
        )
        return list((await session.exec(statement)).all())

    own = await _newest(tenant_id, limit)
    corpus = [] if tenant_id == GLOBAL_TENANT else await _newest(GLOBAL_TENANT, _CORPUS_SCOPE_LIMIT)
    return own + corpus


async def list_document_records(session: AsyncSession, *, tenant_id: str, limit: int = 100) -> list[DocumentRecord]:
    """Every document this tenant owns, newest first.

    Exists because "what documents do I have?" is a *metadata* question, and asking it through
    /ask cannot work: retrieval matches chunks semantically, so a meta-question about the corpus
    retrieves whatever happens to be nearest in embedding space and the answer is grounded in
    that. A real user asked exactly this and got a confident summary of one document's chunks.

    Deliberately excludes the shared corpus (`GLOBAL_TENANT`): this answers "my documents", and
    mixing in corpus documents nobody uploaded would misrepresent what the tenant owns.
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
