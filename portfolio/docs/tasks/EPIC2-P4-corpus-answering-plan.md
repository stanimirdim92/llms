# Implementation Plan: Epic 2 Phase 2.4 — Corpus-level answering

Status: Draft
Spec: docs/EPIC_2_PLAN.md § Phase 2.4 (fused spec+plan doc — convention note in
EPIC2-P1-golden-set-plan.md, not repeated here)
Spec status: N/A — repo convention
Spec revision: git-commit:7d260b927770ac672dc003aee2dad47cf6bf84c6:docs/EPIC_2_PLAN.md
Approved by: —
Approved at: —

## Technical Approach

### Current Flow
`app/api/routers/ask.py:119-125` routes the `aggregate` intent to an explicit "not
supported yet" refusal (Phase 2.0's deliberate stopgap — its real answer path is this
phase). `document_scope.py` already resolves a question to zero, one, or many `doc_ids`
but the single-document case still runs through the same rerank-then-truncate path as an
unscoped question.

### Proposed Flow
`aggregate` questions: vector search → top-N documents (O(N≈15), not O(corpus)) → Voyage
rerank scores candidates → per-document map step → reduce/synthesis with Citations API
grounding → floor check (no candidate above floor → canned "no data" answer, not a weak
synthesis) → overflow logging (not a silent `break`).

Scoped single-document questions (carried over from Phase 2.0's write-up): when
`document_scope.resolve_scope` resolves to exactly one `doc_id`, bypass reranking entirely
and pass that document's chunks in document order, up to the context budget — reusing this
phase's map-step machinery with N=1.

### Components and Responsibilities
- `app/generation/corpus_answer_service.py` (NEW): mirrors `answer_service.py`'s shape for
  the map-reduce path.
- `app/api/routers/ask.py` (MODIFIED): `aggregate` branch calls the new service instead of
  refusing.
- `app/retrieval/document_scope.py` / `app/retrieval/retriever.py` (MODIFIED): single-doc
  bypass.

### Affected Areas
- `app/generation/`
- `app/api/routers/ask.py`
- `app/retrieval/`

## Decisions and Provenance

Every design choice in this phase is already fully specified in `docs/EPIC_2_PLAN.md`'s
Phase 2.4 table (candidate selection, scoring, grounding, overflow handling) — cited
directly per task below, no new `TD-###` needed.

- Candidate selection: vector search → top-N documents, not a whole-corpus map — source:
  spec §2.4 table row 1.
- Scoring: reuse Voyage rerank scores, not a fresh LLM importance call — source: spec §2.4
  table row 2.
- Grounding: reuse the Anthropic Citations API already wired in `answer_service.py:94-132`
  — source: spec §2.4 table row 3.
- Overflow handling: log the drop count — source: spec §2.4 table row 4.
- Below-floor behavior: canned "no data" answer, kept verbatim from graphrag's design —
  source: spec §2.4 "Kept verbatim" paragraph.

## Task Index

- [ ] T001 (L, ws-2.4, deps: EPIC2-P3 CP-001) [REQ-001, REQ-002, REQ-003, REQ-004, REQ-005]: Aggregate answering path
- [ ] T002 (M, ws-2.4, deps: T001) [REQ-007]: Scoped single-document bypass
- [ ] T003 (M, ws-2.4, deps: T001, T002) [REQ-006]: Gated shipping decision via the eval gate

## Requirement Coverage

- REQ-001 (aggregate branch implements map-reduce over top-N documents, O(N≈15)) → T001 → unit test
- REQ-002 (candidate scoring reuses Voyage rerank scores) → T001 → unit test asserting no fresh LLM-scoring call is made
- REQ-003 (grounding reuses Anthropic Citations API) → T001 → unit test on citation output shape
- REQ-004 (budget overflow logs the drop count, not a silent break) → T001 → unit test asserting a log line on overflow
- REQ-005 (below-floor → canned "no data" answer) → T001 → unit test
- REQ-006 (ships only if it beats current path on aggregate-class AND leaves factual unchanged, measured via Phase 2.3's gate) → T003 → EPIC2-P3's eval-gate CI job
- REQ-007 (scoped single-doc bypass: chunks in document order, up to budget) → T002 → unit test

Unmapped requirements: None
Orphan tasks: None

## Verification Strategy

- Task-focused: `uv run pytest tests/unit/test_corpus_answering.py -v` (stubbed
  retrieval+generation, in-memory Qdrant — mirrors `tests/unit/test_retrieval_consistency.py`'s
  pattern, no live services)
- Integrated: `uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/unit -v`, plus EPIC2-P3's `eval-gate` CI job run specifically
  against aggregate-class and factual-class golden questions (T003)

## Risks and Mitigations

| Risk | Trigger/evidence | Mitigation | Task/checkpoint |
|---|---|---|---|
| The map-reduce path doesn't beat the refusal-only baseline on aggregate questions, or regresses factual-class scores | EPIC2-P3's eval gate shows no aggregate-class improvement, or a factual-class regression beyond tolerance | REQ-006/T003 makes shipping explicitly conditional on the gate; do not merge if it doesn't clear the bar | T003 |
| Reusing rerank scores for corpus-level candidate scoring produces different score semantics than graphrag's 0-100 importance score (different scale/calibration assumptions baked into the floor check) | floor check systematically over- or under-triggers the "no data" refusal | T001's acceptance criteria include validating the floor threshold empirically against the golden set, not carrying over graphrag's literal 0-100 number | T001 |

## Open Questions

None.

---
Handoff: Awaiting plan approval
