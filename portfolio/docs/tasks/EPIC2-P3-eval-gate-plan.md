# Implementation Plan: Epic 2 Phase 2.3 — Metrics and the CI gate

Status: Draft
Spec: docs/EPIC_2_PLAN.md § Phase 2.3 (fused spec+plan doc — convention note in
EPIC2-P1-golden-set-plan.md, not repeated here)
Spec status: N/A — repo convention
Spec revision: git-commit:7d260b927770ac672dc003aee2dad47cf6bf84c6:docs/EPIC_2_PLAN.md
Approved by: —
Approved at: —

## Technical Approach

### Current Flow
No metrics, no gate, no CI job exists for evaluation. `.github/workflows/portfolio-ci.yml`
has three jobs today (`static`, `test`, `security`) plus an on-main-only `stack` job — none
of them touch `data/eval/` or call a retrieval/generation pipeline.

### Proposed Flow
1. A recording/replay harness captures real Anthropic/Voyage responses once, locally, with
   real keys, and replays them deterministically thereafter — see TD-001/TD-002 below;
   this is new work, not in the original spec text, made necessary by a gap the spec did
   not anticipate (no CI secrets exist for this repo).
2. A "before" baseline (naive fixed-size chunking, no reranker) is recorded once against
   the Phase 2.1 golden set, producing the first `data/eval/runs/<run_id>.parquet` via
   Phase 2.2's writer.
3. recall@k, routing accuracy, and RAGAS-wrapped-as-LangSmith-evaluators metrics are
   computed from that run.
4. The baseline run is promoted to `data/eval/baseline.parquet`, committed.
5. A CI job replays cassettes, regenerates a fresh run, diffs per-metric-per-question-class
   against the baseline with a stated tolerance, and fails the build naming the specific
   regression.

### Components and Responsibilities
- `app/eval/replay.py` (NEW): cassette-backed wrapper around every provider call site used
  by an eval run.
- `app/eval/metrics.py` (NEW): recall@k, routing-accuracy confusion matrix.
- `app/eval/ragas_evaluators.py` (NEW): RAGAS metrics wrapped as LangSmith custom
  evaluators.
- `.github/workflows/portfolio-ci.yml` (MODIFIED): new `eval-gate` job.
- `data/eval/baseline.parquet` (NEW, committed).
- `data/eval/cassettes/` (NEW, committed).

### Affected Areas
- `app/eval/`
- `.github/workflows/portfolio-ci.yml`
- `pyproject.toml`, `uv.lock`
- `data/eval/`

## Decisions and Provenance

- RAGAS metrics (faithfulness, answer relevancy, context precision/recall) wrapped as
  LangSmith custom evaluators — source: spec §Phase 2.3 ¶1, `.claude/skills/langsmith-evaluator`.
- Committed `data/eval/baseline.parquet`, diffed in CI, not a DB row — source: spec
  §Phase 2.2 ¶3.

### TD-001 — How the CI gate gets provider responses (resolved conflict)
- Choice: record real Anthropic/Voyage responses once, locally, with real keys; replay
  them deterministically in CI with zero live network calls.
