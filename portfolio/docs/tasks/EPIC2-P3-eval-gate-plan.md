# Implementation Plan: Epic 2 Phase 2.3 — Metrics and the CI gate (on LangSmith)

Status: Approved (rewritten 2026-09-24 for LangSmith datasets and experiments)
Spec: docs/EPIC_2_PLAN.md § Phase 2.2 and § Phase 2.3 (fused spec+plan doc — convention note in
EPIC2-P1-golden-set-plan.md, not repeated here)
Spec status: N/A — repo convention
Approved by: the user
Approved at: 2026-09-24

**What changed on 2026-09-24.** The first draft wrote each eval run to a local parquet store
(Phase 2.2, now retired) and committed `data/eval/baseline.parquet`. The user decided evals and
datasets live in LangSmith instead (`docs/TECHNICAL_DECISIONS.md` § "Evals: LangSmith
datasets and experiments"). So here, a run is a LangSmith experiment, and the committed baseline
is a small summary-score file. The record/replay harness (TD-001/TD-002) is kept from the first
draft unchanged.

## Technical Approach

### Current Flow
No metrics, no gate, no eval CI job. The golden set exists (`data/eval/qa_dataset.jsonl`, 67
pairs, checked by `tests/unit/test_qa_dataset.py`). LangSmith is wired for tracing only
(`app/config.py::_configure_langsmith`). No LangSmith dataset or evaluator exists.

### Proposed Flow
1. `qa_dataset.jsonl` stays the source of truth in git. A sync script upserts it into a
   LangSmith dataset. Datasets have indefinite retention.
2. An **eval target** runs one golden question through the real `/ask` pipeline and returns
   everything a metric needs: predicted intent, retrieved chunk ids in rank order, answer,
   citations, latency, tokens.
3. **Evaluators** score each example. Retrieval and routing metrics are our own code, because
   LangSmith has no idea what a chunk id is. RAGAS or LLM-as-judge covers the answer text.
4. **Manual runs** call `aevaluate(...)` against the LangSmith dataset and upload an
   experiment, compared side by side in the LangSmith UI. Experiment runs get extended
   retention by default.
5. A **baseline** experiment of today's pipeline, as it ships, is recorded once. Its summary scores, per metric ×
   question class, are committed as `data/eval/baseline_scores.json`.
6. The **CI gate** builds the examples from the local `qa_dataset.jsonl`, replays the recorded
   provider calls, and runs `aevaluate(..., upload_results=False)`. It compares against
   `baseline_scores.json` with a stated tolerance and fails naming the metric and question class
   that moved. It needs no LangSmith call and no provider keys (see Open question 1).

### Components and Responsibilities
- `scripts/sync_eval_dataset.py` (NEW): `qa_dataset.jsonl` → LangSmith dataset, tagged with the git sha.
- `app/eval/examples.py` (NEW): loads `qa_dataset.jsonl` into LangSmith `Example`s for offline runs.
- `app/eval/replay.py` (NEW): cassette-backed wrapper around every provider call an eval run makes.
- `app/eval/target.py` (NEW): the `/ask`-pipeline target function and its output shape.
- `app/eval/metrics.py` (NEW): recall@k, nDCG@k/MRR, routing accuracy, citation success, as
  plain functions plus thin LangSmith evaluator wrappers.
- `app/eval/judges.py` (NEW): RAGAS / LLM-as-judge answer-quality evaluators.
- `app/eval/gate.py` (NEW): the summary-vs-baseline comparison and its failure message.
- `data/eval/baseline_scores.json` (NEW, committed), `data/eval/cassettes/` (NEW, committed).
- `.github/workflows/portfolio-ci.yml` (MODIFIED): new `eval-gate` job.

### Affected Areas
- `app/eval/`, `scripts/`, `data/eval/`
- `.github/workflows/portfolio-ci.yml`
- `pyproject.toml`, `uv.lock` (new `eval` extra: `vcrpy`, `ragas`; `langsmith` is already a
  runtime dependency)

## Decisions and Provenance

- **LangSmith datasets + experiments, not a local run store.** User decision, 2026-09-24;
  reasoning in `docs/TECHNICAL_DECISIONS.md`.
- **`qa_dataset.jsonl` stays authoritative in git.** It was hand-written and is the most
  valuable eval asset, so it must not live only in a SaaS. The LangSmith dataset is a synced copy.
- **The baseline is `baseline_scores.json`, not a LangSmith experiment id.** A regression has
  to show up as a reviewable diff in the PR, and a committed file is the only thing that does.
- **Retrieval metrics are our code.** They compare returned chunk ids against golden ones,
  which no hosted evaluator can do.

### TD-001 — How the CI gate gets provider responses (kept from the first draft)
- Choice: record real Anthropic/Voyage responses once, locally, with real keys, then replay
  them deterministically in CI with zero live network calls.
- Rejected: live API calls with CI secrets on every run (cost per PR, green/red tied to
  provider uptime, and the repo has no provider secrets), and an out-of-band scheduled gate (a
  regression merges before the gate runs).
- Source: user decision, 2026-09-09.

### TD-002 — Cassette library (kept)
- Choice: `vcrpy`. It records once with `record_mode="once"` and replays with `"none"`. The
  provider SDKs used here sit on `httpx`, which `vcrpy` supports.
- Rejected: `respx` (mocks only, no recording step) and hand-rolled fixture JSON (would
  reinvent request matching).

### TD-003 — Dependency placement
- Choice: `vcrpy` and `ragas` go in a new `eval` optional-dependency group. The Docker images
  run `uv sync` without extras, so neither reaches the api, worker or Streamlit image.
  `app/eval/` imports them lazily, following `app/retrieval/reranker.py`'s pattern.

## Build status (2026-09-24)

Built, lint- and type-clean. **Neither the new unit tests nor the pipeline run have been
executed in-session** (user instruction: sessions don't run tests):
- `answer_question` pulled out of the `/ask` route (`app/api/routers/ask.py`), so the route and
  the eval target run the same code.
- `app/eval/golden.py`: loader, pair ids, and the pinned seed tenant.
- `app/eval/target.py`: the target; errors are kept as data.
- `app/eval/metrics.py`: routing accuracy, recall@5, nDCG@5, MRR, citation precision.
- `app/eval/gate.py`: per-kind aggregation, comparison, the baseline file.
- `app/eval/langsmith_evaluators.py`: example shape and a multi-score evaluator.
- `scripts/sync_eval_dataset.py`, `scripts/run_eval.py` (`--gate`, `--write-baseline`, `--upload`).
- `tests/unit/test_eval_metrics.py`.

Not built, and why:
- **T002 replay:** recording needs real keys. It also can't make CI self-contained on its own
  (Open question 3).
- **T005 judges:** `ragas` raises dependency red flags (Open question 4).
- **T006 baseline:** a human run with keys against the seeded stack.
- **T007's CI job:** needs T002 and T006. The gate *logic* and `run_eval.py --gate` exist.

## Task Index

- [x] T001 (S) [dataset]: Sync script and local example loader (sync not yet run against LangSmith)
- [ ] T002 (M) [TD-001, TD-002]: Recording/replay harness

### CP-001 — Checkpoint: offline evaluation proven
- [ ] A recorded run replays identically twice in a row
- [ ] Zero live network calls during replay (a network-blocking transport fails the test on any real call)
- [x] ~~`aevaluate(..., upload_results=False)` on local examples completes with no LangSmith key set~~
      **Measured 2026-09-24: it scores correctly but is not network-free.** Even under
      `tracing_context(enabled="local")` it calls LangSmith's `/info` and `/runs/multipart`, and the
      failures are soft. Fallback taken: the gate scores with the plain metric functions and never
      calls `aevaluate`; only `--upload` uses it.

- [x] T003 (M, deps: CP-001): Eval target over the `/ask` pipeline
- [x] T004 (M, deps: T003): Retrieval, routing and citation evaluators
- [ ] T005 (L, deps: T003) [TD-003]: RAGAS / LLM-as-judge evaluators
- [ ] T006 (S, deps: T004, T005): Record the baseline of today's pipeline, commit `baseline_scores.json`
- [ ] T007 (M, deps: T006): CI gate job

## Verification Strategy

- Task-focused tests per task (network blocked where replay is involved), run by the user
  or CI. The user asked on 2026-09-24 that sessions not run the suite themselves.
- Integrated: the repo gate plus the new `eval-gate` job.
- Operational: re-recording cassettes after golden-set edits or a model version bump is a
  human-run `--record` pass with real keys.

## Risks and Mitigations

| Risk | Mitigation | Task |
|---|---|---|
| A cassette recorded against an old model version stays green after a real regression | Cassettes carry a recorded-at date and model id; the gate warns past a staleness threshold | T002, T007 |
| `upload_results=False` still wants a LangSmith client or key, or `Example` requires a `dataset_id` | Proven at CP-001 before anything builds on it; if it fails, fall back to calling our metric functions directly on target outputs, with no `aevaluate` in CI | CP-001 |
| `ragas` conflicts with the pinned `langchain*` versions | Resolve with `uv lock` before committing (root rule 13) | T005 |
| Evaluators written against LangSmith's SDK need porting if the platform moves to Langfuse | Metric logic lives in plain functions; the LangSmith wrappers are thin | T004, T005 |

## Open Questions

1. ~~**Does offline `aevaluate` really need no network?**~~ **No** (measured, see CP-001). The gate
   doesn't use it.
2. ~~**Which configuration the "before" baseline uses.**~~ **Resolved 2026-09-24 (user):** the baseline is today's pipeline as it ships, real chunker and reranker included. No naive-chunking run, no no-reranker experiment, and no reranker score used as a metric (the reranker is part of the system under test, so it can't grade itself).

3. **The gate reads Postgres, and replay can't record that.** `answer_question` reads the
   registry (`list_active_versions` for every factual question, the document list for metadata
   ones), and it queries Qdrant. `vcrpy` can record HTTP (Anthropic, Voyage, and Qdrant's REST
   client), but not Postgres. So a CI gate also needs the eval tenant's registry rows in CI's
   Postgres. The likely answer is a small committed fixture of those rows (doc_id, filename,
   status, ingestion_version), loaded before the run. Not decided or built.
4. **`ragas` raises two red flags from `docs/MEMORY.md`'s dependency directive.** `ragas` 0.4.3
   resolves, but it downgrades three installed packages (`fsspec` 2026.7.0→2026.6.0, `jiter`
   0.16.0→0.14.0, `rich` 15.0.0→14.3.4) and adds `nest-asyncio`, which monkey-patches asyncio
   (checked with `uv pip install --dry-run`, 2026-09-24). The alternatives are LangSmith's
   LLM-as-judge or a small Claude judge of our own. The user's call.

---
Handoff: Approved and partly built; T002, T005, T006 and the CI job are pending (see Build status)
