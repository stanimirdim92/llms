"""The LangSmith side: dataset example shape and the evaluator used for uploaded experiments.

Thin on purpose. Scoring lives in `app/eval/metrics.py`, so an uploaded experiment and the
offline gate score identically, and a later move off LangSmith (Langfuse is the deferred
alternative, `docs/TECHNICAL_DECISIONS.md`) ports this file and nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langsmith.evaluation import EvaluationResult, EvaluationResults

from app.eval.golden import GoldenPair
from app.eval.judges import judge_scores
from app.eval.metrics import score
from app.eval.target import TargetOutput

if TYPE_CHECKING:
    from langsmith.schemas import Example, Run

DATASET_NAME = "portfolio-golden"


def example_payload(pair: GoldenPair) -> dict:
    """One golden pair as a LangSmith example. `id` is deterministic, so a re-sync updates the
    same example instead of adding a duplicate.
    """
    return {
        "id": pair.example_id,
        "inputs": {"question": pair.question},
        "outputs": {
            "answer": pair.answer,
            "intent": pair.intent,
            "answerable": pair.answerable,
            "chunk_ids": list(pair.chunk_ids),
        },
        "metadata": {"pair_id": pair.id, "kind": pair.kind},
    }


def pair_from_example(example: Example) -> GoldenPair:
    outputs = example.outputs or {}
    metadata = example.metadata or {}
    return GoldenPair(
        id=metadata["pair_id"],
        question=(example.inputs or {})["question"],
        intent=outputs["intent"],
        kind=metadata["kind"],
        answerable=outputs["answerable"],
        answer=outputs["answer"],
        chunk_ids=tuple(outputs["chunk_ids"]),
    )


def _results(scores: dict[str, float | None]) -> EvaluationResults:
    """Metrics that don't apply (`None`) are omitted rather than sent as 0, matching how the
    offline gate excludes them from its means.
    """
    return {"results": [EvaluationResult(key=key, score=value) for key, value in scores.items() if value is not None]}


def _pair(example: Example | None) -> GoldenPair:
    if example is None:
        # Every run here is over a dataset, so a missing example is a wiring error, not a skip.
        msg = "evaluator called without a dataset example"
        raise ValueError(msg)
    return pair_from_example(example)


def pipeline_metrics(run: Run, example: Example | None) -> EvaluationResults:
    """Every applicable retrieval/routing metric for one example, as a LangSmith multi-score result."""
    return _results(score(_pair(example), TargetOutput.from_dict(run.outputs or {})))


async def answer_judges(run: Run, example: Example | None) -> EvaluationResults:
    """The LLM judges. Separate from `pipeline_metrics` so a run can be scored without paying for
    judge calls.
    """
    return _results(await judge_scores(_pair(example), TargetOutput.from_dict(run.outputs or {})))
