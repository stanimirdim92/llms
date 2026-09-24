"""Run the golden set through the real `/ask` pipeline and score it.

    uv run python scripts/run_eval.py                    # score locally, print the table
    uv run python scripts/run_eval.py --gate             # ...and fail on a regression vs baseline_scores.json
    uv run python scripts/run_eval.py --write-baseline   # ...and record the scores as the new baseline
    uv run python scripts/run_eval.py --upload           # run as a LangSmith experiment instead

Needs the seeded eval corpus (`scripts/fetch_eval_corpus.py`, then `scripts/seed_eval_corpus.py`),
live Postgres and Qdrant, and `ANTHROPIC_API_KEY` / `VOYAGE_API_KEY`. `--upload` also needs
`LANGSMITH_API_KEY` and the synced dataset (`scripts/sync_eval_dataset.py`).

The local modes score with plain functions and never call LangSmith. That's what lets the gate
run where the network is closed: `aevaluate` calls LangSmith's API even with
`upload_results=False` (measured 2026-09-24).
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.eval.gate import ALL, BASELINE_PATH, DEFAULT_TOLERANCE, aggregate, compare, read_baseline, write_baseline
from app.eval.golden import load_golden, seed_tenant_id
from app.eval.metrics import score
from app.eval.target import run_question

_CONCURRENCY = 4
"""Bounded: each question is up to three provider calls, and a burst of 67 would hit
Anthropic's rate limit and turn into retries that skew latency."""


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


async def _score_locally() -> list:
    tenant_id = seed_tenant_id()
    pairs = load_golden()
    limit = asyncio.Semaphore(_CONCURRENCY)

    async def one(pair):  # noqa: ANN001, ANN202 -- local helper
        async with limit:
            output = await run_question(pair.question, tenant_id)
        if output.error_code is not None:
            print(f"  {pair.id}: /ask answered {output.error_code} -- {output.answer}", file=sys.stderr)
        return pair, score(pair, output)

    return await asyncio.gather(*(one(pair) for pair in pairs))


def _print_table(scores: dict, counts: dict) -> None:
    kinds = sorted({kind for cells in scores.values() for kind in cells} - {ALL})
    print(f"{'metric':<20}" + "".join(f"{k:>16}" for k in [ALL, *kinds]))
    for metric in sorted(scores):
        row = "".join(
            f"{scores[metric][k]:>10.3f} (n={counts[metric][k]:>2})" if k in scores[metric] else f"{'-':>16}"
            for k in [ALL, *kinds]
        )
        print(f"{metric:<20}{row}")


async def _upload() -> int:
    from langsmith import aevaluate  # noqa: PLC0415 -- only this mode talks to LangSmith

    from app.eval.langsmith_evaluators import DATASET_NAME, pipeline_metrics  # noqa: PLC0415

    tenant_id = seed_tenant_id()

    async def target(inputs: dict) -> dict:
        return (await run_question(inputs["question"], tenant_id)).as_dict()

    sha = _git_sha()
    await aevaluate(
        target,
        data=DATASET_NAME,
        evaluators=[pipeline_metrics],
        experiment_prefix=f"golden-{sha}",
        metadata={"git_sha": sha, "answer_model": get_settings().answer_model},
        max_concurrency=_CONCURRENCY,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gate", action="store_true", help="fail on a regression against the committed baseline")
    mode.add_argument("--write-baseline", action="store_true", help="record these scores as the new baseline")
    mode.add_argument("--upload", action="store_true", help="run as a LangSmith experiment")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="allowed absolute drop per cell")
    args = parser.parse_args()

    if args.upload:
        return asyncio.run(_upload())

    rows = asyncio.run(_score_locally())
    scores, counts = aggregate(rows)
    _print_table(scores, counts)

    if args.write_baseline:
        settings = get_settings()
        meta = {
            "git_sha": _git_sha(),
            "answer_model": settings.answer_model,
            "intent_router_model": settings.intent_router_model,
        }
        write_baseline(scores, counts, meta)
        print(f"\nwrote {BASELINE_PATH}")
        return 0

    if args.gate:
        regressions = compare(scores, read_baseline(), tolerance=args.tolerance)
        if regressions:
            print(f"\n{len(regressions)} regression(s) beyond {args.tolerance}:", file=sys.stderr)
            for regression in regressions:
                print(f"  {regression.describe()}", file=sys.stderr)
            return 1
        print(f"\nno regression beyond {args.tolerance} against {BASELINE_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
