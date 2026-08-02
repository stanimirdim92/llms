# Memory

State that does not survive a new session otherwise. Read this first; update it last.

**What belongs here vs. the other docs** — the split is what keeps any of them worth reading:

| File | Holds | Changes when |
|---|---|---|
| `CLAUDE.md` | Rules and invariants. Imperative, timeless. | A new way to break the system is found. |
| `docs/PATTERNS.md` | Recurring shapes and the failures they prevent. | The architecture changes. |
| `docs/TECHNICAL_DECISIONS.md` | Why each technology, and what was rejected. | A decision is revisited. |
| `docs/EPIC_*_PLAN.md` | What is planned and in what order. | Scope or sequencing moves. |
| `docs/IDEAS.md` | The parking lot — unscheduled ideas, and rejected ones with their reason. | Any time something occurs to you. |
| **`docs/MEMORY.md`** (this file) | **Where we actually are.** Standing directives, open questions, session log, measurements taken. | Every working session. |

If a fact is durable and imperative it belongs in `CLAUDE.md`, not here — this file is the
mutable part, and mixing the two means the rules get buried in changelog.

---

## Update protocol

Without this, the file rots into a stale snapshot that is worse than nothing, because it is
believed.

**At the end of a session that changed anything:**

1. Add a dated entry under **Session log** — newest first. What changed, and *why*, in a few
   lines. Link the commit.
2. Move anything resolved out of **Open questions**; add anything newly opened.
3. Update **Current state** if a phase's status moved.
4. Record any real **measurement** taken — a number measured once and written down is worth
   more than the same number re-derived approximately three times.
5. If a new invariant was discovered, put it in `CLAUDE.md` and note here that you did.

**Keep the log pruned.** Entries older than a few months whose content has been absorbed into
`CLAUDE.md` / `docs/TECHNICAL_DECISIONS.md` should be deleted, not archived — the pointer to the
durable doc is the useful residue.

**Do not** write anything into this file you have not verified. An unverified claim recorded
here is read as established fact by the next session, which is exactly the failure the "fail
loud" rule exists to prevent.

---

## Standing directives

Decisions the user has made that persist across sessions. Do not re-litigate these; if one
looks wrong, say so once and proceed.

- **Scale target: 10,000 tenants × 10 documents = 100,000 documents**, on 8 vCPU / 16 GB.
  Revised up from 1k × 2. Every capacity claim should be checked against this number.
- **Postgres is the only database engine.** No SQLite anywhere — not for tests, not for Epic
  3's checkpointer.
- **Python floor is 3.13**; Docker and CI run 3.14. The floor is what the code requires.
  Build the dev venv on 3.13 (`uv venv --python 3.13`) — pydantic fails to build models on
  3.14 pre-releases.
- **Never commit `.env`.** It holds a real LangSmith API key, and **this repository is
  public** — a key that reaches a commit is disclosed the moment it is pushed, whether or not
  the commit is later reverted. `.env.example` stays placeholders only.
- **Commit and push directly to `main`** (explicit permission; overrides the default branch
  restriction). Mirror the same commit to the working branch afterwards.
- Streamlit retires when the React UI lands (Epic 4 Phase 6). Don't invest in it beyond parity.
- Commit-signing warnings from the stop hook are expected and were accepted — signing cannot
  work in this container. Don't re-raise.

---

## Current state

**Built and verified:**

- **Epic 1** — retrieve → rerank → generate with citations, multi-format ingestion (Docling),
  structure-aware chunking, Qdrant + Postgres registry, Streamlit UI, full Docker stack.
- **Epic 4 Phase 1** — API-key auth, tenant scoping. Keys hashed at rest, shown once.
- **Epic 4 Phase 2** — per-tenant rate limiting. Redis sliding window, atomic via Lua, fails
  open.
- **Epic 4 Phase 3** — docs, health checks, CI.
- **Epic 4 Phase 5.1** — ingestion behind a procrastinate job queue. `POST /v1/documents`
  returns 202; document row and job commit in one transaction.
- **Explicit document scoping on `/ask`** — pulled forward out of Epic 2 because it fixed an
  observed defect rather than moving a metric. Naming a document by **filename or `doc_id`**
  scopes retrieval to it; an unowned identifier is a 404.

**Not built** — designs only, no code. Don't infer any of it from a plan's directory layout:

