from functools import lru_cache

from fastapi import APIRouter

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
    summary="Ask a question over the curated corpus and/or a session's uploads",
    description="Retrieves relevant chunks, reranks them, and generates a cited answer grounded only "
    "in what was retrieved. Omitting `session_id` searches only the curated corpus.",
    response_description="A cited answer, its citations, and every chunk that was retrieved/reranked",
)
async def ask(request: AskRequest) -> AskResponse:
    result = await _service().answer(request.question, session_id=request.session_id)
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
