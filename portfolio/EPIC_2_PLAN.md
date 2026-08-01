# Epic 2 — Eval framework: implementation plan

The original design is in `docs/IMPLEMENTATION_PLAN.md` (LangSmith datasets, RAGAS
evaluators, a CI threshold gate). That still holds. This file is the buildable plan,
plus everything learned since Epic 1 shipped — most of it from a real defect and from
reading `microsoft/graphrag`.

Nothing here is built except explicit document scoping (under Phase 2.0 below, shipped early
because it fixed a defect rather than a metric). Epic 1's answer path works and has never
been measured.

## Why this epic now blocks other work

Epic 2 was originally "prove the pipeline is good". It has become the prerequisite for a
queue of retrieval changes, because **none of them can be evaluated without it**. Query
expansion, decomposition, and corpus-level answering all change what comes back from
retrieval; without recall@k on a golden set, adopting them is a guess with a cost attached.

The one exception is the intent router (Phase 2.0 below), which fixes an observed defect
rather than improving a metric, and therefore does not need to wait.

## Phase 2.0 — Intent routing (unblocked, do first)

`/ask` currently answers every question the same way: retrieve top-k, rerank, generate.
That is correct for questions whose answer sits in a few passages and **structurally wrong
for two other classes**, one of which reached production:

| Question class | Example | Correct path |
|---|---|---|
| Metadata | "list my documents", "how many did I upload?" | `GET /v1/documents` — registry read, no retrieval, no model |
| Specific factual | "what electrolyte did they use?" | current retrieve → rerank → cite |
| Aggregate / thematic | "what themes run through my uploads?" | map-reduce over top-N documents (Phase 2.4) |
| Out of scope | "what's the weather?" | refuse, do not retrieve |

The observed failure: a user asked the system to list their documents and got a confident
answer grounded in five chunks from one document, four of which were figure captions
containing the vision model's "I'm not able to see the image" refusals. Two separate bugs
compounded there — the captions (fixed) and the routing (not fixed). Retrieval cannot answer
a metadata question, because the embedding of "list my documents" lands nearest whatever
chunk happens to be semantically adjacent. Adding documents does not fix it; the question
is not answerable from chunk content at all.

**Build:** a classifier returning one of four labels via structured output on Haiku 4.5
(a judgment call, so a model is right per rule 5 — but the routing it feeds stays plain
`if`/`else`). Sub-second, fractions of a cent, and cheaper than the retrieval it avoids on
metadata questions.

**Done when:** a metadata question returns registry data with no Qdrant call at all
(assert on a store spy, not on the answer text), an out-of-scope question is refused, and
the factual path is byte-identical to today's behaviour.

### Scoping a question to one named document — built, not planned

*"give me the contents of 3020072D.pdf"* is a factual question **restricted to one
document**, and it now works. It shipped ahead of the rest of this epic for the same reason
2.0 does: it fixes an observed defect rather than moving a metric, so it needed no recall
measurement to justify. Both halves are in:

- `filename` rides in the chunk payload and leads the block title the model reads
  (`answer_service._chunk_title`), so the model can match a name it is actually shown. The
  production symptom without it was a model summarising a document's contents while stating
  it had no document by that name — the only label it had was a content-hash `doc_id`.
- `app/retrieval/document_scope.py` reads filename-shaped tokens out of the question and
  resolves them against the caller's own registry rows; the resulting `doc_ids` become a
  `MatchAny` condition ANDed into `QdrantStore._build_filter`. A named document this tenant
  does not own is a 404 naming it, not a silent unfiltered search.

**Deliberately no model call** — the candidate set is a closed one (the tenant's own
documents), so it is string matching, per rule 5. Matching requires the full filename
*including extension*, which is what stops a tenant owning `data.pdf` having "what data does
the study use?" silently narrowed to that one file.

What is *not* built, and does belong behind measurement: **semantic** reference — "the
flyer", "my CV", "the German one". That needs a model, and it needs 2.3 to show the guessing
helps more than it hurts, since a wrong guess here produces a confident answer about the
wrong document with nothing in the response indicating it.

Two consequences to carry forward:

- Scoped retrieval currently reuses the same `top_k`. Within one document that is a much
  larger fraction of the available chunks, so the scoped path wants its own recall@k line in
  2.1's golden set rather than being assumed equivalent.
- If matching ever moves to filtering on `metadata.filename` directly instead of resolving to
  `doc_id` first, that field needs its own keyword payload index at the 10k x 10 target,
  exactly like `metadata.tenant_id` (`TECHNICAL_DECISIONS.md` § "Scale target"). Resolving
  through the registry avoids that today.

## Phase 2.1 — Golden set

50+ grounded Q&A pairs in `data/eval/qa_dataset.jsonl`, committed. Each pair carries the
question, an accepted answer, **the chunk ids that should be retrieved**, and the intent
label from 2.0 — so the same file evaluates routing accuracy and retrieval recall, not just
answer quality.

Do not machine-generate the whole set from the corpus. A set generated by the same model
family that answers the questions measures self-consistency, not correctness. Hand-write the
hard cases: table lookups, figure-grounded questions, questions whose answer spans two
documents, and questions the corpus genuinely cannot answer (the correct response is a
refusal, and a system that answers them anyway is the failure this catches).

