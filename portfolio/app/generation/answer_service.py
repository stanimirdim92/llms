"""Retrieve -> rerank -> generate with forced citations. The Epic 1 answer path, deliberately a
workflow (fixed pipeline), not an agent -- see ARCHITECTURE.md section 2.

Built on LangChain (ChatAnthropic) rather than the raw Anthropic SDK so it shares the same
framework Epic 3's LangGraph agent runs on.
"""

from dataclasses import dataclass, field
from time import perf_counter

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.generation.prompts import SYSTEM_PROMPT
from app.retrieval.reranker import rerank
from app.retrieval.retriever import Retriever

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
    retrieved_chunks: list[Document] = field(default_factory=list)


def _chunk_title(document: Document) -> str:
    meta = document.metadata
    location = f"page {meta.get('page_no')}" if meta.get("page_no") is not None else "unknown page"
    return f"{meta.get('doc_id', 'unknown')} ({meta.get('chunk_type', 'text')}, {location})"


def _build_document_blocks(documents: list[Document]) -> list[dict]:
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": document.page_content},
            "title": _chunk_title(document),
            "citations": {"enabled": True},
        }
        for document in documents
    ]


def _extract_citations(content_blocks, documents: list[Document]) -> list[Citation]:
    """`content_blocks` is the AIMessage's `.content`, a list of blocks when citations
    are enabled (each a dict mirroring the raw Anthropic API shape)."""
    citations: list[Citation] = []
    if isinstance(content_blocks, str):
        return citations

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        for citation in block.get("citations") or []:
            doc_index = citation.get("document_index")
            if doc_index is None or doc_index >= len(documents):
                continue
            source = documents[doc_index]
            citations.append(
                Citation(
                    quoted_text=citation.get("cited_text", ""),
                    chunk_id=source.metadata.get("chunk_id", source.metadata.get("doc_id", "")),
                    doc_id=source.metadata.get("doc_id", ""),
                    page_no=source.metadata.get("page_no"),
                )
            )
    return citations


def _extract_text(content_blocks) -> str:
    if isinstance(content_blocks, str):
        return content_blocks
    return "".join(block.get("text", "") for block in content_blocks if isinstance(block, dict) and block.get("type") == "text")


class AnswerService:
    def __init__(self, retriever: Retriever | None = None) -> None:
        self._retriever = retriever or Retriever()
        settings = get_settings()
        self._llm = ChatAnthropic(
            model=settings.answer_model,
            api_key=settings.anthropic_api_key,
            max_tokens=1024,
            thinking={"type": "disabled"},
        )

    def answer(self, question: str, session_id: str | None = None) -> Answer:
        start = perf_counter()
        candidates = self._retriever.retrieve(question, session_id=session_id)
        top_documents = rerank(question, candidates)

        response = self._llm.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=[*_build_document_blocks(top_documents), {"type": "text", "text": question}]),
            ]
        )

        text = _extract_text(response.content)
        citations = _extract_citations(response.content, top_documents)
        latency_ms = (perf_counter() - start) * 1000

        log.info(
            "answer_service.answered",
            question=question,
            session_id=session_id,
            retrieved=len(candidates),
            reranked=len(top_documents),
            citation_count=len(citations),
            latency_ms=round(latency_ms, 1),
        )

        return Answer(text=text, citations=citations, retrieved_chunks=top_documents)
