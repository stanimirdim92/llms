from functools import lru_cache

from fastapi import APIRouter

# Not a TYPE_CHECKING-only import despite appearing only in an annotation: FastAPI reads
# these hints at runtime (via get_type_hints when the route is registered) to discover the
# Depends() marker inside CurrentTenant. Deferring it raises NameError at import.
from app.api.deps import CurrentTenant  # noqa: TC001
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
