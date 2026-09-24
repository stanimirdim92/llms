# Implementation Plan: Epic 2 Phase 2.2 — Run storage (parquet + DuckDB)

Status: Draft
Spec: docs/EPIC_2_PLAN.md § Phase 2.2 (fused spec+plan doc — see EPIC2-P1's plan for the
convention note; not repeated per document)
Spec status: N/A — repo convention, see EPIC2-P1-golden-set-plan.md
Spec revision: git-commit:7d260b927770ac672dc003aee2dad47cf6bf84c6:docs/EPIC_2_PLAN.md
Approved by: —
Approved at: —

## Technical Approach

### Current Flow
None — no eval run has ever been recorded. No parquet writer, DuckDB usage, or `app/eval/`
package exists anywhere in the repo (confirmed by recon).

### Proposed Flow
An eval run (produced by running the golden set from Phase 2.1 through the real
retrieve→rerank→generate pipeline) emits one row per (question × retrieved chunk), written
to `data/eval/runs/<run_id>.parquet`. Analysis queries `data/eval/runs/*.parquet` directly
via DuckDB — no service, no table, no migration.

### Components and Responsibilities
- `app/eval/schema.py` (NEW): the row shape, one place naming all 16 columns.
- `app/eval/pricing.py` (NEW): the committed per-model price table `cost_usd` is computed from.
- `app/eval/run_store.py` (NEW): `write_run()` and a DuckDB query helper. `duckdb`/
  `pyarrow` imported lazily inside functions, never at module top level — mirrors
  `app/retrieval/reranker.py:20-22`'s `_local_compressor()` pattern for the same reason:
  the api/worker runtime image never installs the `eval` extra, so a top-level import
  would crash the app even though `app/eval/` ships as source (`.docker/Dockerfile:120`
  COPYs all of `app/` unconditionally).

### Affected Areas
- `app/eval/` (new package)
- `pyproject.toml`, `uv.lock`
- `.gitignore`

## Decisions and Provenance

- RAGAS metrics wrapped as LangSmith custom evaluators (not built here — Phase 2.3) —
  source: spec §Phase 2.3, not re-litigated.
