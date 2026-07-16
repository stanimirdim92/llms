from fastapi import APIRouter

from app.api.schemas import AskRequest, AskResponse, CitationResponse, RetrievedChunkResponse
from app.generation.answer_service import AnswerService

router = APIRouter()
_service = AnswerService()


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    result = _service.answer(request.question)
    return AskResponse(
        answer=result.text,
        citations=[
            CitationResponse(
                quoted_text=c.quoted_text, chunk_id=c.chunk_id, doc_id=c.doc_id, page_no=c.page_no
            )
            for c in result.citations
        ],
        retrieved_chunks=[
            RetrievedChunkResponse(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                chunk_type=c.chunk_type,
                page_no=c.page_no,
                section_path=c.section_path,
                text=c.text,
            )
            for c in result.retrieved_chunks
        ],
    )
