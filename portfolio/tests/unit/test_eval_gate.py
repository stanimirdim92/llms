"""The gate's verdict on a reranker regression, by scoring.

This stands in for the acceptance test T007 first asked for -- "remove the reranker and the gate
fails on nDCG". That cannot run against strict replay: a pipeline without the reranker makes
different requests (no Voyage rerank call, and an Anthropic body whose documents are in vector
order), and under `record_mode="none"` those are cassette *misses*, which abort the run before any
metric exists (`tests/unit/test_eval_replay.py` pins that). What is left to prove is the half that
is pure: given the ranking a reranker-less pipeline would produce, the gate names a rank-sensitive
metric and not only a lower average. Whether the recorded pipeline still matches the code is what
the miss is for.
"""

from __future__ import annotations

from app.eval.gate import ALL, aggregate, compare
from app.eval.golden import GoldenPair
from app.eval.metrics import score
from app.eval.target import TargetOutput

_RERANKED = ("gold", "b", "c", "d", "e")
_VECTOR_ORDER = ("b", "c", "d", "e", "gold")
"""The same five chunks with the golden one last: what falling back to vector order looks like when
the reranker had been putting it first. Nothing leaves the top 5, so recall cannot see it."""


def _row(pair_id: str, retrieved: tuple[str, ...]) -> tuple[GoldenPair, dict[str, float | None]]:
    pair = GoldenPair(
        id=pair_id,
        question="Which value?",
        intent="factual",
        kind="table",
        answerable=True,
        answer="42",
        chunk_ids=("gold",),
    )
    output = TargetOutput(
        predicted_intent="factual",
        retrieved_chunk_ids=retrieved,
        cited_chunk_ids=("gold",),
        answer="42",
        latency_ms=1.0,
    )
    return pair, score(pair, output)


def test_losing_the_reranker_fails_on_ndcg_and_mrr_while_recall_stays_green() -> None:
    baseline, counts = aggregate([_row(f"q{i}", _RERANKED) for i in range(20)])
    current, _ = aggregate([_row(f"q{i}", _VECTOR_ORDER) for i in range(20)])

    regressions = compare(current, baseline, baseline_counts=counts)

    failed = {(r.metric, r.kind) for r in regressions}
    assert ("ndcg_at_5", "table") in failed
    assert ("mrr", "table") in failed
    assert ("ndcg_at_5", ALL) in failed
    assert not any(metric == "recall_at_5" for metric, _ in failed), "recall@5 cannot see a rank change"
    assert "table" in next(r for r in regressions if r.metric == "ndcg_at_5").describe()
