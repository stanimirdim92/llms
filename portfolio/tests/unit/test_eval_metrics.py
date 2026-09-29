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
from app.eval.judges import JUDGED_INTENTS, judge_correctness, judge_groundedness
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


def test_retrieval_is_scored_for_any_answerable_pair_with_golden_chunks_whatever_its_intent() -> None:
    """The three cross-document pairs were relabelled factual -> aggregate. Gating retrieval on
    `intent == "factual"` dropped them from every retrieval and citation cell without a word.
    """
    aggregate_pair = _pair(intent="aggregate", kind="cross-document", chunk_ids=("c1", "c2"))
    scores = score(aggregate_pair, _output(predicted_intent="aggregate", retrieved_chunk_ids=("c1", "x")))
    assert scores["recall_at_5"] == 0.5
    assert scores["ndcg_at_5"] is not None
    assert scores["mrr"] == 1.0
    assert scores["citation_precision"] == 1.0


def test_the_committed_cross_document_pairs_are_scored_for_retrieval() -> None:
    """The three cross-document pairs carry golden chunks and, once relabelled, intent `aggregate`.
    Whatever their label, they must be inside every retrieval and citation cell.
    """
    cross_document = [pair for pair in load_golden() if pair.kind == "cross-document"]
    assert cross_document, "the dataset lost its cross-document class"
    assert all(pair.scores_retrieval for pair in cross_document)


def test_pairs_with_nothing_to_retrieve_are_excluded_whatever_their_intent() -> None:
    """Each exclusion has its own reason: no golden chunk (metadata, out of scope, the corpus-level
    aggregate refusals) or nothing answerable. Scoring any of them as a miss punishes correctly
    finding nothing.
    """
    for pair in (
        _pair(intent="metadata", answerable=False, chunk_ids=()),
        _pair(intent="out_of_scope", answerable=False, chunk_ids=()),
        _pair(intent="aggregate", answerable=False, chunk_ids=()),
        _pair(intent="aggregate", answerable=True, chunk_ids=()),
        _pair(intent="factual", answerable=False, chunk_ids=("c1",)),
    ):
        assert not pair.scores_retrieval, pair
        assert score(pair, _output())["recall_at_5"] is None, pair


def test_judges_cover_factual_and_aggregate_but_not_registry_reads_or_refusals() -> None:
    assert {"factual", "aggregate"} == JUDGED_INTENTS


async def test_an_intent_that_is_not_judged_costs_no_judge_call() -> None:
    """Returns before any model call, so it also proves no network is needed for the exclusion."""
    for intent in ("metadata", "out_of_scope"):
        pair = _pair(intent=intent, answerable=False, chunk_ids=())
        assert await judge_correctness(pair, _output()) is None
        assert await judge_groundedness(pair, _output(retrieved_texts=("text",))) is None


async def test_an_aggregate_answer_that_errored_is_judged_wrong_not_skipped() -> None:
    """An outage must not raise the correctness score, for aggregate any more than for factual."""
    verdict = await judge_correctness(_pair(intent="aggregate"), _output(error_code=503))
    assert verdict is not None
    assert verdict.passed is False


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


def test_one_question_flipping_in_a_small_class_is_noise_but_two_is_not() -> None:
    """Measured: identical code moved an n=3 cell by 0.33 between two live runs."""
    baseline = {"correctness": {"cross-document": 1.0}}
    counts = {"correctness": {"cross-document": 3}}
    one_flip = {"correctness": {"cross-document": 2 / 3}}
    two_flips = {"correctness": {"cross-document": 1 / 3}}
    assert compare(one_flip, baseline, baseline_counts=counts) == []
    assert len(compare(two_flips, baseline, baseline_counts=counts)) == 1


def test_an_improvement_is_not_a_regression() -> None:
    assert compare({"mrr": {ALL: 0.9}}, {"mrr": {ALL: 0.7}}) == []


def test_the_baseline_round_trips_and_is_sorted_for_readable_diffs(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    write_baseline({"mrr": {"table": 0.123456, ALL: 0.5}}, {"mrr": {ALL: 2, "table": 1}}, {"git_sha": "abc"}, path)
    scores, counts = read_baseline(path)
    assert scores == {"mrr": {ALL: 0.5, "table": 0.1235}}
    assert counts == {"mrr": {ALL: 2, "table": 1}}
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
