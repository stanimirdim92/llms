# Implementation Plan: Epic 2 Phase 2.5 — Retrieval techniques

Status: Draft
Spec: docs/EPIC_2_PLAN.md § Phase 2.5 (fused spec+plan doc — convention note in
EPIC2-P1-golden-set-plan.md, not repeated here)
Spec status: N/A — repo convention
Spec revision: git-commit:7d260b927770ac672dc003aee2dad47cf6bf84c6:docs/EPIC_2_PLAN.md
Approved by: —
Approved at: —

## Technical Approach

### Current Flow
`app/generation/answer_service.py` builds one static prompt structure regardless of what
kind of chunks survived reranking. `app/retrieval/retriever.py` embeds and searches with
exactly one query embedding per question, with no expansion or decomposition.

### Proposed Flow
Three independent techniques, in the priority order the spec states, each gated on
recall@k moving via EPIC2-P3's eval gate — a technique that doesn't move the number is
dropped, not shipped anyway:

1. Dynamic prompt assembly (deterministic, no model call): table/figure guidance blocks
   included only when a table/figure chunk survived reranking; stable prefix first,
   variable content last, after the prompt-cache breakpoint.
2. Query expansion (HyDE or n paraphrases → embed each → union → rerank the union), for
   vocabulary mismatch.
3. Query decomposition for multi-part questions, gated behind Phase 2.0's intent
   classifier rather than run on every question.

### Components and Responsibilities
- `app/generation/answer_service.py` (MODIFIED): dynamic prompt assembly.
- `app/retrieval/retriever.py` (MODIFIED): query expansion, query decomposition.

### Affected Areas
- `app/generation/`
- `app/retrieval/`

## Decisions and Provenance

All three techniques and their gating conditions are fully specified in the spec — no new
`TD-###` needed.

- Dynamic prompt assembly, deterministic `if`/`else` — source: spec §2.5 item 1, "per rule
  5" (this repo's own rule: deterministic operations get plain code, not a model call).
- Prompt-cache-safe ordering (stable prefix first, variable last) — source: spec §2.5 item
  1, explicit trap warning.
- Query expansion via HyDE/paraphrase-union-rerank, recall@k-gated — source: spec §2.5
  item 2.
- Query decomposition gated behind Phase 2.0's classifier, not run on every question (n×
  cost) — source: spec §2.5 item 3.

## Task Index

- [ ] T001 (M, ws-2.5, deps: EPIC2-P3 CP-001) [REQ-001]: Dynamic prompt assembly
- [ ] T002 (L, ws-2.5, deps: EPIC2-P3 CP-001) [REQ-002]: Query expansion
- [ ] T003 (L, ws-2.5, deps: T001) [REQ-003]: Query decomposition

## Requirement Coverage

- REQ-001 (dynamic prompt assembly, deterministic, cache-safe ordering) → T001 → unit test
- REQ-002 (query expansion, ships only if recall@k improves) → T002 → EPIC2-P3 eval-gate comparison
- REQ-003 (query decomposition, gated behind Phase 2.0's classifier, ships only if recall@k improves) → T003 → EPIC2-P3 eval-gate comparison

Unmapped requirements: None
Orphan tasks: None

## Verification Strategy

- Task-focused: `uv run pytest tests/unit/test_dynamic_prompt.py -v` (T001),
  `uv run pytest tests/unit/test_query_expansion.py -v` (T002),
  `uv run pytest tests/unit/test_query_decomposition.py -v` (T003) — all replay-backed via
  EPIC2-P3's harness, no live services
- Integrated: `uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pytest tests/unit -v`, plus EPIC2-P3's `eval-gate` CI job for T002/T003's
  recall@k-gated shipping decision

## Risks and Mitigations

| Risk | Trigger/evidence | Mitigation | Task/checkpoint |
|---|---|---|---|
| Query expansion or decomposition doesn't move recall@k, wasting the build effort | EPIC2-P3's eval gate shows no improvement | REQ-002/REQ-003 make shipping explicitly conditional; the spec itself frames this as an acceptable outcome ("it either moves that number or it is dropped") | T002, T003 |
| Dynamic prompt assembly puts variable content before the stable prefix by mistake, silently invalidating prompt caching (no functional test failure, only a cost/latency regression) | cache hit rate drops, full input price paid every request | T001's acceptance criteria include a cache-prefix-stability test | T001 |
| Query decomposition's n× retrieval cost is incurred more broadly than intended if the classifier gate is bypassed or misconfigured | latency/cost spike on questions that didn't need decomposition | T003's acceptance criteria require the classifier gate to be the only entry point — no fallback path that runs decomposition unconditionally | T003 |

## Open Questions

None.

---
Handoff: Awaiting plan approval