- **Epic 2** — the eval framework. Golden set, recall@k, parquet + DuckDB run storage, the CI
  regression gate, intent routing. This blocks most retrieval work: query expansion,
  decomposition, and corpus-level answering all change what retrieval returns, and adopting
  any of them without recall@k is a guess with a cost attached.
- **Epic 3** — the curation agent with human-in-the-loop.
- **Epic 4 Phase 4** — observability. The latency SLO check is buildable now; faithfulness
  alerting needs Epic 2's scores.
- **Epic 4 Phases 5.2–5.9** — user accounts, conversations, document delete, streaming `/ask`.
- **Epic 4 Phase 6** — React + TypeScript UI generated from the OpenAPI schema.

**Verified on real infrastructure:** `init_db` against live Postgres including the
advisory-lock path; the queued path end to end (`POST` → job row → worker → Qdrant →
`ingested`). **Still unverified:** the Qdrant client over the wire under concurrency, and the
nginx config's syntax (no nginx binary in the sandbox).

---

## Measurements taken

Numbers that were actually measured. Re-derive rather than trust if the system has changed
underneath them.

| What | Value | When / how |
|---|---|---|
| Cost of one `/ask` answer | **$0.017024** — 3,447 in + 1,013 out on `claude-sonnet-5` | 2026-08-01, from the LangSmith trace. Matches list price to the last digit at intro rates ($2/$10 per MTok, through 2026-08-31); **$0.025536 at standard $3/$15 from 2026-09-01**. |
| Output share of that cost | **60%**, from 23% of the tokens | Output is priced 5× input. Cost control means shorter answers, not smaller prompts. |
| Voyage cost per answer | **$0.00 billed** (~$0.0004 at list) | voyage-4 $0.06/1M and rerank-2.5 $0.05/1M, **first 200M tokens free on both** — pricing page fetched 2026-08-01. Query embed was 212 tokens. |
| Answer latency | 11.2 s | Same trace. |
| `max_tokens` headroom | **11 tokens of 1024** | `stop_reason: end_turn`, so it completed — but structured-output requests sit right against the ceiling. |
| Prompt caching viability | Not viable in current shape | Stable prefix is the 693-char system prompt (~200 tokens), under Sonnet 5's 1,024-token minimum. Chunks vary per question, so there is no larger shared prefix. |

---

## Open questions

Unresolved, and blocking or shaping something. Each needs a decision or a measurement, not
more discussion.

1. **Identity for Epic 4 Phase 5.2.** User accounts sit on top of the existing API-key tenant
   model, and the relationship between "tenant" and "user" hasn't been decided. Blocks 5.2
   onward.
2. **`processed_dir` disk footprint at 100k documents.** Still unmeasured — the attempt failed
   (Docling `partial_success`, 1/16 pages, fifteen timeouts on arXiv 2008.10896). Needs
   hardware that can finish a parse. Determines whether processed artefacts can stay on local
   disk at target scale.
3. **Payload index on `metadata.tenant_id`.** The vendored `qdrant-multitenancy` skill calls
   for a keyword index with `is_tenant=true`. Harmless at 6 documents; **required** at 100k
   (order 1M points, where an unindexed tenant filter degrades toward a scan). Not built.
4. **Usage is not recorded anywhere.** `answer_service.py` never reads `response.usage`, so the
   cost numbers above were only obtainable because LangSmith happened to be tracing — and that
   project is on the `shortlived` (14-day) tier. Epic 2 Phase 2.2's parquet schema already
   specifies `input_tokens` / `output_tokens` / `cost_usd`; capturing them on the `/ask` path
   is a smaller, independent step.
5. **Whole-document extraction.** "Fill this schema from document X" is not a similarity query
   — every field must be found, so ranking chunks against the schema text is the wrong
   primitive even when correctly scoped. Works today only because the test document is one
   chunk; on a longer document `rerank_top_n=5` would drop a field-bearing chunk and the model
   would answer `"unknown"` with no error. Recorded in `docs/EPIC_2_PLAN.md`; needs the golden set.

## Deferred, not dropped

Recorded so they stay visible: backups; a stuck-job sweeper (`updated_at` makes a dead worker's
`processing` row detectable, nothing sweeps it); `DELETE /v1/documents`; metrics; correlation
ids; RapidOCR cache-location verification.

---

## Session log

Newest first.

### 2026-08-01 — repo hygiene: templates, security workflows, pattern and memory docs

