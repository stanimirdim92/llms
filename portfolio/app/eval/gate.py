"""Aggregate per-question scores and compare them with the committed baseline.

`data/eval/baseline_scores.json` is the gate's reference, in git on purpose: a regression then
shows up as a reviewable diff, and the reference outlives LangSmith's experiment retention. This
module is plain Python with no LangSmith import, so the gate runs in a network-free job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.eval.golden import EVAL_DIR

if TYPE_CHECKING:
    from pathlib import Path

    from app.eval.golden import GoldenPair

BASELINE_PATH = EVAL_DIR / "baseline_scores.json"
ALL = "all"
DEFAULT_TOLERANCE = 0.05
"""Absolute drop allowed per cell before the gate fails. Deliberately not zero: live model calls
are not bit-reproducible, and a gate that fails on noise gets disabled."""

Scores = dict[str, dict[str, float]]
"""metric -> question kind (or "all") -> mean over the pairs where the metric applies."""


@dataclass(frozen=True)
class Regression:
    metric: str
    kind: str
    baseline: float
    current: float | None

    def describe(self) -> str:
        now = "missing" if self.current is None else f"{self.current:.3f}"
        return f"{self.metric} on {self.kind} questions: {self.baseline:.3f} -> {now}"


def aggregate(rows: list[tuple[GoldenPair, dict[str, float | None]]]) -> tuple[Scores, dict[str, dict[str, int]]]:
    """Means per metric, overall and per question kind, plus how many pairs each mean covers.

    Per kind, not only overall: a gate reporting one average hides a table-lookup collapse under
    forty healthy prose questions, and a failure has to name the class that moved.
    """
    sums: dict[str, dict[str, float]] = {}
    counts: dict[str, dict[str, int]] = {}
    for pair, metrics in rows:
        for metric, value in metrics.items():
            if value is None:
                continue
            for cell in (ALL, pair.kind):
                sums.setdefault(metric, {}).setdefault(cell, 0.0)
                counts.setdefault(metric, {}).setdefault(cell, 0)
                sums[metric][cell] += value
                counts[metric][cell] += 1
    means = {metric: {cell: cells[cell] / counts[metric][cell] for cell in cells} for metric, cells in sums.items()}
    return means, counts


def compare(current: Scores, baseline: Scores, tolerance: float = DEFAULT_TOLERANCE) -> list[Regression]:
    """Every baseline cell that dropped by more than `tolerance`, or vanished.

    A cell that disappears is a regression, not a pass: a metric that silently stops being
    computed would otherwise turn the gate green.
    """
    regressions = []
    for metric, cells in sorted(baseline.items()):
        for kind, reference in sorted(cells.items()):
            now = current.get(metric, {}).get(kind)
            if now is None or now < reference - tolerance:
                regressions.append(Regression(metric=metric, kind=kind, baseline=reference, current=now))
    return regressions


def write_baseline(scores: Scores, counts: dict[str, dict[str, int]], meta: dict, path: Path = BASELINE_PATH) -> None:
    """Sorted and rounded, so the file diffs readably in a pull request."""
    rounded = {m: {k: round(v, 4) for k, v in sorted(cells.items())} for m, cells in sorted(scores.items())}
    payload = {"meta": meta, "scores": rounded, "counts": counts}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_baseline(path: Path = BASELINE_PATH) -> Scores:
    return json.loads(path.read_text(encoding="utf-8"))["scores"]
