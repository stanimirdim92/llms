"""Epic 2 Phase 2.3's scoring and gate logic. Pure functions, so no service and no network.

These are what decide whether CI fails on a retrieval regression, so they get the tests the
pipeline run itself can't: `scripts/run_eval.py` needs a seeded corpus and provider keys.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from app.eval.gate import ALL, aggregate, compare, read_baseline, write_baseline
from app.eval.golden import GoldenPair, load_golden
from app.eval.langsmith_evaluators import example_payload
from app.eval.metrics import citation_precision, ndcg_at_k, recall_at_k, reciprocal_rank, score
from app.eval.target import TargetOutput

if TYPE_CHECKING:
    from pathlib import Path


def _pair(**overrides: object) -> GoldenPair:
    fields: dict = {
        "id": "q900",
        "question": "What was measured?",
        "intent": "factual",
        "kind": "prose",
        "answerable": True,
        "answer": "Accuracy.",
        "chunk_ids": ("c1",),
    }
    fields.update(overrides)
    return GoldenPair(**fields)


def _output(**overrides: object) -> TargetOutput:
    fields: dict = {
        "predicted_intent": "factual",
        "retrieved_chunk_ids": ("c1", "c2"),
        "cited_chunk_ids": ("c1",),
        "answer": "Accuracy.",
        "latency_ms": 10.0,
    }
    fields.update(overrides)
    return TargetOutput(**fields)


# -------------------------------------------------------------------------------------------
# Metrics
# -------------------------------------------------------------------------------------------


def test_recall_counts_golden_chunks_found_in_the_top_k() -> None:
    assert recall_at_k(("a", "b"), ["a", "x", "y"]) == 0.5
    assert recall_at_k(("a",), ["x", "x", "x", "x", "x", "a"]) == 0.0, "rank 6 is outside the top 5"


def test_ndcg_drops_when_the_right_chunk_slides_down_but_recall_does_not() -> None:
    """The reason nDCG is in the set: a reranker regression that keeps the chunk in the top 5
    is invisible to recall@5.
    """
    top = ["a", "x", "y", "z", "w"]
    fifth = ["x", "y", "z", "w", "a"]
    assert recall_at_k(("a",), top) == recall_at_k(("a",), fifth) == 1.0
    assert ndcg_at_k(("a",), top) == 1.0
    assert ndcg_at_k(("a",), fifth) < 0.5


def test_reciprocal_rank_is_one_over_the_first_hit() -> None:
    assert reciprocal_rank(("b",), ["a", "b"]) == 0.5
    assert reciprocal_rank(("b",), ["a"]) == 0.0


def test_no_citations_is_a_failure_not_a_pass() -> None:
    assert citation_precision(("a",), []) == 0.0
    assert citation_precision(("a",), ["a", "x"]) == 0.5


def test_non_retrieval_pairs_score_routing_only() -> None:
    """An unanswerable question has no right chunk. Scoring it 0 would punish correctly finding nothing."""
    scores = score(_pair(answerable=False, chunk_ids=()), _output())
    assert scores["routing_accuracy"] == 1.0
    assert scores["recall_at_5"] is None
    assert scores["citation_precision"] is None


def test_a_failed_classification_is_a_routing_miss() -> None:
    """Excluding it instead would let an outage raise routing accuracy."""
    scores = score(_pair(), _output(predicted_intent=None, retrieved_chunk_ids=(), error_code=503))
    assert scores["routing_accuracy"] == 0.0
    assert scores["recall_at_5"] == 0.0


# -------------------------------------------------------------------------------------------
# Gate
# -------------------------------------------------------------------------------------------


def test_aggregate_reports_each_kind_and_excludes_non_applicable_rows() -> None:
    rows: list[tuple[GoldenPair, dict[str, float | None]]] = [
        (_pair(kind="prose"), {"recall_at_5": 1.0}),
        (_pair(kind="table"), {"recall_at_5": 0.0}),
        (_pair(kind="refusal"), {"recall_at_5": None}),
    ]
    scores, counts = aggregate(rows)
    assert scores["recall_at_5"] == {ALL: 0.5, "prose": 1.0, "table": 0.0}
    assert counts["recall_at_5"][ALL] == 2, "a None must not count towards the mean"


def test_a_drop_beyond_tolerance_is_named_by_metric_and_kind() -> None:
    baseline = {"ndcg_at_5": {ALL: 0.80, "table": 0.81}}
    current = {"ndcg_at_5": {ALL: 0.78, "table": 0.52}}
    regressions = compare(current, baseline, tolerance=0.05)
    assert [(r.metric, r.kind) for r in regressions] == [("ndcg_at_5", "table")]
    assert "table" in regressions[0].describe()


def test_a_cell_that_vanishes_fails_the_gate() -> None:
    """A metric that silently stops being computed must not turn the gate green."""
    regressions = compare({}, {"mrr": {ALL: 0.7}})
    assert len(regressions) == 1
    assert regressions[0].current is None


def test_an_improvement_is_not_a_regression() -> None:
    assert compare({"mrr": {ALL: 0.9}}, {"mrr": {ALL: 0.7}}) == []


def test_the_baseline_round_trips_and_is_sorted_for_readable_diffs(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    write_baseline({"mrr": {"table": 0.123456, ALL: 0.5}}, {"mrr": {ALL: 2, "table": 1}}, {"git_sha": "abc"}, path)
    assert read_baseline(path) == {"mrr": {ALL: 0.5, "table": 0.1235}}
    text = path.read_text()
    assert text.index('"all"') < text.index('"table"')
    assert json.loads(text)["meta"]["git_sha"] == "abc"


# -------------------------------------------------------------------------------------------
# Golden set and its LangSmith copy
# -------------------------------------------------------------------------------------------


def test_the_committed_golden_set_loads() -> None:
    pairs = load_golden()
    assert len(pairs) >= 50
    assert len({p.id for p in pairs}) == len(pairs)


def test_an_empty_golden_set_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n")
    with pytest.raises(ValueError, match="no golden pairs"):
        load_golden(empty)


def test_example_ids_are_stable_so_a_resync_updates_instead_of_duplicating() -> None:
    pair = _pair()
    assert example_payload(pair)["id"] == example_payload(_pair())["id"]
    assert example_payload(pair)["id"] != example_payload(_pair(id="q901"))["id"]
