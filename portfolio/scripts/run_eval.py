"""Run the golden set through the real `/ask` pipeline and score it.

    uv run python scripts/run_eval.py                    # score locally, print the table
    uv run python scripts/run_eval.py --gate             # ...and fail on a regression vs baseline_scores.json
    uv run python scripts/run_eval.py --write-baseline   # ...and record the scores as the new baseline
    uv run python scripts/run_eval.py --upload           # run as a LangSmith experiment instead
    uv run python scripts/run_eval.py --judges ...       # add the LLM judges (correctness, groundedness)
    uv run python scripts/run_eval.py --record ...       # ...and record every provider call to data/eval/cassettes/
    uv run python scripts/run_eval.py --replay ...       # score from those recordings: no network, no keys

Needs the seeded eval corpus (`scripts/fetch_eval_corpus.py`, then `scripts/seed_eval_corpus.py`),
live Postgres and Qdrant, and `ANTHROPIC_API_KEY` / `VOYAGE_API_KEY`. `--upload` also needs
`LANGSMITH_API_KEY` and the synced dataset (`scripts/sync_eval_dataset.py`). `--replay` needs
Postgres only, loaded with `scripts/eval_registry.py load`, and is what the CI `eval-gate` job runs.

**Recording the baseline and the cassettes together** -- the one sequence that keeps the three
committed artefacts consistent with each other (run from `portfolio/`, with real keys and a stack up):

    uv sync --locked --extra dev --extra eval
    uv run python scripts/fetch_eval_corpus.py
    uv run python scripts/seed_eval_corpus.py
    uv run python scripts/eval_registry.py export
    uv run python scripts/run_eval.py --record --judges --write-baseline

then commit `data/eval/cassettes/`, `data/eval/baseline_scores.json` and
`data/eval/registry_fixture.json` together. The order matters: seeding gives every document a fresh
`ingestion_version`, the export freezes it into the fixture CI loads, and the recorded Qdrant queries
filter on it -- so a fixture exported before a re-seed makes every replayed query miss (`--record`
refuses to start if the database and the fixture disagree). `--record --write-baseline` is one pass:
the baseline is scored from the very responses the cassettes hold, so `--replay --judges --gate`
reproduces it exactly. `--replay` must be given `--judges` if and only if the recording was.

The local modes score with plain functions and never call LangSmith. That's what lets the gate
run where the network is closed: `aevaluate` calls LangSmith's API even with
`upload_results=False` (measured 2026-09-24). `--record`/`--replay` run the questions one at a time,
because the cassettes are process-global (`app/eval/replay.py`); a plain run keeps its concurrency.
"""

import argparse
import asyncio
import functools
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval_registry import FIXTURE_PATH

from app.config import MissingCredentialsError, get_settings, require_provider_credentials
from app.eval.gate import ALL, BASELINE_PATH, DEFAULT_TOLERANCE, aggregate, compare, read_baseline, write_baseline
from app.eval.golden import GoldenPair, load_golden, seed_tenant_id
from app.eval.judges import JUDGED_INTENTS, judge_scores
from app.eval.metrics import score
from app.eval.replay import (
    CASSETTE_DIR,
    SETUP_NAME,
    Harness,
    Mode,
    ReplayError,
    build_meta,
    current_models,
    current_pipeline,
    find_secrets,
    read_meta,
    require_judges_match,
    staleness_warnings,
    warm_services,
)
from app.eval.target import run_question

_CONCURRENCY = 4
"""Bounded: each question is up to three provider calls, and a burst of 67 would hit
Anthropic's rate limit and turn into retries that skew latency."""

Rows = list[tuple[GoldenPair, dict[str, float | None]]]


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _report_error(pair: GoldenPair, output_code: int | None, detail: str) -> None:
    if output_code is not None:
        print(f"  {pair.id}: /ask answered {output_code} -- {detail}", file=sys.stderr)


