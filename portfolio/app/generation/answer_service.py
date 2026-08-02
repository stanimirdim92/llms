"""Retrieve -> rerank -> generate with forced citations. The Epic 1 answer path, deliberately a
workflow (fixed pipeline), not an agent -- see docs/ARCHITECTURE.md section 2.

Built on LangChain (ChatAnthropic) rather than the raw Anthropic SDK so it shares the same
framework Epic 3's LangGraph agent runs on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.generation.prompts import SYSTEM_PROMPT
from app.retrieval.reranker import rerank
from app.retrieval.retriever import Retriever

if TYPE_CHECKING:
    from langchain_core.documents import Document

log = structlog.get_logger(__name__)

# AIMessage.content: a plain string, or a list of content blocks (each a dict mirroring
# the raw Anthropic API shape when citations/structured output are involved).
AnthropicContent = str | list[str | dict]


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
    """The label the model sees for each document block -- and the only identifier it can
    match a question against.

    `filename` leads when present. With `doc_id` alone the model cannot answer "tell me
    about 24383456-639402.pdf" even holding the right chunk, because a content-hash id looks
    nothing like the name the user typed; it answers, correctly and unhelpfully, that it has
    no such document. `doc_id` is kept alongside so citations stay traceable and so chunks
    ingested before filenames were stored still render.
    """
    meta = document.metadata
    location = f"page {meta.get('page_no')}" if meta.get("page_no") is not None else "unknown page"
    doc_id = meta.get("doc_id", "unknown")
    name = meta.get("filename")
    label = f"{name} [{doc_id}]" if name else doc_id
    return f"{label} ({meta.get('chunk_type', 'text')}, {location})"


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


def _extract_citations(content_blocks: AnthropicContent, documents: list[Document]) -> list[Citation]:
    """`content_blocks` is the AIMessage's `.content`, a list of blocks when citations
    are enabled (each a dict mirroring the raw Anthropic API shape).
    """
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


def _extract_text(content_blocks: AnthropicContent) -> str:
    if isinstance(content_blocks, str):
        return content_blocks
    return "".join(
        block.get("text", "") for block in content_blocks if isinstance(block, dict) and block.get("type") == "text"
    )


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

    async def answer(self, question: str, tenant_id: str | None = None, doc_ids: list[str] | None = None) -> Answer:
        """`doc_ids` narrows retrieval to those documents. Resolved by the caller from its own
        registry rows (see `retrieval/document_scope.py`); this method does not parse the
        question, so a scope is always an explicit decision made somewhere legible.
        """
        start = perf_counter()
        candidates = await self._retriever.retrieve(question, tenant_id=tenant_id, doc_ids=doc_ids)
        top_documents = await rerank(question, candidates)

        response = await self._llm.ainvoke(
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
            tenant_id=tenant_id,
            retrieved=len(candidates),
            reranked=len(top_documents),
            citation_count=len(citations),
            latency_ms=round(latency_ms, 1),
        )

        return Answer(text=text, citations=citations, retrieved_chunks=top_documents)
