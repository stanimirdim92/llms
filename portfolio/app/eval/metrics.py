"""Per-question metrics, as plain functions over a golden pair and what the pipeline returned.

No LangSmith import here. The CI gate calls these directly: `aevaluate` still calls LangSmith's
API even with `upload_results=False` (measured 2026-09-24, CP-001 in the 2.3 plan), so it can't
run in a network-free job. `app/eval/langsmith_evaluators.py` wraps these same functions for
uploaded experiments, so both paths score identically.

A metric returns `None` when it doesn't apply to the pair, and `None` is excluded from every
mean. That is not the same as 0: an unanswerable question with no golden chunk that retrieves
nothing relevant has done the right thing, and a 0 would say otherwise.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.eval.golden import GoldenPair
    from app.eval.target import TargetOutput

RETRIEVAL_K = 5
"""`rerank_top_n`: what the answer is built from, so what "retrieved" means for these metrics.
The 20 pre-rerank candidates are not exposed by `/ask` and are not what the model sees."""


def recall_at_k(golden: tuple[str, ...], retrieved: list[str], k: int = RETRIEVAL_K) -> float:
    top = set(retrieved[:k])
    return sum(1 for chunk_id in golden if chunk_id in top) / len(golden)


def ndcg_at_k(golden: tuple[str, ...], retrieved: list[str], k: int = RETRIEVAL_K) -> float:
    """Binary relevance. Rank-sensitive where recall is not: a golden chunk that slips from 1st
    to 5th leaves recall@5 unchanged and lowers this, which is the reranker's whole job.
    """
    relevant = set(golden)
    dcg = sum(1 / math.log2(rank + 2) for rank, chunk_id in enumerate(retrieved[:k]) if chunk_id in relevant)
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(len(relevant), k)))
    return dcg / ideal


def reciprocal_rank(golden: tuple[str, ...], retrieved: list[str], k: int = RETRIEVAL_K) -> float:
    relevant = set(golden)
    for rank, chunk_id in enumerate(retrieved[:k], start=1):
        if chunk_id in relevant:
            return 1 / rank
    return 0.0


def citation_precision(golden: tuple[str, ...], cited: list[str]) -> float:
    """The fraction of cited chunks that are golden. An answer with no citations scores 0: every
    factual claim is supposed to cite (`prompts.py`), so none at all is a failure, not a pass.
    """
    if not cited:
        return 0.0
    relevant = set(golden)
    return sum(1 for chunk_id in cited if chunk_id in relevant) / len(cited)


def score(pair: GoldenPair, output: TargetOutput) -> dict[str, float | None]:
    """Every metric for one question. Keys are stable: `baseline_scores.json` is keyed on them."""
    # A failed classification (`predicted_intent` None) is a routing miss, not an excluded row:
    # dropping it would let an outage raise routing accuracy.
    routing = float(output.predicted_intent == pair.intent)
    if not pair.scores_retrieval:
        return {
            "routing_accuracy": routing,
            "recall_at_5": None,
            "ndcg_at_5": None,
            "mrr": None,
            "citation_precision": None,
        }
    retrieved = list(output.retrieved_chunk_ids)
    return {
        "routing_accuracy": routing,
        "recall_at_5": recall_at_k(pair.chunk_ids, retrieved),
        "ndcg_at_5": ndcg_at_k(pair.chunk_ids, retrieved),
        "mrr": reciprocal_rank(pair.chunk_ids, retrieved),
        "citation_precision": citation_precision(pair.chunk_ids, list(output.cited_chunk_ids)),
    }
