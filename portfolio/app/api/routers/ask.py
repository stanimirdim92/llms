from functools import lru_cache

from fastapi import APIRouter, Depends

# Must stay a runtime import. `rate_limited` is called below, and `CurrentTenant` -- though
# it appears only in an annotation -- is read at runtime by FastAPI (get_type_hints, when the
# route is registered) to find the Depends() marker inside it. If `rate_limited` ever leaves
# this import, ruff will suggest moving the rest into a TYPE_CHECKING block; don't.
from app.api.deps import CurrentTenant, rate_limited, require_scopes
from app.api.schemas import AskRequest, AskResponse, CitationResponse, RetrievedChunkResponse
from app.auth.scopes import ASK
from app.db import get_session, init_db
from app.exceptions import APIError
from app.generation.answer_service import AnswerService
from app.generation.intent_router import classify_intent
from app.registry.db import list_document_records
from app.retrieval.document_scope import DocumentScope, mentions_a_document, resolve_scope
from app.vectorstore.qdrant_store import RetrievalUnavailableError

router = APIRouter()

_OUT_OF_SCOPE_ANSWER = (
    "I can only answer questions grounded in the documents you've uploaded. This one isn't -- "
    "ask about something in your documents, or check GET /v1/documents for what's searchable."
)
_AGGREGATE_NOT_SUPPORTED_ANSWER = (
    "Questions spanning your whole document collection aren't supported yet. Ask about one "
    "document or a specific fact instead."
)
"""The `aggregate` branch from docs/EPIC_2_PLAN.md Phase 2.0's table. Its real answer path
(map-reduce over top-N documents) is Phase 2.4 and needs 2.1's golden set first -- refusing
honestly here beats routing it through the factual pipeline, which would silently do the
single-passage-per-question thing Phase 2.0 exists to stop doing for exactly this class."""


@lru_cache
def _service() -> AnswerService:
    return AnswerService()


def _plain_answer(text: str) -> AskResponse:
    """An `AskResponse` for the three intents Phase 2.0 doesn't retrieve for -- no citations, no
    retrieved chunks, because nothing was retrieved. Same response shape as a normal answer so
    callers don't need a second code path for "the system chose not to search".
    """
    return AskResponse(answer=text, citations=[], retrieved_chunks=[])


async def _document_summary(tenant_id: str) -> str:
    """Answers a `metadata` question straight from the registry -- Phase 2.0's whole point.

    Mirrors `GET /v1/documents`'s own read and default `limit` (100, not `_document_scope`'s
    200) so a metadata question and the listing endpoint report the same count for the same
    tenant. Retrieval cannot answer this class of question at all: the embedding of "list my
    documents" lands nearest whatever chunk happens to be semantically adjacent, which is how a
    metadata question reached production grounded in a stranger's figure-caption text.
    """
    await init_db()
    async with get_session() as session:
        records = await list_document_records(session, tenant_id=tenant_id, limit=100)

    if not records:
        return "You haven't uploaded any documents yet."
    lines = [f"You have {len(records)} document{'s' if len(records) != 1 else ''}:"]
    lines.extend(f"- {record.filename} ({record.status}, {record.chunk_count} chunks)" for record in records)
    return "\n".join(lines)


async def _document_scope(question: str, tenant_id: str) -> DocumentScope:
    """Resolve a filename or `doc_id` named in the question against what this caller may read.

    The registry read is gated on `mentions_a_document` so the common case -- a question that
    names nothing -- costs no query. `list_document_records` puts `tenant_id` in the WHERE
    clause, so a resolved `doc_id` is always one the caller owns. That is the ownership check
    required before any id reaches a Qdrant filter: matching on a client-supplied id alone
    would resolve to another tenant's document while looking entirely correct.

    This used to call a separate `list_scope_candidates`, because the curated corpus made "what
    may I scope to" wider than "what do I own". The corpus is gone, so they are the same query
    and there is one function again. Do not reintroduce a second one: the last time two existed
    they disagreed, and the disagreement was a 404 on every document the docs told callers to
    name.
    """
    if not mentions_a_document(question):
        return DocumentScope()

    await init_db()
    async with get_session() as session:
        # 200, not the 100 `GET /v1/documents` renders: this resolves a *name* a caller typed,
        # so the net has to be wider than what a listing page shows.
        records = await list_document_records(session, tenant_id=tenant_id, limit=200)
    return resolve_scope(question, records)


