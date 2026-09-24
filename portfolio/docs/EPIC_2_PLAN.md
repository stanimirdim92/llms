# Epic 2 — Eval framework: implementation plan

The original design is in `docs/IMPLEMENTATION_PLAN.md` (LangSmith datasets, RAGAS
evaluators, a CI threshold gate). That still holds. This file is the buildable plan,
plus everything learned since Epic 1 shipped — most of it from a real defect and from
reading `microsoft/graphrag`.

Built: Phase 2.0 in full (intent routing and explicit document scoping, both shipped early
because each fixed a defect rather than moved a metric) and Phase 2.1 (the pinned corpus and a
67-pair golden set). Nothing scores anything yet -- that is 2.2 and 2.3, now built on
LangSmith datasets and experiments -- so Epic 1's answer path works and has never been measured.

## Why this epic now blocks other work

Epic 2 was originally "prove the pipeline is good". It has become the prerequisite for a
queue of retrieval changes, because **none of them can be evaluated without it**. Query
expansion, decomposition, and corpus-level answering all change what comes back from
retrieval; without recall@k on a golden set, adopting them is a guess with a cost attached.

The one exception is the intent router (Phase 2.0 below), which fixes an observed defect
rather than improving a metric, and therefore does not need to wait.

## Phase 2.0 — Intent routing (built)

`/ask` used to answer every question the same way: retrieve top-k, rerank, generate.
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

**Built:** a classifier returning one of four labels via structured output on Haiku 4.5
(`app/generation/intent_router.py` -- a judgment call, so a model is right per rule 5, but the
routing it feeds is plain `if`/`match` in `app/api/routers/ask.py`). Sub-second, fractions of a
cent, and cheaper than the retrieval it avoids on metadata questions.

**Done when:** a metadata question returns registry data with no Qdrant call at all
(assert on a store spy, not on the answer text), an out-of-scope question is refused, and
the factual path is byte-identical to today's behaviour. All three verified in
`tests/unit/test_intent_routing.py`. `aggregate` refuses with an explicit "not supported yet"
rather than falling through to the factual pipeline -- its real answer path is Phase 2.4 below,
which needs recall@k over Phase 2.1's golden set (Phase 2.3) before it can be measured.

### Scoping a question to one named document — built, not planned

*"give me the contents of 3020072D.pdf"* is a factual question **restricted to one
document**, and it now works. It shipped ahead of the rest of this epic for the same reason
2.0 does: it fixes an observed defect rather than moving a metric, so it needed no recall
measurement to justify. Both halves are in:

- `filename` rides in the chunk payload and leads the block title the model reads
  (`answer_service._chunk_title`), so the model can match a name it is actually shown. The
  production symptom without it was a model summarising a document's contents while stating
  it had no document by that name — the only label it had was a content-hash `doc_id`.
- `app/retrieval/document_scope.py` reads filename- *and* `doc_id`-shaped tokens out of the
  question and resolves them against the caller's own registry rows; the resulting `doc_ids`
  become a `MatchAny` condition ANDed into `QdrantStore._build_filter`. A named document this
  tenant does not own is a 404 naming it, not a silent unfiltered search.

  Filenames-only was the first cut and it shipped with a hole: a user who pasted
  `doc_id=019fb3eb…` — the identifier the API itself hands back — matched nothing, so the
  pre-check returned `False` and the search ran unscoped. Four of the five chunks that won
  reranking came from that tenant's CV rather than the named advertisement, because the
  question was mostly Pydantic field descriptions ("The name of the company or entity") and
  those embed closer to a CV's contact and profile sections than to a sparse one-page flyer.
  Both identifiers are now accepted. The lesson generalises past this fix: **the pre-check
  gates the registry read, so any identifier it fails to recognise silently never scopes** —
  a `False` there is indistinguishable from a question that named nothing.

**Deliberately no model call** — the candidate set is a closed one (the tenant's own
documents), so it is string matching, per rule 5. Matching requires the full filename
*including extension*, which is what stops a tenant owning `data.pdf` having "what data does
the study use?" silently narrowed to that one file.

