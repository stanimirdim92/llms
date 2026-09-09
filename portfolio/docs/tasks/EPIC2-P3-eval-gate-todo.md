## T001: Recording/replay harness

**Requirements:** REQ-008 (`docs/EPIC_2_PLAN.md` §2.2 ¶4, read literally — see TD-001); TD-001, TD-002, TD-003, TD-004

**Description:** A thin wrapper around every provider call site an eval run touches, so a
`--record` pass hits live Anthropic/Voyage APIs once and writes `vcrpy` cassettes to
`data/eval/cassettes/`, and every other run replays them with `record_mode="none"`
(hard-fails on any cassette miss, rather than silently falling through to a real call).

**Acceptance criteria:**
- [ ] `vcrpy` added to the `eval` optional-dependency group (`pyproject.toml`), `uv lock`
      run and committed
- [ ] `app/eval/replay.py` wraps the identified provider call sites: `app/generation/
      answer_service.py` (Anthropic generation + citations), `app/generation/
      intent_router.py` (classifier call), `app/retrieval/reranker.py` (Voyage rerank),
      and whatever performs query embedding
- [ ] `--record` mode hits live APIs and writes one cassette per golden-set question id
      under `data/eval/cassettes/`, tagged with a recorded-at timestamp and the provider
      model version in use at record time
- [ ] Default (non-record) mode replays with `record_mode="none"`: any request not found
      in a cassette raises, rather than silently calling the real API
- [ ] A test proves replay makes zero live network calls: block the transport (e.g. a
      raising `httpx.MockTransport` substituted for the real one) and confirm a replayed
      run still completes correctly