async def _score_locally(*, with_judges: bool) -> Rows:
    tenant_id = seed_tenant_id()
    pairs = load_golden()
    limit = asyncio.Semaphore(_CONCURRENCY)

    async def one(pair):  # noqa: ANN001, ANN202 -- local helper
        async with limit:
            output = await run_question(pair.question, tenant_id)
        _report_error(pair, output.error_code, output.answer)
        scores = score(pair, output)
        if with_judges:
            async with limit:
                scores |= await judge_scores(pair, output)
        return pair, scores

    return await asyncio.gather(*(one(pair) for pair in pairs))


async def _score_pair(pair: GoldenPair, tenant_id: str, *, with_judges: bool) -> tuple[GoldenPair, dict]:
    """One pair, question then judges, inside one cassette: the judge calls are recorded with it."""
    output = await run_question(pair.question, tenant_id)
    _report_error(pair, output.error_code, output.answer)
    scores = score(pair, output)
    if with_judges:
        scores |= await judge_scores(pair, output)
    return pair, scores


def _warn(message: str) -> None:
    # `::warning::` is what GitHub Actions turns into an annotation; elsewhere it reads as a prefix.
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "WARNING: "
    print(f"{prefix}{message}", file=sys.stderr)


async def _registry_drift() -> list[str]:
    """Documents where the live database and `registry_fixture.json` disagree.

    Recorded Qdrant queries filter on each document's `ingestion_version`, and CI builds its
    database from the fixture. A fixture exported before the last re-seed therefore records
    nothing wrong and then misses every query in CI, with a message about HTTP requests.
    """
    from app.db import get_session, init_db  # noqa: PLC0415
    from app.registry.db import list_document_records  # noqa: PLC0415

    await init_db()
    async with get_session() as session:
        records = await list_document_records(session, tenant_id=seed_tenant_id(), limit=10_000)
    live = {r.doc_id: (r.ingestion_version, r.status) for r in records}
    frozen = {
        d["doc_id"]: (d["ingestion_version"], d["status"])
        for d in json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["documents"]
    }
    return sorted(
        f"{doc_id}: database {live.get(doc_id)}, fixture {frozen.get(doc_id)}"
        for doc_id in live.keys() | frozen.keys()
        if live.get(doc_id) != frozen.get(doc_id)
    )


