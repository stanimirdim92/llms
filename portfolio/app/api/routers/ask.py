from functools import lru_cache

from fastapi import APIRouter, Depends

# Must stay a runtime import. `rate_limited` is called below, and `CurrentTenant` -- though
# it appears only in an annotation -- is read at runtime by FastAPI (get_type_hints, when the
# route is registered) to find the Depends() marker inside it. If `rate_limited` ever leaves
# this import, ruff will suggest moving the rest into a TYPE_CHECKING block; don't.
from app.api.deps import CurrentTenant, rate_limited
from app.api.schemas import AskRequest, AskResponse, CitationResponse, RetrievedChunkResponse
from app.db import get_session, init_db
from app.exceptions import APIError
from app.generation.answer_service import AnswerService
from app.registry.db import list_document_records
from app.retrieval.document_scope import DocumentScope, mentions_a_document, resolve_scope

router = APIRouter()


@lru_cache
def _service() -> AnswerService:
    return AnswerService()


async def _document_scope(question: str, tenant_id: str) -> DocumentScope:
    """Resolve a filename or `doc_id` named in the question against *this tenant's* documents.

    The registry read is gated on `mentions_a_document` so the common case -- a question that
    names nothing -- costs no query. The records passed to `resolve_scope` come from
    `list_document_records`, which filters on `tenant_id` in the WHERE clause, so a resolved
    `doc_id` is always one the caller owns. That is the ownership check required before any
    id reaches a Qdrant filter: `doc_id` is a content hash, so two tenants uploading the same
    file share one, and matching on the id alone would resolve to the other tenant's document
    while looking entirely correct.
    """
    if not mentions_a_document(question):
        return DocumentScope()

    await init_db()
    async with get_session() as session:
        records = await list_document_records(session, tenant_id=tenant_id)
    return resolve_scope(question, records)


@router.post(
    "/ask",
    tags=["ask"],
    summary="Ask a question over the curated corpus plus your own tenant's uploads",
    description="Retrieves relevant chunks, reranks them, and generates a cited answer grounded only "
    "in what was retrieved. Searches the shared corpus plus documents uploaded by the tenant the "
    "`x-api-key` header authenticates as -- never another tenant's. Requires a valid API key.\n\n"
    "Naming one of your own documents in the question restricts the search to that document, "
    "and `scoped_to` in the response says which. Either identifier works, both exactly as "
    "`GET /v1/documents` reports them: the **filename** written in full with its extension "
    "('give me the contents of report.pdf'), or the **doc_id**, bare or behind a `doc_id=` "
    "marker. The marker is the only form that works for the shared corpus, whose ids are bare "
    "arXiv numbers. Naming a document you do not have returns 404 rather than silently "
    "searching everything.",
    response_description="A cited answer, its citations, and every chunk that was retrieved/reranked",
    dependencies=[Depends(rate_limited("ask", "rate_limit_ask"))],
)
async def ask(request: AskRequest, tenant_id: CurrentTenant) -> AskResponse:
    scope = await _document_scope(request.question, tenant_id)
    if scope.names_nothing_owned:
        # 404, not 403, and deliberately without saying whether the file exists for anyone
        # else -- that would be an existence oracle over content hashes. Naming the caller's
        # own documents back is safe and is the thing that makes the error actionable.
        named = ", ".join(scope.unknown)
        raise APIError(f"No document matching {named} in your documents. Check GET /v1/documents.", code=404)

    result = await _service().answer(request.question, tenant_id=tenant_id, doc_ids=scope.doc_ids or None)
    return AskResponse(
        answer=result.text,
        scoped_to=scope.filenames,
        citations=[
            CitationResponse(quoted_text=c.quoted_text, chunk_id=c.chunk_id, doc_id=c.doc_id, page_no=c.page_no)
            for c in result.citations
        ],
        retrieved_chunks=[
            RetrievedChunkResponse(
                chunk_id=doc.metadata.get("chunk_id", ""),
                doc_id=doc.metadata.get("doc_id", ""),
                chunk_type=doc.metadata.get("chunk_type", "text"),
                page_no=doc.metadata.get("page_no"),
                section_path=doc.metadata.get("section_path", ""),
                text=doc.page_content,
            )
            for doc in result.retrieved_chunks
        ],
    )
