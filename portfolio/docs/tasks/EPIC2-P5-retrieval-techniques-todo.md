## T001: Dynamic prompt assembly

**Requirements:** REQ-001 (`docs/EPIC_2_PLAN.md` §2.5 item 1)

**Description:** Deterministic, no-model-call prompt assembly — table-reading guidance
only when a table chunk survived reranking, figure guidance only when a figure chunk did.
Stable prefix first, variable content last, after the final prompt-cache breakpoint.

**Acceptance criteria:**
- [ ] Table-reading guidance block included in the prompt if and only if a table-type
      chunk (per `app/vectorstore`'s `chunk_type` metadata) is among the reranked
      candidates
- [ ] Figure guidance block included if and only if a figure-type chunk is present —
      same condition structure as the table case
- [ ] Plain `if`/`else`, no model call, per rule 5
- [ ] Prompt structure keeps a stable prefix (system instructions, unconditional content)
      first and all conditionally-included, per-question content last, after the final
      cache breakpoint
- [ ] A test asserts the stable-prefix bytes are identical across two calls with different
      retrieved chunk sets (proves the cache breakpoint doesn't move)

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_dynamic_prompt.py -v`
- [ ] Build/static check succeeds: `uv run ruff check . && uv run ty check .`

**Dependencies:** EPIC2-P3 CP-001

**Workstream:** ws-2.5

**Context pointers:**
- Project/module rules: Root `CLAUDE.md` rule 5 ("Use the model only for judgment calls")
- Closest precedent: `app/generation/answer_service.py`'s existing prompt construction
- Shared contract/invariant: prompt-caching prefix-match behavior — the trap named
  explicitly in the spec

**Files/areas touched:**
- `app/generation/answer_service.py`
- `tests/unit/test_dynamic_prompt.py`

**Estimated scope:** M

---

## T002: Query expansion

**Requirements:** REQ-002 (`docs/EPIC_2_PLAN.md` §2.5 item 2)

**Description:** HyDE or n-paraphrase generation → embed each → union the candidate sets →
rerank the union, for vocabulary mismatch ("does NMC degrade?" vs. "capacity fade in
LiNi₀.₈Mn₀.₁Co₀.₁O₂"). Ships only if it measurably improves recall@k.

**Acceptance criteria:**
- [ ] Implementation choice (HyDE vs. n-paraphrase) decided and justified during this
      task, against the golden set's vocabulary-mismatch cases from Phase 2.1
- [ ] Expanded queries embedded, candidate sets unioned, reranked as one set (not
      per-query reranking then merged rankings)
- [ ] EPIC2-P3's eval-gate comparison run: ships only if recall@k improves; if it doesn't,
      this task's acceptance criteria are met by *documenting that it was measured and
      dropped*, not by forcing a merge anyway

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_query_expansion.py -v` (replay-backed)
- [ ] Manual check: EPIC2-P3 eval-gate recall@k comparison reviewed before any merge
      decision

**Dependencies:** EPIC2-P3 CP-001

**Workstream:** ws-2.5

**Context pointers:**
- Project/module rules: None
- Closest precedent: None (first query-expansion implementation in this repo)
- Shared contract/invariant: `app/retrieval/retriever.py`'s existing single-embedding
  search path

**Files/areas touched:**
- `app/retrieval/retriever.py`
- `tests/unit/test_query_expansion.py`

**Estimated scope:** L

---

## T003: Query decomposition

**Requirements:** REQ-003 (`docs/EPIC_2_PLAN.md` §2.5 item 3)

**Description:** Splits a multi-part question ("compare X and Y") into sub-questions
before retrieval, since one embedding of the combined question averages both and matches
neither. Gated behind Phase 2.0's intent classifier — not run on every question, since it
costs n× retrieval plus a synthesis step.

**Acceptance criteria:**
- [ ] Decomposition triggers only through Phase 2.0's classifier detecting a multi-part
      question — no unconditional fallback path that runs it on every question
- [ ] Each sub-question retrieved independently (n× retrieval), results synthesized in one
      final answer
- [ ] EPIC2-P3's eval-gate comparison run: ships only if recall@k improves on the
      multi-part-question subset of the golden set

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_query_decomposition.py -v` (replay-backed)
- [ ] Manual check: eval-gate recall@k comparison on multi-part questions, reviewed before
      merge

**Dependencies:** T001

**Workstream:** ws-2.5

**Context pointers:**
- Project/module rules: None
- Closest precedent: T002 (query expansion) — the union/rerank shape is related but
  distinct: expansion unions candidate sets for one question, decomposition retrieves
  separately per sub-question and synthesizes
- Shared contract/invariant: `app/generation/intent_router.py`'s classifier output —
  reused, not reimplemented, as the gating signal

**Files/areas touched:**
- `app/retrieval/retriever.py`
- `app/api/routers/ask.py` (gating on classifier output)
- `tests/unit/test_query_decomposition.py`

**Estimated scope:** L