- [ ] A recorded run replays byte-identically on two separate replay passes (CP-001)

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_eval_replay.py -v`
- [ ] Build/static check succeeds: `uv run ruff check . && uv run ty check .`

**Dependencies:** EPIC2-P2 (run storage) complete

**Workstream:** ws-2.3

**Context pointers:**
- Project/module rules: None
- Closest precedent: `app/retrieval/reranker.py:16-25` (lazy optional-dependency import
  discipline — apply the same pattern to `vcrpy`/`duckdb` imports in `app/eval/`)
- Shared contract/invariant: this module is the authoritative definition of the
  record/replay contract (see plan's Contracts section) — Phase 2.4/2.5 both depend on it
  working correctly, not just existing

**Files/areas touched:**
- `app/eval/replay.py`
- `pyproject.toml`, `uv.lock`
- `data/eval/cassettes/` (directory, populated by a real `--record` run, not by this task's tests)
- `tests/unit/test_eval_replay.py`

**Estimated scope:** M

---

## T002: Record the "before" baseline run

**Requirements:** REQ-004 (`docs/EPIC_2_PLAN.md` §2.3 ¶2)

**Description:** A human-run `--record` pass — naive fixed-size chunking, no reranker —
against the Phase 2.1 golden set, producing both the cassette set (T001) and the first
`data/eval/runs/<run_id>.parquet` (Phase 2.2's writer).

**Acceptance criteria:**
- [ ] A one-off "naive" retrieval configuration exists for this run only (fixed-size
      chunking, reranker disabled) — does not change the default pipeline configuration
- [ ] Run executed once, locally, with real provider keys, in `--record` mode
- [ ] Produces `data/eval/runs/<run_id>.parquet` via `app.eval.run_store.write_run()`
      (Phase 2.2)
- [ ] Cassettes for every golden-set question committed to `data/eval/cassettes/`

**Verification:**
- [ ] Manual check: run executed and its output parquet inspected (row count matches
      golden-set size × retrieved-chunk count)

**Dependencies:** T001

**Workstream:** ws-2.3

**Context pointers:**
- Project/module rules: None
- Closest precedent: EPIC2-P1's T002 (also a one-time human-run step with real keys)
- Shared contract/invariant: `app.eval.schema` row shape (Phase 2.2)

**Files/areas touched:**
- `data/eval/runs/<run_id>.parquet` (gitignored, local only)
- `data/eval/cassettes/`

**Estimated scope:** S

---

## T003: recall@k computation

**Requirements:** REQ-002 (`docs/EPIC_2_PLAN.md` §2.3 ¶1)

**Description:** recall@k against the golden `chunk_ids`, reading `data/eval/runs/*.parquet`
via `app.eval.run_store`, reported per question class (`intent_label`).

**Acceptance criteria:**
- [ ] `app/eval/metrics.py::recall_at_k(run_id, k)` returns recall@k overall and broken
      down by `intent_label`
- [ ] Computed purely from run-row columns (`chunk_id`, `in_golden_set`, `rank`) — no
      new provider call

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_recall_at_k.py -v`

**Dependencies:** CP-001

**Workstream:** ws-2.3

**Context pointers:**
- Project/module rules: `.claude/skills/qdrant-search-quality` (recall@k methodology)
- Closest precedent: None
- Shared contract/invariant: `app.eval.schema` row shape

**Files/areas touched:**
- `app/eval/metrics.py`
- `tests/unit/test_recall_at_k.py`

**Estimated scope:** M

---

## T004: Routing-accuracy confusion matrix

**Requirements:** REQ-003 (`docs/EPIC_2_PLAN.md` §2.3 ¶1)

**Description:** A confusion matrix comparing each row's `intent_label` (expected, from
the golden set) against `predicted_label` (Phase 2.0's classifier output, already a run-row
column).

**Acceptance criteria:**
- [ ] `app/eval/metrics.py::routing_confusion_matrix(run_id)` returns a 4x4 matrix over
      the `Intent` literal values

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_routing_accuracy.py -v`

**Dependencies:** CP-001

**Workstream:** ws-2.3

**Context pointers:**
- Project/module rules: None
- Closest precedent: None
- Shared contract/invariant: `Intent` literal, `app/generation/intent_router.py:27`

**Files/areas touched:**
- `app/eval/metrics.py`
- `tests/unit/test_routing_accuracy.py`

**Estimated scope:** M

---

## T005: RAGAS metrics as LangSmith evaluators

**Requirements:** REQ-001 (`docs/EPIC_2_PLAN.md` §2.3 ¶1); TD-004

**Description:** Faithfulness, answer relevancy, context precision, and context recall
wrapped as LangSmith custom evaluators, per `.claude/skills/langsmith-evaluator`.

**Acceptance criteria:**
- [ ] `ragas` added to the `eval` optional-dependency group; `uv lock` resolves cleanly
      against pinned `langchain*` versions (verify by resolving — do not assume
      compatibility from memory, per root rule 13)
- [ ] `app/eval/ragas_evaluators.py` wraps the four named RAGAS metrics as LangSmith
      custom evaluator callables, following `.claude/skills/langsmith-evaluator`'s
      "Creating Evaluators - custom code" pattern
- [ ] Evaluators consume a run's questions/answers/contexts (via `app.eval.run_store`) and
      write scores back as additional run-row or aggregate output — exact shape decided
      during implementation, consistent with T001's schema

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_ragas_evaluators.py -v` (replay-backed
      via T001, no live provider calls)
- [ ] Build/static check succeeds: `uv run ruff check . && uv run ty check .`

**Dependencies:** CP-001

**Workstream:** ws-2.3

**Context pointers:**
- Project/module rules: `.claude/skills/langsmith-evaluator`, `.claude/skills/langsmith-dataset`
- Closest precedent: None (first RAGAS integration in this repo — recon confirmed no
  existing evaluator object)
- Shared contract/invariant: LangSmith wiring is currently tracing-only
  (`app/config.py:260-271` `_configure_langsmith`) — this task adds the first evaluator
  object, it does not extend an existing one

**Files/areas touched:**
- `app/eval/ragas_evaluators.py`
- `pyproject.toml`, `uv.lock`
- `tests/unit/test_ragas_evaluators.py`

**Estimated scope:** L

---

## T006: Promote baseline to `data/eval/baseline.parquet`

**Requirements:** REQ-005 (`docs/EPIC_2_PLAN.md` §2.3 ¶3)

**Description:** Commit T002's baseline run as the fixed comparison point CI diffs
against.

**Acceptance criteria:**
- [ ] `data/eval/baseline.parquet` committed (not gitignored — distinct from
      `data/eval/runs/`, per EPIC2-P2's T003)
- [ ] Contains T002's naive-baseline run, with T003/T004/T005's metrics computed and
      available against it

**Verification:**
- [ ] Manual check: file present and loadable via `app.eval.run_store`'s query helper

**Dependencies:** T003, T004, T005

**Workstream:** ws-2.3

**Context pointers:**
- Project/module rules: None
- Closest precedent: None
- Shared contract/invariant: `app.eval.schema` row shape

**Files/areas touched:**
- `data/eval/baseline.parquet`

**Estimated scope:** S

---

## T007: CI gate job

**Requirements:** REQ-006, REQ-007 (`docs/EPIC_2_PLAN.md` §2.3 ¶3-4, "Done when"); TD-001

**Description:** A new `eval-gate` job in `.github/workflows/portfolio-ci.yml` that
replays cassettes (T001), regenerates a fresh run, diffs per-metric-per-question-class
against `data/eval/baseline.parquet` (T006) with a stated tolerance, and fails the build
naming the specific regression.

**Acceptance criteria:**
- [ ] New job in `.github/workflows/portfolio-ci.yml`, `needs: [test]` (or `static`,
      confirmed during implementation against the job's actual dependency needs — see the
      plan's noted risk), makes zero live network calls (T001's replay mode, no CI secrets
      required — consistent with `gh secret list` showing none exist)
- [ ] Runs the current code's retrieval+generation against the golden set via cassette
      replay, produces a fresh `data/eval/runs/<run_id>.parquet`
- [ ] Diffs the fresh run's recall@k / routing-accuracy / RAGAS metrics against
      `data/eval/baseline.parquet`, per question class, against an explicit, stated
      tolerance (not "any change fails")
- [ ] On regression, the job's failure output names the specific metric and question class
      that moved — not just an aggregate score
- [ ] **Acceptance test**: with the reranker deliberately disabled (a throwaway local
      branch/fixture), the gate fails and its output identifies the reranker /
      context-precision-recall class as the cause

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_eval_gate.py -v` (the diff/tolerance
      logic, unit-tested against fixture parquet files, independent of CI)
- [ ] Manual check: the reranker-disabled acceptance test above, run once to confirm the
      failure message names the right cause

**Dependencies:** T006

**Workstream:** ws-2.3

**Context pointers:**
- Project/module rules: None
- Closest precedent: `.github/workflows/portfolio-ci.yml:203-218` (the existing
  skip-detection loop's shape — assert-and-fail-loud pattern, same spirit for a metric
  regression)
- Shared contract/invariant: `data/eval/baseline.parquet` (T006)

**Files/areas touched:**
- `.github/workflows/portfolio-ci.yml`
- `app/eval/gate.py` (or similar — the diff/tolerance logic)
- `tests/unit/test_eval_gate.py`

**Estimated scope:** M