What is *not* built, and does belong behind measurement: **semantic** reference — "the
flyer", "my CV", "the German one". That needs a model, and it needs 2.3 to show the guessing
helps more than it hurts, since a wrong guess here produces a confident answer about the
wrong document with nothing in the response indicating it.

Three consequences to carry forward:

- **A schema is not a search query, and scoping alone does not fix that.** "Return this
  Pydantic model, filled in from document X" is a *whole-document extraction* request: every
  field has to be found, so ranking chunks by similarity to the schema text is the wrong
  primitive even once the search is correctly narrowed. It worked in the observed case only
  because the flyer is a single chunk. On a multi-chunk document, `rerank_top_n=5` would
  silently drop the chunk holding one of the requested fields and the model would fill it with
  `"unknown"` — a wrong answer with no error, and one the user cannot distinguish from the
  field genuinely being absent. A scoped question whose `doc_ids` resolve to one document
  should bypass ranking and pass **that document's chunks in document order**, up to the
  context budget. That belongs with 2.4's corpus-level work (same map-reduce machinery, one
  document instead of N) and needs recall@k over 2.1's golden set to prove it, so it is not
  built here.
- Scoped retrieval currently reuses the same `top_k`. Within one document that is a much
  larger fraction of the available chunks, so the scoped path wants its own recall@k line in
  2.1's golden set rather than being assumed equivalent.
- If matching ever moves to filtering on `metadata.filename` directly instead of resolving to
  `doc_id` first, that field needs its own keyword payload index at the 10k x 10 target,
  exactly like `metadata.tenant_id` (`docs/TECHNICAL_DECISIONS.md` § "Scale target"). Resolving
  through the registry avoids that today.

## Phase 2.1 — Golden set

**Built (2026-09-17): the corpus, seeded through the real pipeline, and the golden set.**

### The corpus

Six 2026 arXiv papers on retrieval-augmented generation — evaluation, robustness under document
poisoning, citation grounding, context efficiency, multi-agent graph RAG — pinned in
`data/eval/corpus_manifest.json` by **versioned** arXiv id and sha256, plus the **seed tenant
id**, which is pinned rather than minted because `upload_doc_id` salts the content digest with it
and every chunk id is therefore a function of it. The PDFs are not committed;
`scripts/fetch_eval_corpus.py` fetches and verifies them and refuses to write bytes that do not
match.

**This replaced a first attempt that used the wrong six papers.** The lithium-ion cathode set was
the *demo* corpus removed with the `global` tenant in August; rebuilding it was rebuilding a
decision that had already been reversed. It was also a poor fixture on its own terms: subscripted
chemical formulas did not survive Docling — the review's component list parses as "It consists of
4 ), anode" where the source reads LiCoO2 — so a whole class of question was unanswerable for
reasons that had nothing to do with retrieval.

### The chunk manifest comes out of the store, not out of a re-parse

`scripts/seed_eval_corpus.py` ingests each paper through **`ingest_document`** — the same
function the worker and Streamlit call, with the same helpers in the same order — and then reads
the chunk manifest back out of Qdrant, filtered on `list_active_versions` exactly as
`Retriever.retrieve` is. **What retrieval can see is what a golden reference is allowed to name.**

The first version of this was an offline parse-and-chunk that never touched Qdrant, Voyage or
Postgres, and it was wrong in a way that would have been invisible: it called
`chunk_document(..., figures=[])`, so its manifest carried no figure chunks and did not describe
what the system actually indexes. A fixture that is *nearly* the real chunk set is worse than no
fixture, because recall@k measured against it reads as a property of retrieval. Deleted rather
than patched — a second parse implementation is the thing to remove, not to fix.

One property this makes explicit rather than dodging: **figure chunks are real but not
reproducible.** A figure chunk exists only if the vision model returned a caption
`figure_extractor` did not reject as unusable, so a re-ingest can legitimately produce a
different set. `--check` reports that as drift like any other, and a golden pair citing a figure
chunk has to be re-checked when it does.

### The golden set

**Built: `data/eval/qa_dataset.jsonl`, 67 hand-written pairs.** Each carries the question, an
accepted answer, the intent label from 2.0, `answerable`, the chunk ids that should be retrieved
**and the sha256 of each of those chunks when the pair was written**.