@router.post(
    "/ask",
    tags=["ask"],
    summary="Ask a question over the documents your tenant has uploaded",
    description="Retrieves relevant chunks, reranks them, and generates a cited answer grounded only "
    "in what was retrieved. Searches **only** documents uploaded by the tenant the `x-api-key` "
    "header authenticates as -- never another tenant's, and there is no shared corpus. A tenant "
    "that has uploaded nothing has nothing to search. Requires a valid API key.\n\n"
    "Naming one of your own documents in the question restricts the search to that document, "
    "and `scoped_to` in the response says which. Either identifier works, both exactly as "
    "`GET /v1/documents` reports them: the **filename** written in full with its extension "
    "('give me the contents of report.pdf'), or the **doc_id**, bare or behind a `doc_id=` "
    "marker.\n\nNaming a document you do not have returns **404** rather than silently "
    "searching everything; naming one of yours that is still ingesting (or that failed) returns "
    "**409**, because answering from a document with no chunks yet would be a confident lie about "
    "a document nothing searched.",
    response_description="A cited answer, its citations, and every chunk that was retrieved/reranked",
    dependencies=[Depends(require_scopes(ASK)), Depends(rate_limited("ask", "rate_limit_ask"))],
)
async def ask(request: AskRequest, tenant_id: CurrentTenant) -> AskResponse:
    # Phase 2.0 (docs/EPIC_2_PLAN.md): three of four intents never reach retrieval at all, by
    # design -- retrieval matches chunks semantically, so a question that isn't about document
    # *content* gets an answer grounded in whatever text happens to be nearest in embedding
    # space regardless of how wrong that is for the question actually asked. `factual` alone
    # falls through to the pipeline below, unchanged from before this branch existed.
    match await classify_intent(request.question):
        case "metadata":
            return _plain_answer(await _document_summary(tenant_id))
        case "out_of_scope":
            return _plain_answer(_OUT_OF_SCOPE_ANSWER)
        case "aggregate":
            return _plain_answer(_AGGREGATE_NOT_SUPPORTED_ANSWER)

    scope = await _document_scope(request.question, tenant_id)
    if scope.names_nothing_owned:
        # 404, not 403, and deliberately without saying whether the file exists for anyone
        # else -- that would confirm a leaked id belongs to somebody. Naming the caller's
        # own documents back is safe and is the thing that makes the error actionable.
        named = ", ".join(scope.unknown)
        raise APIError(f"No document matching {named} in your documents. Check GET /v1/documents.", code=404)
    if scope.names_only_unready:
        # 409, not 404: the document exists, it just has no chunks yet. Answering anyway
        # would scope to nothing and return a confident "the document does not mention that",
        # which is a lie about a document that was never searched.
        named = ", ".join(scope.not_ready)
        raise APIError(
            f"{named} is not searchable yet -- ingestion has not finished or it failed. "
            "Check GET /v1/documents/{doc_id} for its status.",
            code=409,
        )

    try:
        result = await _service().answer(request.question, tenant_id=tenant_id, doc_ids=scope.doc_ids or None)
    except RetrievalUnavailableError as exc:
        # No honest fallback exists for a failed search (rule 9) -- a clear, distinguishable
        # 503 beats the generic 500 `unhandled_error_handler` would otherwise return, and beats
        # retrying into what may be a compounding provider outage.
        raise APIError(
            "Retrieval is temporarily unavailable (the embedding or vector-search provider "
            "didn't respond). Try again shortly.",
            code=503,
        ) from exc
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
        truncated=result.truncated,
    )
