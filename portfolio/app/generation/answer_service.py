"""Retrieve -> rerank -> generate with forced citations. The Epic 1 answer path, deliberately a
workflow (fixed pipeline), not an agent -- see ARCHITECTURE.md section 2."""

from dataclasses import dataclass, field
from time import perf_counter

import structlog
from anthropic import Anthropic

from app.config import get_settings
from app.generation.prompts import SYSTEM_PROMPT
from app.retrieval.reranker import rerank
from app.retrieval.retriever import Retriever
from app.vectorstore.chroma_store import RetrievedChunk

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Citation:
    quoted_text: str
    chunk_id: str
    doc_id: str
    page_no: int | None


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[Citation]
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)


def _chunk_title(chunk: RetrievedChunk) -> str:
    location = f"page {chunk.page_no}" if chunk.page_no is not None else "unknown page"
    return f"{chunk.doc_id} ({chunk.chunk_type}, {location})"


def _build_document_blocks(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": chunk.text},
            "title": _chunk_title(chunk),
            "citations": {"enabled": True},
        }
        for chunk in chunks
    ]


def _extract_citations(content_blocks: list, chunks: list[RetrievedChunk]) -> list[Citation]:
    citations: list[Citation] = []
    for block in content_blocks:
        for citation in getattr(block, "citations", None) or []:
            doc_index = getattr(citation, "document_index", None)
            if doc_index is None or doc_index >= len(chunks):
                continue
            source_chunk = chunks[doc_index]
            citations.append(
                Citation(
                    quoted_text=getattr(citation, "cited_text", ""),
                    chunk_id=source_chunk.chunk_id,
                    doc_id=source_chunk.doc_id,
                    page_no=source_chunk.page_no,
                )
            )
    return citations


class AnswerService:
    def __init__(self, retriever: Retriever | None = None) -> None:
        self._retriever = retriever or Retriever()
        settings = get_settings()
        self._client = Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.answer_model

    def answer(self, question: str) -> Answer:
        start = perf_counter()
        candidates = self._retriever.retrieve(question)
        top_chunks = rerank(question, candidates)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [*_build_document_blocks(top_chunks), {"type": "text", "text": question}],
                }
            ],
        )

        text = "".join(block.text for block in response.content if block.type == "text")
        citations = _extract_citations(response.content, top_chunks)
        latency_ms = (perf_counter() - start) * 1000

        log.info(
            "answer_service.answered",
            question=question,
            retrieved=len(candidates),
            reranked=len(top_chunks),
            citation_count=len(citations),
            latency_ms=round(latency_ms, 1),
        )

        return Answer(text=text, citations=citations, retrieved_chunks=top_chunks)