By intent: 59 `factual`, 3 `metadata`, 3 `out_of_scope`, 2 `aggregate`. By class: 40 prose, 7
table lookups, **6 figure-grounded**, 3 cross-document, 3 unanswerable, 3 registry, 3 refusal, 2
corpus-level.

The six figure pairs are the ones that could not have existed a day earlier, and they are worth
naming: a figure's caption is its only searchable text, so they are the only pairs that measure
whether captioning works at all.

None of it was machine-generated. A set generated by the same model family that answers the
questions measures self-consistency, not correctness; the hard classes are exactly the ones such
a set does not produce, so `tests/unit/test_qa_dataset.py` asserts each is present rather than
trusting the total.

That file is the other half: twelve checks, two mutation-confirmed red -- every golden chunk id
resolves against `chunk_manifest.json`, and every cited chunk still hashes to what the pair
recorded. **What it cannot check, stated in the file too:** that an id is the *right* one. A pair
citing `-text-0009` where `-text-0003` holds the answer passes everything and surfaces only as
one stubbornly low score in the first eval run. Grounding was checked at authoring time against
the full chunk text -- all 67 pairs, every number in every answer found in the chunks it cites --
and that check cannot be committed, because `data/eval/chunk_text/` is derived from the papers.

**Figure pairs can inherit a vision misread, and the chunk check can't see it.** Found
2026-09-24: q013 said SelCtx's overhead was 59 ms, grounded in the 09-17 caption, but the PDF's own
figure text reads 593 ms, and the chart has five methods, not four. The check above confirms an
answer against its *cited chunk*; for a figure that chunk is a model's caption, so a misread
passes. When a figure pair is written or re-checked, confirm it against the PDF's text layer
where the figure carries text (`pypdfium2` reads it), not the caption alone.

One pair earns a note of its own. *"What is retrieval-augmented generation, in general?"* is
labelled `out_of_scope` even though the corpus is entirely about RAG. It is the adversarial case
for the 2026-09-17 prompt fix, which told the classifier to read an unfamiliar specific term as
evidence *for* `factual`: this pair is what stops that correction sliding into "everything is
factual". Verified live -- still `out_of_scope` after the change.

Consult the `qdrant:qdrant-search-quality` plugin skill for recall@k methodology rather than inventing
one; `ranx` is what it names for scoring, and **nothing scores anything yet** -- that is 2.3.

## Phase 2.2 — Datasets and experiments in LangSmith

**Replaced 2026-09-24.** This phase was a local run store: one parquet row per question ×
retrieved chunk, queried with DuckDB. The user decided evals and datasets live in **LangSmith**
instead, so there is no local run store to build. The reasoning, and what was given up, is in
`docs/TECHNICAL_DECISIONS.md` § "Evals: LangSmith datasets and experiments".

- **The golden set stays in git.** `qa_dataset.jsonl` is authoritative. A sync script copies it
  into a LangSmith dataset, tagged with the git sha. Datasets have indefinite retention.
- **A run is a LangSmith experiment.** `aevaluate()` runs an eval target (the real `/ask`
  pipeline) over the dataset. Per-example outputs replace the parquet row: predicted intent,
  ranked chunk ids, answer, citations, latency, tokens. Experiment runs get extended retention
  by default; the docs say 180 days and the pricing page says 400, so that's unresolved.
- **The gate's baseline is a committed file**, `data/eval/baseline_scores.json` (summary score
  per metric × question class), so a regression is still a diff in the pull request.
- **The gate can still run offline.** The installed SDK's `aevaluate` takes
  `upload_results=False` and local `Example`s built from `qa_dataset.jsonl`. With recorded
  provider calls, CI would need neither LangSmith nor provider keys. That's not yet run;
  it's the first checkpoint in `docs/tasks/EPIC2-P3-eval-gate-plan.md`.

The local-store version's plan and tasks are kept, marked retired, in
`docs/tasks/EPIC2-P2-run-storage-*.md`. Its `cost_usd` price-table decision (`docs/MEMORY.md`
open question 5) applies only if LangSmith's own trace cost turns out not to be enough.

## Phase 2.3 — Metrics and the CI gate

