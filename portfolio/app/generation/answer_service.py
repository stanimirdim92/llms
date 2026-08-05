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
    truncated: bool = False
    """True when the model hit `max_tokens` rather than finishing.

    A truncated answer is not a shorter answer -- it stops mid-sentence, and because citation
    blocks are emitted as the text is generated, the citation list stops with it. Both the text
    and the sources are therefore incomplete while looking exactly like a complete answer, so
    the one thing this must not be is silent. `False` by default so an `Answer` built anywhere
    else (tests, a future eval harness) does not have to know about it.
    """


_MAX_ANSWER_TOKENS = 1024
"""Named rather than inlined so the truncation warning can report the ceiling it hit.

Not a `Settings` field: raising it is a cost decision that should be made with the truncation
rate in front of you, and that rate did not exist until it was logged.
"""

_TRUNCATED_STOP_REASON = "max_tokens"
"""Anthropic's `stop_reason` when generation was cut off by the token ceiling.

Read from `response_metadata`, and the route it takes there is worth stating because it is not
the obvious one: `langchain_anthropic._format_output` puts `stop_reason` in `llm_output`, and
`langchain_core`'s `generate` is what merges `llm_output` into the message's `response_metadata`.
So the read location is right, via langchain-core rather than langchain-anthropic -- resolved
against both installed packages, not remembered. Any value other than `max_tokens` (`end_turn`,
`stop_sequence`) means the model chose to stop.
"""


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
    citations: list[Citation] = []
    if isinstance(content_blocks, str):
        return citations

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        for citation in block.get("citations") or []:
            doc_index = citation.get("document_index")
            # `not 0 <= doc_index`, not just the upper bound. A negative index is the one
            # out-of-range value Python *resolves*: `documents[-1]` is a real document, so the
            # citation rendered normally while attributing the quote to whichever chunk happened
            # to be reranked last -- a wrong source carrying a right quote, which reads as
            # correct at every point of use.
            if doc_index is None or not 0 <= doc_index < len(documents):
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
            max_tokens=_MAX_ANSWER_TOKENS,
            thinking={"type": "disabled"},
        )

    async def answer(self, question: str, tenant_id: str, doc_ids: list[str] | None = None) -> Answer:
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

        stop_reason = response.response_metadata.get("stop_reason")
        truncated = stop_reason == _TRUNCATED_STOP_REASON
        # `.get`, not indexing: `usage_metadata` is None on some providers and on a cached
        # response, and an answer must not fail because its cost could not be reported.
        usage = response.usage_metadata or {}

        log.info(
            "answer_service.answered",
            question=question,
            tenant_id=tenant_id,
            retrieved=len(candidates),
            reranked=len(top_documents),
            citation_count=len(citations),
            latency_ms=round(latency_ms, 1),
            # Logged on every answer, not only when something is wrong. Token counts are the
            # only record of what this path costs -- there is no billing hook -- and a
            # `stop_reason` that is *usually* `end_turn` is only informative if the normal
            # value is also on record.
            stop_reason=stop_reason,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
        if truncated:
            # A separate warning, because the info line above is what a dashboard aggregates
            # and this is what a human needs to see. `max_tokens` here is not a tuning nit: the
            # answer is cut off mid-sentence and its citation list is short, and the caller
            # cannot tell either from the text.
            log.warning(
                "answer_service.truncated",
                question=question,
                tenant_id=tenant_id,
                output_tokens=usage.get("output_tokens"),
                max_tokens=_MAX_ANSWER_TOKENS,
            )

        return Answer(text=text, citations=citations, retrieved_chunks=top_documents, truncated=truncated)