- Parquet+DuckDB over Postgres — source: spec §Phase 2.2 ¶3, `docs/ARCHITECTURE.md` §2b
  (append-only analytical data, evolving schema, CI needs a diffable committed baseline a
  DB row can't provide). Not re-argued here; inherited.
- Parquet+DuckDB alongside (not instead of) LangSmith — source: spec §Phase 2.2 ¶4 (the
  regression gate must work offline and in version control; LangSmith stays for
  interactive trace exploration).

### TD-001 — Dependency placement for `duckdb`
- Choice: new `eval` optional-dependency group in `pyproject.toml` (joins `ragas` in
  Phase 2.3).
- Alternatives: add to the existing `dev` extra.
- Reason: `dev` is tooling to develop/lint/test this repo (ruff, ty, pytest, pre-commit,
  pip-audit); `duckdb`/`ragas` are libraries the eval harness *imports at runtime* when
  actually running an eval. Conflating the two makes `dev` a catch-all. This repo already
  draws exactly this line once, for `local-reranker` (optional runtime-adjacent code path,
  its own extra, not folded into `dev`) — `eval` follows that precedent rather than
  inventing a new pattern.
- Source: mirrors `pyproject.toml:95-99` (`local-reranker` extra).
- Affects: T002, and Phase 2.3's `ragas`/`vcrpy` additions to the same group.

### TD-002 — Module placement and import discipline
- Choice: `app/eval/` (new subpackage), with `duckdb`/`pyarrow` imported lazily inside
  each function that needs them, `# noqa: PLC0415` per the established convention.
- Alternatives: `scripts/`-only (no importable package); eager top-level imports.
- Reason: `tests/unit/` needs an importable module to unit-test the schema/writer without
  going through a CLI (no precedent in this repo for logic living only in `scripts/`
  with no `app/` counterpart — every existing CLI, e.g. `create_tenant.py`, is a thin
  wrapper calling into `app/`). Eager imports would break api/worker boot: the runtime
  image ships `app/eval/`'s source (whole `app/` is COPYed) but the `eval` extra is never
  installed there, exactly the situation `app/retrieval/reranker.py:20-22` already solved
  for `sentence-transformers`/`torch`.
- Source: `app/retrieval/reranker.py:16-25` (`_local_compressor`), `.docker/Dockerfile:120`.
- Affects: T002.

### TD-003 — `.gitignore` for per-run files
- Choice: add `data/eval/runs/` to `.gitignore`.
- Alternatives: commit every run's parquet file.
- Reason: the spec explicitly calls `qa_dataset.jsonl` and `baseline.parquet` "committed"
  but says nothing about per-run files, and nothing currently ignores `data/eval/runs/` —
  every local or CI eval run would otherwise accumulate as an uncommitted-by-convention
  but not-actually-ignored file, one commit away from silently bloating the repo. The
  sibling entry `data/eval/results/` (already gitignored, currently unused) is the
  precedent that generated eval output belongs in `.gitignore`.
- Source: `.gitignore:13` (existing `data/eval/results/` entry).
- Affects: T003.

## Task Index

- [ ] T001 (S, ws-2.2, deps: —) [REQ-001]: Define the run-row schema
- [ ] T002 (M, ws-2.2, deps: T001) [REQ-002, REQ-003, TD-001, TD-002]: Parquet writer + DuckDB query helper
- [ ] T003 (XS, ws-2.2, deps: T002) [REQ-002, TD-003]: Gitignore per-run output

## Requirement Coverage

- REQ-001 (one row per question × retrieved chunk, 16 named columns) → T001 → schema unit test
- REQ-002 (written to `data/eval/runs/<run_id>.parquet`) → T002, T003 → round-trip test + gitignore check
- REQ-003 (DuckDB over `data/eval/runs/*.parquet`, no service/table/migration; `duckdb` added, `pyarrow`/`pandas` already present) → T002 → dependency-add verified against `pyproject.toml`
- REQ-004 (not Postgres — verification-only, decision already made in spec) → docs/ARCHITECTURE.md §2b, no task needed; behavior preserved by construction (no new Postgres table is added anywhere in this phase)
- REQ-005 (not LangSmith-only — verification-only) → same as REQ-004, no task needed

Unmapped requirements: None
Orphan tasks: None

## Verification Strategy

- Task-focused: `uv run pytest tests/unit/test_eval_schema.py -v` (T001),
  `uv run pytest tests/unit/test_eval_run_store.py -v` (T002 — parquet round-trip and
  DuckDB query against a `tmp_path`, no live services needed)
- Integrated: `uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/unit -v`
- Data/migration: None — file-based, not a Postgres table; no Alembic revision applies
  here (stated explicitly so it isn't reflexively added).

## Risks and Mitigations

| Risk | Trigger/evidence | Mitigation | Task/checkpoint |
|---|---|---|---|
| A future edit adds a top-level `import duckdb`/`import ragas` in `app/eval/`, crashing api/worker boot (extra not installed there) | api container fails to start with `ModuleNotFoundError: duckdb` | T002 keeps imports function-local per TD-002; a unit test asserting `app.api.main`'s import graph never reaches `app.eval.*` (mirrors the existing api/ingestion boundary test named in `portfolio/CLAUDE.md` § Producer/consumer split) | T002 |
| `data/eval/runs/` grows unbounded without the gitignore fix | repo diff shows stray parquet files after a few local eval runs | T003 | T003 |

## Open Questions

None blocking. **`cost_usd` was the one; resolved 2026-09-24** -- a committed price table in
`app/eval/pricing.py`, not `Settings`, raising on an unpriced model; detail and the prices in
T001. What still needs a human is approval of this plan.

---
Handoff: Awaiting plan approval