- Alternatives considered:
  - Provision real GitHub Actions secrets, call live APIs on every CI run — rejected:
    cost per PR, couples CI green/red to provider uptime, new secret-rotation surface,
    and this repo's CI currently has **no** provider secrets at all (`gh secret list
    --repo stanimirdim92/llms` returned empty this session — verified, not assumed).
  - Run the eval gate out-of-band (scheduled/`workflow_dispatch`, decoupled from the PR
    gate) — rejected: weaker than the spec's own framing ("CI fails the build" — a
    regression would merge before the next scheduled run caught it).
- Reason: the spec's Phase 2.2 ¶4 states the regression gate "must work offline and in
  version control." Read literally (zero network calls during the gate's execution), only
  the record/replay option satisfies it while still failing the build synchronously on a
  PR.
- Source: user decision, this session, 2026-09-09, resolving an ambiguity the spec itself
  didn't anticipate (repository evidence — no secrets — made the live-call reading
  infeasible as written).
- Affects: T001, T002, T007.

### TD-002 — Cassette library
- Choice: `vcrpy`.
- Alternatives: hand-rolled fixture JSON files; `respx` (httpx-native mock).
- Reason: `vcrpy` has a genuine two-phase `record_mode="once"`/`"none"` workflow — record
  locally with real keys, replay in CI with none — which is exactly what TD-001 needs.
  `respx` only mocks (no recording step); hand-rolled fixtures would reinvent
  request-matching logic `vcrpy` already provides. All provider SDKs used here
  (`anthropic`, `voyageai` via `langchain-voyageai`) sit on `httpx`, which `vcrpy` supports
  natively.
- Source: new technical decision — no repository precedent existed for this before now
  (`repository-precedent.md` §2 applies: justified explicitly, not presented as obvious).
  `httpx` already a pinned runtime dependency (`pyproject.toml` — pulled in by
  `fastapi[standard]`/`anthropic`/`qdrant-client`, confirmed by recon).
- Affects: T001.

### TD-003 — Cassette location
- Choice: `data/eval/cassettes/`, committed.
- Alternatives: `tests/fixtures/cassettes/`.
- Reason: cassettes are eval-domain fixtures tied one-to-one with
  `data/eval/qa_dataset.jsonl`'s question ids, not generic test fixtures — colocating
  keeps every eval-framework asset (`qa_dataset.jsonl`, `runs/`, `baseline.parquet`,
  `cassettes/`) under one directory, matching `docs/ARCHITECTURE.md` §2b's stated data-flow
  diagram.
- Affects: T001.

### TD-004 — Dependency placement
- Choice: `ragas` and `vcrpy` join the `eval` optional-dependency group created in
  Phase 2.2 (TD-001 there).
- Source: same reasoning as EPIC2-P2's TD-001; not re-argued here.
- Affects: T001, T005.

## Contracts and Data Changes

### Contract: cassette record/replay mode
- Owner: ws-2.3 (this plan)
- Consumers: Phase 2.4, Phase 2.5 (both gated through this same harness — "measured
  through 2.3 or they do not land")
- Authoritative definition: `app/eval/replay.py`
- Compatibility: additive (new module; no existing provider call site's public signature
  changes, only its transport is wrapped)
- Stabilization checkpoint: CP-001

## Task Index

- [ ] T001 (M, ws-2.3, deps: EPIC2-P2 complete) [REQ-008, TD-001, TD-002, TD-003, TD-004]: Recording/replay harness
- [ ] T002 (S, ws-2.3, deps: T001) [REQ-004]: Record the "before" baseline run

### CP-001 — Checkpoint: cassette-replay harness proven
- [ ] A recorded run replays byte-identically twice in a row
- [ ] Zero live network calls during replay (verified via a network-blocking transport in
      the replay test — any attempted real HTTP call fails the test)
- [ ] Application builds without errors

- [ ] T003 (M, ws-2.3, deps: CP-001) [REQ-002]: recall@k computation
- [ ] T004 (M, ws-2.3, deps: CP-001) [REQ-003]: Routing-accuracy confusion matrix
- [ ] T005 (L, ws-2.3, deps: CP-001) [REQ-001, TD-004]: RAGAS metrics as LangSmith evaluators
- [ ] T006 (S, ws-2.3, deps: T003, T004, T005) [REQ-005]: Promote baseline to `data/eval/baseline.parquet`
- [ ] T007 (M, ws-2.3, deps: T006) [REQ-006, REQ-007, TD-001]: CI gate job

## Requirement Coverage

- REQ-001 (RAGAS wrapped as LangSmith custom evaluators) → T005 → evaluator unit tests
- REQ-002 (recall@k against golden chunk ids) → T003 → recall@k unit tests
- REQ-003 (routing accuracy confusion matrix) → T004 → confusion-matrix unit tests
- REQ-004 (a deliberate "before" baseline first) → T002 → baseline run exists and is used by T006
- REQ-005 (`data/eval/baseline.parquet` committed, CI compares against it) → T006 → file committed, T007 reads it
- REQ-006 (gate fails on regression beyond stated tolerance, names the metric+class) → T007 → CI gate unit/integration test
- REQ-007 (dropping the reranker is caught by CI, failure names the reranker as cause) → T007 → the stated acceptance test itself
- REQ-008 (CI gate makes zero live provider calls) → T001 → CP-001's network-block test

Unmapped requirements: None
Orphan tasks: None

## Verification Strategy

- Task-focused: `uv run pytest tests/unit/test_eval_replay.py -v` (T001, network blocked),
  `uv run pytest tests/unit/test_recall_at_k.py -v` (T003),
  `uv run pytest tests/unit/test_routing_accuracy.py -v` (T004),
  `uv run pytest tests/unit/test_ragas_evaluators.py -v` (T005)
- Workstream: `uv run pytest tests/unit -k eval -v`
- Integrated: `uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/unit -v` plus the new `eval-gate` CI job (T007) added to
  `.github/workflows/portfolio-ci.yml`
- Manual/operational: re-recording cassettes (golden-set question changes, provider model
  version bump) is a human-run `--record` pass with real keys, documented in
  `docs/MEMORY.md`'s standing directives — not automated.

## Risks and Mitigations

| Risk | Trigger/evidence | Mitigation | Task/checkpoint |
|---|---|---|---|
| A cassette recorded against an old provider model version stays green forever even after a real production regression, because it never gets re-recorded | drift between what CI replays and what the live API actually returns today | T001's acceptance criteria: cassette metadata carries a recorded-at timestamp and model version; T007's gate warns (not fails) when a cassette exceeds a stated staleness threshold | T001, T007 |
| The `eval-gate` CI job's exact service dependency (does it need live Postgres for document-registry reads?) is unconfirmed until the provider-call surface is fully mapped | job written against unneeded services, or missing a needed one | Confirmed during T001/T007's own implementation against the actual call graph, not guessed here | T001, T007 |
| `ragas`'s own dependency footprint conflicts with pinned `langchain*` versions in `pyproject.toml` | `uv lock` fails to resolve after adding `ragas` | Resolve before committing; if genuinely incompatible, record a new TD here documenting the constraint (per root rule 13 — verify by resolving, not from memory) | T005 |

## Open Questions

None — TD-001 resolves the one substantive gap found during planning.

---
Handoff: Awaiting plan approval
