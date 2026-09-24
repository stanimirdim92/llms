"""Run one golden question through the real `/ask` pipeline and keep what the metrics read.

It calls `answer_question`, the same function the route calls, never a reimplementation, so a
green eval is a statement about what ships.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from fastapi import HTTPException

from app.api.routers.ask import answer_question


@dataclass(frozen=True)
class TargetOutput:
    predicted_intent: str | None
    retrieved_chunk_ids: tuple[str, ...]
    """In rank order: the reranked chunks the answer was built from."""
    cited_chunk_ids: tuple[str, ...]
    answer: str
    latency_ms: float
    retrieved_texts: tuple[str, ...] = ()
    """The chunk texts, same order as the ids. What the groundedness judge checks the answer against."""
    error_code: int | None = None
    """Set when `/ask` answered with an error (a 503 from routing or retrieval, a scope 404/409).
    Kept as data rather than raised: one failing question must score as a miss, not abort a run
    and hide the other 66 results."""

    def as_dict(self) -> dict:
        return {
            "predicted_intent": self.predicted_intent,
            "retrieved_chunk_ids": list(self.retrieved_chunk_ids),
            "cited_chunk_ids": list(self.cited_chunk_ids),
            "answer": self.answer,
            "latency_ms": self.latency_ms,
            "retrieved_texts": list(self.retrieved_texts),
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TargetOutput:
        return cls(
            predicted_intent=data.get("predicted_intent"),
            retrieved_chunk_ids=tuple(data.get("retrieved_chunk_ids") or ()),
            cited_chunk_ids=tuple(data.get("cited_chunk_ids") or ()),
            answer=data.get("answer") or "",
            latency_ms=float(data.get("latency_ms") or 0.0),
            retrieved_texts=tuple(data.get("retrieved_texts") or ()),
            error_code=data.get("error_code"),
        )


async def run_question(question: str, tenant_id: str) -> TargetOutput:
    start = perf_counter()
    try:
        intent, response = await answer_question(question, tenant_id)
    except HTTPException as exc:
        # The intent is lost when `/ask` raises after routing (a scope 404/409). Routing then
        # scores as a miss even if it was right. Acceptable: the seeded corpus has no scope
        # errors, so a row landing here is already a failure worth seeing.
        return TargetOutput(
            predicted_intent=None,
            retrieved_chunk_ids=(),
            cited_chunk_ids=(),
            answer=str(exc.detail),
            latency_ms=(perf_counter() - start) * 1000,
            error_code=exc.status_code,
        )
    return TargetOutput(
        predicted_intent=intent,
        retrieved_chunk_ids=tuple(chunk.chunk_id for chunk in response.retrieved_chunks),
        cited_chunk_ids=tuple(citation.chunk_id for citation in response.citations),
        answer=response.answer,
        latency_ms=(perf_counter() - start) * 1000,
        retrieved_texts=tuple(chunk.text for chunk in response.retrieved_chunks),
    )
