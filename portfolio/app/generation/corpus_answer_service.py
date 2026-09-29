"""Corpus-level answers for `aggregate` questions (Epic 2 Phase 2.4), behind `AGGREGATE_ANSWERING`.

"What themes run through my uploads?" can't be answered from the five chunks nearest one
embedding: they cluster in whichever document happens to sit closest, and the answer then
describes that document as if it were the collection. So this widens retrieval, ranks
*documents* rather than chunks, and answers from a few chunks of each of the best documents.

Shaped after `microsoft/graphrag`'s global search, with its parts swapped for ones this system
already has (`docs/EPIC_2_PLAN.md` Phase 2.4):
- candidates are the top chunks of one tenant-scoped search, not a map over the whole corpus
  (O(documents retrieved), never O(corpus));
- documents are scored by Voyage rerank scores, not a model-assigned importance score;
- there is one generation over the selected source chunks, with the Citations API, not a
  per-document summary step. A per-document map would ground the final answer in model-written
  summaries, so its citations would point at text no document contains.
- If nothing scores above the floor, the answer is a canned "nothing relevant" instead of a
  synthesis from weak material, which is the part of graphrag's design kept verbatim.
"""

from __future__ import annotations

from collections import OrderedDict
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.generation.answer_service import (
    _MAX_ANSWER_TOKENS,
    Answer,
    _build_document_blocks,
    _extract_citations,
    _extract_text,
)
from app.generation.prompts import AGGREGATE_NO_DATA_ANSWER, AGGREGATE_SYSTEM_PROMPT
from app.retrieval.reranker import rerank
from app.retrieval.retriever import Retriever

if TYPE_CHECKING:
    from langchain_core.documents import Document

log = structlog.get_logger(__name__)

CANDIDATE_CHUNKS = 60
"""Chunks fetched by the one vector search. Wide on purpose: the default 20 mostly come from the
single nearest document, which is the failure this path exists to fix."""

RERANKED_CHUNKS = 30
MAX_DOCUMENTS = 5
CHUNKS_PER_DOCUMENT = 3
"""Five documents x three chunks = at most 15 sources, about three times a factual answer's
input. A collection-wide question costs more to answer; this caps how much more."""

SCORE_FLOOR = 0.25
"""Minimum Voyage rerank score for a document to count as relevant. **Not calibrated yet**: it's
a starting point on rerank-2.5's 0-1 scale, and graphrag's 0-100 importance number doesn't carry
over. Calibrate it against the aggregate-class golden questions (`scripts/run_eval.py`) before
switching `AGGREGATE_ANSWERING` on."""


def _select(reranked: list[Document]) -> tuple[list[Document], int]:
    """The best chunks of the best documents, and how many relevant documents didn't fit.

    Documents are ranked by their best chunk's rerank score, in order of first appearance, since
    the reranker already sorted by score. A chunk with no score (the reranker was down and
    `rerank` fell back to vector order) passes the floor. Refusing then would turn a guardrail's
    outage into an answer outage (root rule 9), and the fallback is already logged.
    """
    by_document: OrderedDict[str, list[Document]] = OrderedDict()
    for chunk in reranked:
        score = chunk.metadata.get("relevance_score")
        if score is not None and score < SCORE_FLOOR:
            continue
        by_document.setdefault(chunk.metadata.get("doc_id", ""), []).append(chunk)
    kept = list(by_document.values())[:MAX_DOCUMENTS]
    dropped = max(0, len(by_document) - MAX_DOCUMENTS)
    return [chunk for chunks in kept for chunk in chunks[:CHUNKS_PER_DOCUMENT]], dropped


class AggregateAnswerService:
    def __init__(self, retriever: Retriever | None = None) -> None:
        self._retriever = retriever or Retriever()
        settings = get_settings()
        self._llm = ChatAnthropic(
            model=settings.answer_model,
            api_key=settings.anthropic_api_key,
            max_tokens=_MAX_ANSWER_TOKENS,
            thinking={"type": "disabled"},
        )

    async def answer(self, question: str, tenant_id: str) -> Answer:
        start = perf_counter()
        candidates = await self._retriever.retrieve(question, tenant_id=tenant_id, top_k=CANDIDATE_CHUNKS)
        reranked = await rerank(question, candidates, top_n=RERANKED_CHUNKS)
        sources, dropped = _select(reranked)

        if dropped:
            # Logged, never a silent cut: graphrag's version just `break`s out of the loop, so an
            # answer that ignored half the relevant documents reads exactly like a complete one.
            log.info("aggregate.documents_dropped", dropped=dropped, kept=MAX_DOCUMENTS, tenant_id=tenant_id)
        if not sources:
            log.info("aggregate.nothing_above_floor", floor=SCORE_FLOOR, candidates=len(candidates))
            return Answer(text=AGGREGATE_NO_DATA_ANSWER, citations=[], retrieved_chunks=[])

        response = await self._llm.ainvoke(
            [
                SystemMessage(content=AGGREGATE_SYSTEM_PROMPT),
                HumanMessage(content=[*_build_document_blocks(sources), {"type": "text", "text": question}]),
            ]
        )
        stop_reason = response.response_metadata.get("stop_reason")
        log.info(
            "aggregate.answered",
            documents=len({s.metadata.get("doc_id") for s in sources}),
            sources=len(sources),
            stop_reason=stop_reason,
            latency_ms=round((perf_counter() - start) * 1000, 1),
            tenant_id=tenant_id,
        )
        return Answer(
            text=_extract_text(response.content),
            citations=_extract_citations(response.content, sources),
            retrieved_chunks=sources,
            truncated=stop_reason == "max_tokens",
        )