async def _score_sequentially(mode: Mode, *, with_judges: bool) -> Rows:
    """`--record` / `--replay`: one question at a time, each in its own cassette.

    Sequential because vcrpy patches the HTTP classes for the whole process; two questions in
    flight would play each other's recordings.
    """
    settings = get_settings()
    tenant_id = seed_tenant_id()
    pairs = load_golden()
    pair_ids = [pair.id for pair in pairs]

    if mode is Mode.RECORD:
        try:
            require_provider_credentials()
        except MissingCredentialsError as exc:
            raise ReplayError(str(exc)) from exc
        if drift := await _registry_drift():
            msg = (
                "registry_fixture.json does not match the database being recorded -- run "
                "`scripts/eval_registry.py export` first:\n  " + "\n  ".join(drift)
            )
            raise ReplayError(msg)

    with Harness(mode, qdrant_url=settings.qdrant_url) as harness:
        if mode is Mode.RECORD:
            harness.prepare_recording()
        else:
            meta = read_meta(harness.directory)
            require_judges_match(meta, judges=with_judges)
            if leaked := find_secrets(harness.directory):
                # The committed cassettes are the thing being audited: a leak that got past record
                # time (or a hand edit) is caught before it is replayed and re-published.
                raise ReplayError("credential(s) in the cassettes:\n  " + "\n  ".join(leaked))
            for warning in harness.check_replayable(pair_ids):
                _warn(warning)
            for warning in staleness_warnings(meta, current_models(settings), current_pipeline(settings)):
                _warn(warning)

        # Every lazily-built service, in its own cassette, before any question: otherwise its
        # setup calls land in whichever pair runs first.
        await harness.run(SETUP_NAME, functools.partial(warm_services, judges=with_judges))
        rows = []
        for pair in pairs:
            rows.append(
                await harness.run(pair.id, functools.partial(_score_pair, pair, tenant_id, with_judges=with_judges))
            )

        if mode is Mode.RECORD:
            meta = build_meta(settings, pair_ids, judges=with_judges, git_sha=_git_sha())
            harness.finish_recording(
                meta,
                secret_literals=[
                    settings.anthropic_api_key.get_secret_value(),
                    settings.voyage_api_key.get_secret_value(),
                    settings.langsmith_api_key.get_secret_value(),
                ],
            )
    return rows


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

    from app.eval.langsmith_evaluators import DATASET_NAME, answer_judges, pipeline_metrics  # noqa: PLC0415

    tenant_id = seed_tenant_id()

    async def target(inputs: dict) -> dict:
        return (await run_question(inputs["question"], tenant_id)).as_dict()

    sha = _git_sha()
    await aevaluate(
        target,
        data=DATASET_NAME,
        evaluators=[pipeline_metrics, answer_judges],
        experiment_prefix=f"golden-{sha}",
        metadata={"git_sha": sha, "answer_model": get_settings().answer_model},
        max_concurrency=_CONCURRENCY,
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gate", action="store_true", help="fail on a regression against the committed baseline")
    mode.add_argument("--write-baseline", action="store_true", help="record these scores as the new baseline")
    mode.add_argument("--upload", action="store_true", help="run as a LangSmith experiment")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--record", action="store_true", help="call the providers and record every call as a cassette")
    source.add_argument("--replay", action="store_true", help="answer from the recorded cassettes: no network, no keys")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="allowed absolute drop per cell")
    parser.add_argument(
        "--judges",
        action="store_true",
        help="also run the LLM judges (costs a judge call per factual/aggregate question; --upload always runs them)",
    )
    args = parser.parse_args()

    if args.upload and (args.record or args.replay):
        parser.error("--upload runs live against LangSmith; it cannot be combined with --record or --replay")
    if args.replay and args.write_baseline:
        # A baseline stamps the current settings and sha, which a replay only *assumes* match the
        # recording. The baseline is written by the pass that records.
        parser.error(
            "--write-baseline needs --record (or a live run): a baseline taken from a replay would mislabel itself"
        )
    return args


def _gate(scores: dict, args: argparse.Namespace) -> int:
    baseline, baseline_counts = read_baseline()
    regressions = compare(scores, baseline, tolerance=args.tolerance, baseline_counts=baseline_counts)
    if regressions:
        print(f"\n{len(regressions)} regression(s) beyond {args.tolerance}:", file=sys.stderr)
        for regression in regressions:
            print(f"  {regression.describe()}", file=sys.stderr)
        return 1
    print(f"\nno regression beyond {args.tolerance} against {BASELINE_PATH.name}")
    return 0


def main() -> int:
    args = _parse_args()
    if args.upload:
        return asyncio.run(_upload())

    if args.record or args.replay:
        try:
            rows = asyncio.run(
                _score_sequentially(Mode.RECORD if args.record else Mode.REPLAY, with_judges=args.judges)
            )
        except ReplayError as exc:
            print(f"\nERROR: {exc}", file=sys.stderr)
            return 2
    else:
        rows = asyncio.run(_score_locally(with_judges=args.judges))
    if args.judges:
        # A judge that returned no verdict is excluded from the mean, which quietly shrinks the
        # sample. Said out loud so a baseline isn't written over a half-judged run unnoticed.
        missing = sum(1 for pair, scores in rows if pair.intent in JUDGED_INTENTS and scores.get("correctness") is None)
        if missing:
            print(f"WARNING: {missing} judged question(s) got no correctness verdict (see judge.no_verdict)")
    scores, counts = aggregate(rows)
    _print_table(scores, counts)
    if args.record:
        print(f"\nrecorded cassettes to {CASSETTE_DIR}")

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
    return _gate(scores, args) if args.gate else 0


if __name__ == "__main__":
    raise SystemExit(main())