Added `.github/` issue forms (bug, feature) and a PR template, all written around this repo's
*silent* failure modes rather than generic prompts — the bug form asks for the pytest skip
count, the PR template's checklist is the tenant boundary and the re-ingestion delete step.

Added `.github/workflows/security.yml`: CodeQL (`security-extended`, scoped to
`portfolio/app|scripts|streamlit_app`) and a gitleaks history scan, both weekly on a schedule
plus on PR. Rationale: the existing pipeline audits *dependencies* and only fires on
`portfolio/**` changes, so a CVE disclosed against untouched code never surfaces, and nothing
looked at our own code or at committed credentials at all. `.gitleaks.toml` allowlists the
documented placeholders (`pf_live_...`, `KEY_PREFIX`, the deliberately-invalid
`sk-ant-something` test fixture) narrowly rather than by silencing directories.

Wrote `docs/PATTERNS.md` (19 patterns, each verified against source, each naming the failure it
prevents) and this file.

**Still to do by hand — I cannot set these:** enable **secret scanning + push protection** in
Settings → Code security. That is the control that stops a key landing; the gitleaks job only
catches what already did.

### 2026-08-01 — measured what an answer costs

Traced one real `/ask` to exact token counts. Findings in **Measurements** above; the
actionable ones are that output dominates cost 60/23, that the answer finished 11 tokens under
`max_tokens`, and that nothing in the codebase records usage (now Open question 4).

### 2026-08-01 — `doc_id` scoping ([`ae53c67`](https://github.com/stanimirdim92/llms/commit/ae53c67))

A question naming `doc_id=019fb3eb…` searched unscoped: the pre-check only looked for
filenames, returned `False`, and skipped the registry read. Four of five reranked chunks came
from the tenant's CV instead of the named advertisement — the question was mostly Pydantic
field descriptions, which embed closer to a CV's contact sections than to a sparse flyer.

Generalisable lesson, and the reason this is worth remembering: **the pre-check gates the
registry read, so any identifier it fails to recognise silently never scopes.** A `False` there
is indistinguishable from a question that named nothing.

`mentions_a_filename` → `mentions_a_document`. Two id spellings accepted: the bare
`{tenant_id}-{hash}` shape, and an explicit `doc_id=` marker — the latter because the curated
corpus uses bare arXiv ids like `2008.10896`, unmatchable on shape against prose.

### 2026-08-01 — filename scoping ([`36c8770`](https://github.com/stanimirdim92/llms/commit/36c8770))

Built `retrieval/document_scope.py`. No model call: the candidate set is the tenant's own
registry rows, so it is string matching against a closed set. Matching requires the full
filename *with extension* — bare stems would let a tenant owning `data.pdf` have "what data
does the study use?" silently narrowed to it.

Two bugs caught during this work, both the same shape — **code inserted between a decorator and
its function**. First, a helper placed under `@router.post` took the decorator, so `/v1/ask`
started returning `DocumentScope`; caught by diffing the generated OpenAPI. Then, inserting
tests between `@pytest.mark.usefixtures` and its function silently unauthenticated an existing
test; caught by the suite. Worth carrying forward as a review reflex.

### 2026-08-01 — redis image pinned, filename in chunk metadata ([`85ff4e2`](https://github.com/stanimirdim92/llms/commit/85ff4e2))

`filename` now rides in the chunk payload and leads the model-visible block title. The symptom
it fixed: the model summarising a document's contents while stating it had no document by that
name, because the only label it was given was a 65-character content hash.

**Consequence still outstanding:** points written before this change carry no `filename`.
Scoping still resolves them (via `doc_id`), but the model won't see the name and Streamlit's
chunk labels fall back to the hash. **A re-upload backfills it.**

### 2026-07-30 → 08-01 — earlier

Python floor 3.13 ([`2cfabbb`](https://github.com/stanimirdim92/llms/commit/2cfabbb)) — the
retarget surfaced a real crash-on-import in `Home.py` that `py314` had hidden behind PEP 649's
deferred annotations. Epic 2 and 3 plans written
([`eeb185f`](https://github.com/stanimirdim92/llms/commit/eeb185f)). Scale target and the
graph-DB verdict recorded ([`ad14a4e`](https://github.com/stanimirdim92/llms/commit/ad14a4e)) —
`microsoft/graphrag` was read closely; it uses no graph database (networkx in memory, parquet
on disk), and all 8 of its packages pin `requires-python <3.14`, so anything taken from it is
reimplemented rather than imported.
