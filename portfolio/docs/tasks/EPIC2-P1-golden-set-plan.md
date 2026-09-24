# Implementation Plan: Epic 2 Phase 2.1 — Golden set

Status: Built 2026-09-17 (`9b2e1ae`, `e794e5f`, `be6c04d`) without this plan being approved; kept as history
Spec: docs/EPIC_2_PLAN.md § Phase 2.1 (repo convention: fused spec+plan doc, no formal REQ-### header — ids below are derived from its phase text, not invented)
Spec status: N/A — see note above; treated as approved by standing project convention (partially built from this doc already: Phase 2.0 shipped straight from it)
Spec revision: git-commit:7d260b927770ac672dc003aee2dad47cf6bf84c6:docs/EPIC_2_PLAN.md
Approved by: —
Approved at: —

> **As built, and where it departs from this plan** (checked against the tree 2026-09-24). The
> authoritative account is `docs/EPIC_2_PLAN.md` § Phase 2.1; the checkboxes below were never ticked.
>
> - **T001:** six arXiv PDFs, pinned by versioned id + sha256 in `data/eval/corpus_manifest.json`.
>   *No non-PDF format*, against the acceptance criterion. No license note either -- the PDFs are
>   not committed (`scripts/fetch_eval_corpus.py` downloads and verifies them), so the repo
>   redistributes nothing.
> - **T002:** `scripts/seed_eval_corpus.py` runs the real `ingest_document` under a *pinned*
>   seed tenant id and reads `data/eval/chunk_manifest.json` back out of Qdrant; `--check` reports
>   drift. *No `tests/unit/test_seed_eval_corpus.py`* and no byte-identical idempotency test --
>   figure chunks are legitimately non-reproducible (they depend on the vision model's caption),
>   so that criterion could not hold as written.
> - **T003:** 67 pairs, each also carrying `answerable` and the sha256 of every cited chunk.
>   Checked by `tests/unit/test_qa_dataset.py` (not `test_eval_golden_set.py`) against the
>   committed `chunk_manifest.json`, not live Qdrant, so it never skips.

## Technical Approach

### Current Flow
None — no fixed document corpus exists. The original six-arXiv-paper demo corpus was
removed with the shared `global` tenant on 2026-08-03 (`docs/TECHNICAL_DECISIONS.md` §
"The shared corpus, removed 2026-08-03"). `scripts/create_tenant.py` is the only seed
tooling that exists today, and it creates an empty tenant with no documents.

### Proposed Flow
1. Pin a fixed, format-diverse set of source documents (task-selected, see T001 — this
   plan does not name specific files; see Open Questions).
2. `scripts/seed_eval_corpus.py` creates a dedicated eval-golden-set tenant (reusing
   `scripts/create_tenant.py`'s machinery) and ingests the pinned documents through the
   real ingestion pipeline (`app.ingestion.pipeline`), pinning chunker settings so chunk
   ids are stable.
3. A human hand-writes 50+ Q&A pairs against the ingested corpus, each carrying the
   question, accepted answer, golden `chunk_ids`, and `intent_label` — committed to
   `data/eval/qa_dataset.jsonl`.

This whole phase is a **local, human-run, one-time** step (real Voyage/Anthropic keys
needed for ingestion and figure captioning) — it is not CI-automated. It produces the
fixture data Phase 2.2's run storage and Phase 2.3's replay harness consume.

### Components and Responsibilities
- `scripts/seed_eval_corpus.py` (NEW): tenant + corpus creation, mirrors
  `scripts/create_tenant.py`'s CLI shape.
- `data/eval/qa_dataset.jsonl` (NEW, committed): the golden set itself.

### Affected Areas
- `scripts/`
- `data/eval/` (new directory)
- `tests/unit/` (new sanity-check suite)

## Decisions and Provenance

- Seed script mirrors `scripts/create_tenant.py`'s CLI pattern (argparse, lazy
  `init_db()`, `asyncio.run(main())`) — source: precedent `scripts/create_tenant.py:19,164-168,184-185`.
- Golden-set methodology (question design, hard-case coverage, recall@k framing) follows
  the `qdrant:qdrant-search-quality` plugin skill rather than an invented process — source: spec
  §Phase 2.1 ¶4, explicit instruction.

## Task Index

- [ ] T001 (S, ws-2.1, deps: —) [REQ-001]: Select and pin the golden-set source documents
- [ ] T002 (M, ws-2.1, deps: T001) [REQ-001, REQ-002]: Seed script ingests the pinned corpus into a dedicated tenant
- [ ] T003 (L, ws-2.1, deps: T002) [REQ-003, REQ-004, REQ-005]: Hand-write and commit the golden Q&A set

## Requirement Coverage

- REQ-001 (recreate a fixed, tenant-owned corpus, reproducible from a script) → T001, T002 → seed script re-run produces an identical tenant/document set
- REQ-002 (chunk ids stable — pin documents and chunker settings before writing pairs) → T002 → re-running the seed script twice yields identical chunk ids (idempotency test)
- REQ-003 (50+ pairs in `data/eval/qa_dataset.jsonl`, each with question/answer/chunk_ids/intent_label) → T003 → schema sanity test
- REQ-004 (hand-written hard cases; not machine-generated wholesale) → T003 → manual review, category checklist in T003's acceptance criteria
- REQ-005 (follow the `qdrant:qdrant-search-quality` plugin skill methodology) → T003 → cited in the task's context pointers

Unmapped requirements: None
Orphan tasks: None

## Verification Strategy

- Task-focused: `uv run pytest tests/unit/test_eval_golden_set.py -v` (T002/T003 — parses
  `qa_dataset.jsonl`, asserts every row has the four required fields, `intent_label` is
  one of `app/generation/intent_router.py`'s four `Intent` literal values, and every
  referenced `chunk_id` exists in Qdrant for the seed tenant; skips when no live
  Postgres/Qdrant, mirroring `tests/unit/test_create_tenant.py`'s skip pattern)
- Integrated: `uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/unit -v` (repo gate, `portfolio/CLAUDE.md` § Verification gate)
- Manual/operational: running `scripts/seed_eval_corpus.py` against a live stack with
  real provider keys is a documented one-time step (recorded in `docs/MEMORY.md`), not
  automated in CI — CI has no provider secrets (`gh secret list` confirmed empty this
  session).

## Risks and Mitigations

| Risk | Trigger/evidence | Mitigation | Task/checkpoint |
|---|---|---|---|
| Chosen source documents turn out not license-compatible with a public portfolio repo | legal/licensing review after the fact | T001's acceptance criteria require recording source + license before ingestion | T001 |
| Re-running the seed script drifts chunk ids (chunker settings change, Docling upgrade) | golden `chunk_ids` in `qa_dataset.jsonl` stop matching Qdrant | T002 pins chunker settings explicitly and is idempotency-tested | T002 |

## Open Questions

None — document selection is scoped as T001's own acceptance criterion (choose N≥6
format-diverse, license-compatible documents and record their source), not left
undecided at the plan level.

---
Handoff: Built; superseded by `docs/EPIC_2_PLAN.md` § Phase 2.1