Consult `.claude/skills/qdrant-search-quality` for golden-set and recall@k methodology
rather than inventing one.

## Phase 2.2 — Run storage: parquet + DuckDB

An eval run emits one row per (question × retrieved chunk):
`run_id, git_sha, question_id, intent_label, predicted_label, chunk_id, doc_id, rank,
vector_score, rerank_score, in_golden_set, judge_verdict, latency_ms, input_tokens,
output_tokens, cost_usd`.

Written to `data/eval/runs/<run_id>.parquet`. Analysis is DuckDB over
`data/eval/runs/*.parquet` — SQL across every run ever made, with no service, no table, and
no migration. `pyarrow` and `pandas` are already in `uv.lock` as Streamlit transitives with
`cp314` wheels, so this adds **no dependency**; DuckDB does need adding.

Why not Postgres: see `ARCHITECTURE.md` § 2b. Short version — this is append-only
analytical data with an evolving schema, and the CI gate needs a *committed* baseline it can
diff in a pull request, which a database row cannot provide.

Why not only LangSmith: LangSmith holds traces and hosted experiment comparison and stays
in the loop for interactive exploration. It is a network call to a hosted service, and the
regression gate must work offline and in version control. Both, for different jobs.

## Phase 2.3 — Metrics and the CI gate

RAGAS metrics (faithfulness, answer relevancy, context precision/recall) wrapped as
LangSmith custom evaluators, plus two that RAGAS does not cover and that this system needs:

- **recall@k against the golden chunk ids** — the only metric that isolates *retrieval*
  from generation, and therefore the only one that can attribute a bad answer to the right
  half of the pipeline.
- **routing accuracy** from 2.0's labels — a confusion matrix, because misrouting a
  metadata question to retrieval is precisely the production defect.

A deliberate "before" baseline first: naive fixed-size chunking, no reranker. Without it
every later number is unanchored.

`data/eval/baseline.parquet` is committed and is what CI compares against. The gate fails
the build on regression beyond a stated tolerance, and the failure names *which metric on
which question class* moved — a gate that only says "eval failed" gets disabled within a
month.

**Done when:** a deliberately broken change (drop the reranker) is caught by CI, and the
failure output identifies the reranker as the cause rather than reporting a lower aggregate.

## Phase 2.4 — Corpus-level answering (measured, not assumed)

The `aggregate` branch from 2.0. Design taken from `microsoft/graphrag`'s global search,
with three of its four components replaced by parts this system already has — see
`TECHNICAL_DECISIONS.md` § "Graph RAG" for the source reading and the licence position.

| Step | GraphRAG | Here |
|---|---|---|
| Candidate selection | map over the **whole** corpus | vector search → top-N **documents**; O(N≈15), not O(100k) |
| Scoring | ask the map model for a 0–100 importance score | Voyage rerank scores — purpose-built, batched, better calibrated, already paid for |
| Grounding | model *types* `[Data: Reports (2, 7)]`, nothing verifies it | Anthropic Citations API — verified source spans, already in use |
| Budget overflow | silent `break` | log the drop count, per rule 7 |

Kept verbatim, because it is right: **when no candidate scores above the floor, return a
canned "no data" answer instead of synthesising from weak material.** That is the same
principle as dropping unusable figure captions, reached independently by both codebases.

**Done when** it beats the current single-pass path on aggregate-class golden questions
*and* leaves factual-class scores unchanged. If it does not, it does not ship — which is the
entire reason it comes after 2.3.

## Phase 2.5 — Retrieval techniques, in priority order

All of these are measured through 2.3 or they do not land.

1. **Dynamic prompt assembly** — deterministic, no model call: table-reading guidance only
   when a table chunk survived reranking, figure guidance only when a figure chunk did.
   Plain `if`/`else` per rule 5.
   **Trap worth naming:** prompt caching is a *prefix* match. Variable content assembled at
   the front of the system prompt invalidates the cache on every request and silently pays
   full input price. Stable prefix first, variable content last, after the final breakpoint.
2. **Query expansion** (HyDE or n paraphrases → embed each → union → rerank the union) —
   for vocabulary mismatch, which is constant in scientific text: "does NMC degrade?" versus
   "capacity fade in LiNi₀.₈Mn₀.₁Co₀.₁O₂". Measured by recall@k; it either moves that number
   or it is dropped.
3. **Query decomposition** — "compare X and Y" produces one embedding that averages both
   and matches neither. Splitting fixes it, at n× retrieval plus a synthesis step, so gate
   it behind 2.0's classifier rather than running it on every question.

## Not in this epic

- **Auto prompt tuning** (graphrag's `prompt-tune`: generate extraction prompts from a
  corpus sample). Relevant — it is the systematic version of the fix applied to the figure
  caption prompt by hand — but it needs the eval harness to show a generated prompt beats a
  written one. Revisit after 2.3.
- **Anything O(corpus) per query.** At 100k documents a model call per document is 100k
  calls. See `TECHNICAL_DECISIONS.md` § "Scale target".

## Dependencies

| Package | Phase | For |
|---|---|---|
| `ragas` | 2.3 | Faithfulness / relevancy / context metrics |
| `duckdb` | 2.2 | SQL over the parquet run files |
| `pyarrow` | 2.2 | **Already in `uv.lock`** via Streamlit — no add needed |