LLM-judged answer quality, as LangSmith evaluators: **correctness** against the accepted answer and
**groundedness** in the retrieved chunks (`app/eval/judges.py`, Claude with structured output). This
was "RAGAS metrics" until 2026-09-24. `ragas` was dropped because it downgrades `fsspec`, `jiter` and
`rich` and adds `nest-asyncio` (see `docs/TECHNICAL_DECISIONS.md`). Plus the metrics no judge covers,
which are our own code:

- **recall@k against the golden chunk ids** — the only metric that isolates *retrieval*
  from generation, and therefore the only one that can attribute a bad answer to the right
  half of the pipeline.
- **routing accuracy** from 2.0's labels — a confusion matrix, because misrouting a
  metadata question to retrieval is precisely the production defect.
- **nDCG@k / MRR against the same golden chunk ids** — recall@k answers "was the right chunk
  retrieved at all"; these answer "how high did it rank", which is specifically what
  `rerank-2.5` is paid for. Without a rank-sensitive metric, a reranker regression that still
  keeps the right chunk somewhere in the top-k is invisible to recall@k alone.
- **Citation success rate** — distinct from the groundedness judge (which scores the generated
  *text* against retrieved context): this checks whether `_extract_citations` actually
  resolves a citation to a real, in-range chunk for every factual claim in a golden answer.
  The unit-level guards already exist (`test_an_out_of_range_document_index_is_dropped_not_raised`,
  `test_a_negative_document_index_does_not_wrap_around_to_the_last_document` in
  `test_answer_extraction.py`); this is the dataset-level rate those guards don't measure —
  what fraction of golden questions come back with every claim actually grounded, not just
  whether the Citations API returned *something*.

The baseline is **today's pipeline as it ships**, recorded once. Without it every later number
is unanchored. (This originally asked for a "naive fixed-size chunking, no reranker" baseline;
see below for why that was dropped.)

`data/eval/baseline_scores.json` is committed and is what CI compares against (it was
`baseline.parquet` before the 2026-09-24 LangSmith decision). The gate fails the build on
regression beyond a stated tolerance, and the failure names *which metric on which question
class* moved — a gate that only says "eval failed" gets disabled within a month.

A naive-chunking baseline can't be scored by recall@k against the golden set: every golden
`chunk_id` is an id of the real chunker's output, and a re-chunked corpus has different ids.
**Resolved 2026-09-24 (user):** the baseline is today's pipeline as it ships, real chunker and reranker included. No naive-chunking run, no no-reranker experiment, and no reranker score used as a metric (the reranker is part of the system under test, so it can't grade itself).

**Done when:** a deliberately broken change (the reranker removed, on a throwaway branch
only) is caught by CI, and the failure output points at the rank-sensitive metrics rather
than reporting a lower aggregate. This tests the gate; it is not a baseline and ships nowhere.

## Phase 2.4 — Corpus-level answering (measured, not assumed)

The `aggregate` branch from 2.0. Design taken from `microsoft/graphrag`'s global search,
with three of its four components replaced by parts this system already has — see
`docs/TECHNICAL_DECISIONS.md` § "Graph RAG" for the source reading and the licence position.

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
2. **Query expansion / query rewriting** (HyDE or n paraphrases → embed each → union → rerank
   the union) — for vocabulary mismatch, which is constant in scientific text: "does NMC
   degrade?" versus "capacity fade in LiNi₀.₈Mn₀.₁Co₀.₁O₂". Measured by recall@k; it either
   moves that number or it is dropped.
3. **Query decomposition** — "compare X and Y" produces one embedding that averages both
   and matches neither. Splitting fixes it, at n× retrieval plus a synthesis step, so gate
   it behind 2.0's classifier rather than running it on every question.

## Not in this epic

- **Auto prompt tuning** (graphrag's `prompt-tune`: generate extraction prompts from a
  corpus sample). Relevant — it is the systematic version of the fix applied to the figure
  caption prompt by hand — but it needs the eval harness to show a generated prompt beats a
  written one. Revisit after 2.3.
- **Anything O(corpus) per query.** At 100k documents a model call per document is 100k
  calls. See `docs/TECHNICAL_DECISIONS.md` § "Scale target".

## Dependencies

| Package | Phase | For |
|---|---|---|
| `vcrpy` | 2.3 | Record provider calls once, replay them in CI |
