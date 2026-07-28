from functools import lru_cache

from fastapi import APIRouter, Depends

# Must stay a runtime import. `rate_limited` is called below, and `CurrentTenant` -- though
# it appears only in an annotation -- is read at runtime by FastAPI (get_type_hints, when the
# route is registered) to find the Depends() marker inside it. If `rate_limited` ever leaves
# this import, ruff will suggest moving the rest into a TYPE_CHECKING block; don't.
from app.api.deps import CurrentTenant, rate_limited
from app.api.schemas import AskRequest, AskResponse, CitationResponse, RetrievedChunkResponse
from app.generation.answer_service import AnswerService

router = APIRouter()


@lru_cache
def _service() -> AnswerService:
    return AnswerService()


@router.post(
    "/ask",
    response_model=AskResponse,
    tags=["ask"],
    summary="Ask a question over the curated corpus plus your own tenant's uploads",
    description="Retrieves relevant chunks, reranks them, and generates a cited answer grounded only "
    "in what was retrieved. Searches the shared corpus plus documents uploaded by the tenant the "
    "`x-api-key` header authenticates as -- never another tenant's. Requires a valid API key.",
    response_description="A cited answer, its citations, and every chunk that was retrieved/reranked",
    dependencies=[Depends(rate_limited("ask", "rate_limit_ask"))],
)
async def ask(request: AskRequest, tenant_id: CurrentTenant) -> AskResponse:
    result = await _service().answer(request.question, tenant_id=tenant_id)
    return AskResponse(
        answer=result.text,
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
