## T001: Aggregate answering path

**Requirements:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005 (`docs/EPIC_2_PLAN.md` §2.4 table)

**Description:** `app/generation/corpus_answer_service.py` implements the map-reduce
answering path for `aggregate`-intent questions: vector search top-N documents, Voyage
rerank scoring, per-document map step, reduce/synthesis with Citations API grounding,
floor check, overflow logging.

**Acceptance criteria:**
- [ ] Candidate selection is vector search → top-N documents (N≈15 default,
      configurable), not a per-chunk or whole-corpus scan
- [ ] Scoring reuses `app/retrieval/reranker.py`'s existing Voyage rerank call — no new
      LLM-based 0-100 importance scoring call is added
- [ ] Reduce/synthesis step uses the same Citations-API document-block pattern as
      `app/generation/answer_service.py:94-132` (`_build_document_blocks`,
      `_extract_citations`) — reused, not reimplemented
- [ ] When the context budget is exceeded, dropped candidates are logged (count and
      identifiers) via `structlog`, matching this repo's logging convention — never a
      silent `break`
- [ ] When no candidate scores above a stated floor, the service returns a canned "no
      data" answer instead of synthesizing from weak material — floor value empirically
      validated against the Phase 2.1 golden set's aggregate-class questions (not assumed
      from graphrag's own number)
- [ ] `app/api/routers/ask.py`'s `aggregate` branch calls this service instead of the
      Phase 2.0 refusal

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_corpus_answering.py -v`
- [ ] Build/static check succeeds: `uv run ruff check . && uv run ty check .`

**Dependencies:** EPIC2-P3 CP-001 (replay harness proven — this task's tests run against
recorded cassettes, not live calls)

**Workstream:** ws-2.4

**Context pointers:**
- Project/module rules: `portfolio/CLAUDE.md` § "The tenant boundary" (this path still
  reads through `Retriever`/`QdrantStore`, so tenant scoping is inherited, not
  reimplemented)
- Closest precedent: `app/generation/answer_service.py` (mirrors its shape for citations
  and generation)
- Shared contract/invariant: Anthropic Citations API usage
  (`app/generation/answer_service.py:94-132`), Voyage rerank
  (`app/retrieval/reranker.py:29-33`)

**Files/areas touched:**
- `app/generation/corpus_answer_service.py`
- `app/api/routers/ask.py`
- `tests/unit/test_corpus_answering.py`

**Estimated scope:** L

---

## T002: Scoped single-document bypass

**Requirements:** REQ-007 (`docs/EPIC_2_PLAN.md` § Phase 2.0 write-up, "belongs with 2.4's
corpus-level work")

**Description:** When `document_scope.resolve_scope` resolves a question to exactly one
`doc_id`, bypass reranking and pass that document's chunks in document order, up to the
context budget — reusing T001's map-step machinery with N=1, rather than the current
rerank-then-truncate path that can silently drop a field on a multi-chunk document.

**Acceptance criteria:**
- [ ] When exactly one `doc_id` resolves from `document_scope.resolve_scope`, retrieval
      returns that document's chunks in document order (not reranked-and-truncated)
- [ ] Chunks passed up to the context budget, with overflow logged (same discipline as
      T001)
- [ ] Multi-document or unscoped questions are unaffected — this path activates only on
      exactly one resolved `doc_id`

**Verification:**
- [ ] Tests pass: `uv run pytest tests/unit/test_corpus_answering.py -v` (extended with
      single-doc cases) or a dedicated `tests/unit/test_document_scope_bypass.py`

**Dependencies:** T001

**Workstream:** ws-2.4

**Context pointers:**
- Project/module rules: `docs/EPIC_2_PLAN.md` § Phase 2.0, "A schema is not a search
  query" paragraph — names the exact defect this fixes (whole-document extraction
  silently dropping a field via `rerank_top_n=5`)
- Closest precedent: `app/retrieval/document_scope.py:135-289` (`resolve_scope`)
- Shared contract/invariant: T001's map-step machinery

**Files/areas touched:**
- `app/retrieval/document_scope.py` or `app/retrieval/retriever.py`
- `tests/unit/test_corpus_answering.py` or new dedicated test file

**Estimated scope:** M

---

## T003: Gated shipping decision via the eval gate

**Requirements:** REQ-006 (`docs/EPIC_2_PLAN.md` §2.4, "Done when")

**Description:** Not a code task — the explicit measurement gate this phase's own spec
text requires before either T001/T002 merge to `main`.

**Acceptance criteria:**
- [ ] EPIC2-P3's `eval-gate` CI job run against T001/T002's branch, specifically comparing
      aggregate-class golden-question scores (must improve over the current
      refusal-only baseline) and factual-class scores (must stay within tolerance,
      unchanged)
- [ ] If either condition fails, T001/T002 do not merge — this is a hard gate, not a
      recommendation

**Verification:**
- [ ] Manual check: eval-gate CI run output reviewed against both conditions before merge

**Dependencies:** T001, T002

**Workstream:** ws-2.4

**Context pointers:**
- Project/module rules: None
- Closest precedent: None
- Shared contract/invariant: EPIC2-P3's `eval-gate` job and `data/eval/baseline_scores.json` (was `baseline.parquet` before the 2026-09-24 LangSmith decision)

**Files/areas touched:**
- None (process gate, not a code change)

**Estimated scope:** XS
