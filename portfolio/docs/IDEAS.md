# Ideas

A parking lot. Anything that might be worth doing but isn't scheduled — so it stops occupying
working memory and stops getting re-discovered from scratch every few sessions.

**This is not a roadmap.** `docs/EPIC_*_PLAN.md` holds what we intend to build, in order.
Everything here is unjudged: some of it is good, some will turn out to be wrong, and a few
entries exist mainly so nobody spends an afternoon re-deriving why they were dropped.

## How to use it

- **Add freely, in one line if that's all you have.** A half-formed idea recorded beats a good
  one forgotten. Better one line today than a paragraph never written.
- **Say what makes it worth doing**, not just what it is. "Add caching" is unactionable in six
  weeks; "answers repeat across tenants, so a semantic cache could cut model spend" is.
- **When an idea graduates**, move it into the relevant `EPIC_*_PLAN.md` and delete it here.
  Two copies immediately disagree.
- **When an idea is rejected**, move it to *Considered and rejected* with the reason. That
  section is the one that saves the most time — an idea with no recorded verdict comes back.
- Sizes are gut-feel: **S** hours, **M** a day or two, **L** longer. They exist to make the
  cheap-and-valuable entries easy to spot, not as estimates.

---

## Retrieval and answer quality

- **Whole-document mode for scoped questions.** *(M, blocked on the golden set)* When
  `doc_ids` resolves to one document, pass that document's chunks **in order** up to the
  context budget instead of ranking them. Schema-filling and summarisation need every chunk,
  not the top 5 — today a field-bearing chunk can be silently dropped and the model answers
  `"unknown"` with no error. Detail in `docs/EPIC_2_PLAN.md`.
- **Cache the query embedding.** *(S)* Identical questions re-embed every time. A small
  content-keyed cache is nearly free and cuts one network round-trip from the hot path.
- **Semantic answer cache.** *(M)* Cache answers keyed on the embedding, returning a hit above
  a similarity threshold. Real money at the target scale, but the failure mode is nasty:
  serving a stale answer after a re-upload. Needs invalidation on `doc_id` before it is safe.
- **Show retrieved chunks in the API response by default.** *(S)* Already returned; worth
  surfacing prominently in clients — a wrong answer is diagnosable in seconds when you can see
  what it read. **Not universal agreement, recorded rather than resolved (rule 6):** the
  2026-08-10 review treats the same behaviour as a cost/exposure problem — every reranked
  chunk's full text ships on every answer whether cited or not, with no
  `include_retrieved_chunks=false` to opt out, so payload size and document-content exposure
  both scale with `rerank_top_n`. Diagnosability and exposure are the same design decision seen
  from two threat models; worth an explicit opt-out flag (default on while this stays
  single-tenant-dev, revisit the default once monetization means a real customer's documents
  are behind it) rather than picking one side now.
- **Hybrid search (BM25 + dense).** *(M)* Exact identifiers, model numbers, and chemical
  formulae are where pure dense retrieval is weakest, and this corpus is full of them. Qdrant
  supports sparse vectors natively. Measure first.
- **Per-document-type chunking.** *(M)* A CV, a one-page flyer, and a 30-page paper currently
  share one strategy. The flyer becoming a single chunk was luck, not design.
- **Chunk-size tokenizer doesn't match the embedding provider.** *(S)* `app/ingestion/chunker.py`
  measures `chunk_max_tokens` (default 700) with `sentence-transformers/all-MiniLM-L6-v2`'s
  tokenizer, while embedding runs through Voyage `voyage-4`. Nothing connects the two token
  spaces, so 700 is a guess about what fits, not a measured one. Use a Voyage-compatible
  tokenizer or count against Voyage's own token-counting API.
- **No token cap on a table chunk.** *(S)* The table-chunking path in `chunker.py` serializes a
  whole table to Markdown as one chunk with no size limit — a large XLSX/CSV upload can produce
  an oversized embedding input, reranker input, and generation block in one step. `Settings` has
  no `table_max_tokens` field at all.
- **Chunk `page_no` is a single value, not a range.** *(S)* `chunker.py` takes
  `doc_items[0].prov[0].page_no` — the first item's first provenance page — even though a
  contextualised chunk can span several `doc_items` and several pages. Citations therefore name
  one page for content that may start elsewhere. Needs `page_start`/`page_end` (or a `pages`
  list) instead of one scalar.
- **Neither content cache carries a version.** *(S)* The figure-caption cache key
  (`caption-<sha256 of image bytes>.txt`, `figure_extractor.py`) and the parsed-document cache
  key (`processed_dir/<doc_id>.json`, `pipeline.py`) are both keyed on content/id alone — neither
  includes the caption prompt, the caption model, or the Docling/parser version. Changing the
  prompt, the vision model, or upgrading Docling therefore keeps serving cache entries produced
  under the old settings, indefinitely, with nothing to invalidate them. Fix is a fingerprint
  (`hash(source_digest, docling_version, parser_options)` / `hash(image_digest, model,
  prompt_version)`) folded into each cache path.

## Model providers

- **Pluggable generation provider: OpenAI and Ollama alongside Anthropic.** *(M)* Three
  reasons, in order of weight. Ollama makes the whole stack runnable with **no API keys and
  no spend** — a reviewer can clone and run it, which is worth more for a portfolio than any
  README claim. OpenAI is the comparison anyone will ask for, and Epic 2's eval harness makes
  "which model answers this corpus best" a measurable question rather than a preference.
  Third, one-provider-only is a single point of failure.
  The shape: a `generation_provider` setting selecting a factory, since `AnswerService`
  already talks to a LangChain chat model and `langchain-openai`/`langchain-ollama` are
  drop-in. What is *not* drop-in is the citation path — see the next entry, which is a
  blocker, not a footnote. Three other Anthropic touchpoints have to be decided too rather
  than discovered later: `figure_extractor`'s **vision captioning** (a figure's caption is
  its only searchable text, so a weaker vision model degrades retrieval silently),
  `require_provider_credentials` at boot, and the cost accounting, which currently assumes
  one price table.
- **A citation mechanism that does not depend on Anthropic's Citations API.** *(L, blocks the
  entry above)* This is the real cost of going multi-provider, and it is easy to
  underestimate. Today `_build_document_blocks` sends each chunk as a `document` block with
  `citations: {enabled: True}` and the API returns `cited_text` spans **the model did not
  author** — they are extracted from the source, so a citation cannot be hallucinated. That
  guarantee is the product. Neither OpenAI nor Ollama has an equivalent, so a naive port
  produces model-written quotes that look identical and are occasionally fabricated: strictly
  worse than no citations, because it is a wrong answer wearing evidence.
  Options, cheapest first: (a) ask for chunk indices only (`[3]`, never prose), then resolve
  each index to real chunk text ourselves — the model chooses *which*, never *what*, so
  nothing quoted can be invented, and an out-of-range index is a detectable failure;
  (b) ask for verbatim quotes and **verify** each against the chunk it claims, dropping any
  that do not match; (c) post-hoc attribution, embedding each answer sentence against the
  retrieved chunks. (a) is the honest floor and probably where to start. Whatever ships must
  keep `Citation(quoted_text, chunk_id, doc_id, page_no)` intact, since it is the API
  contract, and should record which mechanism produced it so a consumer can tell an extracted
  span from a verified one. Epic 2's eval set is what makes the comparison measurable.

## Cost and performance

- **Raise `max_tokens` above 1024, or stream.** *(S, now measurable)* One measured answer
  finished **11 tokens** under the ceiling. Truncation is no longer silent — `stop_reason` and
  the token counts are logged on every answer, `Answer.truncated` reaches `AskResponse`, and
  Streamlit warns — so the missing input is now a *rate*: watch `answer_service.truncated` for a
  while and raise the ceiling against real numbers rather than one anecdote. Raising it blind
  costs money on every answer to fix a fraction of them.
  (The "record token usage per answer" entry that sat here has shipped, so it is gone.)
- **Cheaper model for figure captions.** *(S)* Captioning uses the same model as answering.
  It is a bounded describe-this-image task; Haiku may be indistinguishable at a fifth the cost.
  Measurable against a handful of figures without any eval harness.
- **Batch API for corpus ingestion.** *(M)* Anthropic's Batches API is 50% off and ingestion is
  not latency-sensitive. Fits the worker model exactly.
- **Fast mode for interactive `/ask`.** *(S)* Opus-tier only and premium-priced, so probably
  wrong for this workload — noted so the question isn't reopened without the numbers.

## Scale — toward 10k tenants × 10 documents

- ~~**Payload index on `metadata.tenant_id` with `is_tenant=true`.**~~ **Done 2026-08-03**
  (`qdrant_store._ensure_payload_indexes`), verified against a real `qdrant/qdrant:v1.18.3`
  container. Delete this line at the next prune.
- **The `m=0` + `payload_m` trade for per-tenant HNSW graphs.** *(M, conditional — probably
  never)* `qdrant-scaling` offers it when indexing throughput becomes the bottleneck: build no
  global HNSW graph, only per-tenant ones. Recorded with its precondition because it is easy to
  cargo-cult from the docs. **One half of the precondition now holds and the other still does
  not.** The trade needs indexing throughput to be the bottleneck *and* cross-tenant search to be
  rare; removing the shared corpus (2026-08-03) made every query single-tenant, so cross-tenant
  search is now not merely rare but **impossible** — `_build_filter` matches exactly one tenant.
  What still blocks it is that **nothing measures Qdrant's indexing throughput**, so there is no
  evidence it is the bottleneck. Revisit only with that measurement in hand; the previous note
  here said both halves failed, which stopped being true the day the corpus went.
- **Quantization.** *(M)* Scalar or binary quantization on the collection, to keep the working
  set in RAM at 16 GB. Costs recall; the `qdrant-performance-optimization` skill has the
  tradeoff. Needs recall@k to evaluate honestly.
- **Measure `processed_dir` growth.** *(S)* Still unmeasured — the attempt died on Docling
  timeouts. Determines whether processed artefacts can stay on local disk at target scale.
- **Object storage for uploads.** *(L)* Local disk doesn't survive a multi-instance deployment.
  Not needed until there is more than one api host.
- ~~**Shorten the rate-limit ZSET member.**~~ **Done differently, same day it was written.**
  The measurement that prompted it (3120 bytes per key for 60 requests, against 120 for
  `limits`' counter) turned into the argument for adopting `limits` outright rather than
  optimising ours — so there is no ZSET left to shrink. Kept as a struck-through line for one
  reason: this entry was stale within the hour, which is the failure mode the doc split exists
  to prevent. Delete this line at the next prune.
  (And the follow-on: the 120-bytes-per-key figure that briefly replaced it was the *counter*
  strategy, which was itself replaced hours later for not honouring its own `Retry-After`. Actual
  per-key cost is **1464 bytes**, ~29 MB at 10k tenants × 2 scopes. Two stale numbers from one
  measurement, which is the real lesson here.)

## Security and privacy

- **The raw question is logged on every answer.** *(S)* `answer_service.py` logs
  `question=question` on both the normal `answer_service.answered` line and the
  `answer_service.truncated` warning, alongside `tenant_id`. A question can contain pasted
  contract text, a name, an account number — anything a user typed. Not currently a documented
  policy either way; log a correlation id and a question hash by default and gate raw-text
  logging (or LangSmith tracing, which can capture the same content) behind an explicit setting.
- **Worker exceptions reach the client verbatim.** *(S)* `tasks.py` writes
  `error=f"{type(exc).__name__}: {exc}"` to `DocumentRecord.error_message`, and both
  `GET /v1/documents` and `GET /v1/documents/{doc_id}` return that string unmodified. A Docling,
  Anthropic, Voyage, or Qdrant exception message can include a local path or library internals.
  Split into a stable `error_code` for the client and the raw exception for logs only.
- **Upload acceptance checks the filename suffix, not the bytes.** *(S)* `formats.py`'s
  `is_supported_upload` is a suffix match; nothing inspects the actual content (no
  magic-byte/MIME sniffing) before a file reaches Docling in the worker. The worker is non-root
  and isolated, which bounds the blast radius, but a mismatched suffix still buys a full parse
  attempt on untrusted bytes for free.

## Developer experience

- **`make` or `just` targets.** *(S)* The verify gate is four commands and the stack invocation
  needs `--env-file` or it silently uses fallbacks. One `just verify` and one `just up` removes
  a whole class of "it worked on my machine".
- **Devcontainer.** *(M)* Encodes the 3.13-floor / 3.14-runtime split so a fresh clone can't
  build the venv on a pre-release interpreter and hit the pydantic failure.
- **A seeded demo tenant.** *(S)* One command producing a key plus ingested corpus, so the
  stack is explorable within a minute of `docker compose up`.
- **Trivy image scanning in CI.** *(S)* Dependency CVEs are covered and Dependabot bumps the
  pinned bases, but nothing reports CVEs in those images *between* bumps.
- **Pin GitHub Actions to commit SHAs.** *(S)* Tags are mutable. Dependabot understands SHA
  pins and keeps them current. Supply-chain hardening, cheap.
- **LangGraph, its Postgres checkpoint package, and `langchain-openai` ship in the main
  dependency group.** *(S)* All three are Epic 3 packages and Epic 3 isn't built; the Dockerfile
  runs `uv sync --locked` with no `--extra`, so all three reach the api/worker/streamlit image
  today for zero runtime use. Moving them into an `agent` extra (alongside the existing `eval`
  extra idea) shrinks the image and the CVE surface with nothing importing them yet to break.
- **`pip-audit` runs via `uvx`, not the locked version.** *(S)* It's declared under
  `[project.optional-dependencies].dev` in `pyproject.toml`, but CI invokes
  `uvx pip-audit -r ... --disable-pip`, which resolves its own environment independently of
  `uv.lock` — so CI can audit a different scanner version than the one pinned locally.
  `uv run pip-audit` would use the locked one; the dev-docs comment claiming it's "the same
  command CI runs" is not quite accurate today.

## Auth

- **A sweep for keys about to lapse.** *(S)* `expires_at` exists and is enforced, but nothing
  warns before the deadline -- the first signal is a 401 in production. `expires_at` is
  indexed for exactly this query; a cron and an email is the whole feature.
- **A Redis-outage fallback for the limiter.** *(S)* Today an unreachable Redis fails open —
  no protection at all, loudly logged. `limits` ships a `MemoryStorage` that could back the same
  idea, and `slowapi` wires it as an `in_memory_fallback` that degrades to
  per-process counters instead, which is partial protection rather than none. With
  `GUNICORN_WORKERS` processes the effective limit becomes `workers x limit`, so it is a
  guardrail not a guarantee — but it is strictly better than nothing during exactly the
  incident where load may be why Redis is struggling.
- **The rate limiter's fail-open catch is a bare `Exception`, not a Redis-specific one.**
  *(S)* `app/rate_limit.py`'s `check()` wraps `hit()`/`get_window_stats()` in `except Exception`
  (with an explicit `noqa: BLE001`) — intentional per rule 9 (a guardrail's outage must not
  become the API's outage), but broad enough that a `TypeError` or a bad `limits` upgrade would
  also read as "Redis is down" and fail open for the wrong reason. Narrowing to the specific
  Redis/storage exceptions and re-raising anything else would keep the fail-open behaviour for
  real outages while surfacing a real bug as a real bug. Not urgent — the current behaviour is a
  known, deliberate tradeoff, not a bug — but worth pairing with a
  `rate_limit_fail_open_total{reason}` counter so a misclassification is visible.
- **A per-tenant rate-limit ceiling alongside the per-key one.** *(S)* Buckets are keyed on
  `key_id`, so a tenant holding N keys has N times the budget — fairness between clients, not
  a cost ceiling. A second bucket on `tenant_id` checked beside the first makes it a ceiling,
  at the cost of a second Redis round trip per request. Not built because nothing here bills
  by request.
- **Scope the CLI's bootstrap key.** *(S)* `scripts/create_tenant.py` mints unrestricted keys.
  That is right for the first key of a tenant and wrong as a habit; a `--scopes` flag would
  let the CLI mint narrow ones too, rather than requiring a round trip through the API.
- **Treat retrieved chunk text as untrusted input.** *(M, unmeasured — see the caveats)* Found
  2026-08-05 while scanning a third-party skill set; recorded because **the word "injection"
  appears nowhere in `app/` or in any doc here**, so the absence was silence rather than a
  decision. `answer_service._build_document_blocks` puts each retrieved chunk's
  `page_content` verbatim into an Anthropic `document` content block, so a PDF containing
  "ignore your instructions and ..." reaches the model as context.

  Three things keep this off the urgent list, and all three should be checked before anyone
  acts on it. **Documents are tenant-scoped**, so a tenant can only poison their own answers —
  the blast radius is self-inflicted, not cross-tenant, which is what would make it serious.
  **Epic 1 has no tools**, so there is nothing to abuse; that changes at Epic 3, where the
  agent gets tools and human-in-the-loop gates, and this entry should be re-read then.
  And the `document` block with `citations` enabled is Anthropic's own channel for
  source material rather than string-concatenation into the prompt, which is *plausibly* more
  resistant — **unverified, and worth measuring before relying on it.**

  If it is taken: the cheap version is a length cap plus a signature filter on chunk text at
  *ingest* time, so a poisoned document fails loudly with `error_message` set rather than
  becoming a retrievable chunk. The expensive version is an output check that the answer's
  claims are covered by the cited spans, which Epic 2's faithfulness scoring gets for free.

## Product surface

- **`DELETE /v1/documents/{doc_id}`.** *(S)* Currently the only way to remove a document is by
  hand in both Qdrant and Postgres — which the user has already had to do once.
- **Streaming `/ask`.** *(M)* 11s to first token is a long silence. Anthropic streams; the
  citation blocks arrive incrementally.
- **Conversations with persisted citations.** *(L)* Epic 4 Phase 5; noted so the ideas here
  stay connected to the plan.
- **Per-tenant usage and spend endpoint.** *(M)* Depends on recording usage above. Also the
  foundation for any quota that isn't purely request-count-based.
- **`GET /v1/documents` has a bounded `limit` but no real pagination.** *(S)* `count` on
  `DocumentListResponse` is the size of the page just returned, not the tenant's total, and
  there's no cursor/next-page token. Fine at today's document counts; add
  `(uploaded_at, doc_id)` cursor pagination and a total count before it isn't.
- **Document-name resolution for `/ask` caps its candidate set at 200 records.** *(S)*
  `ask.py` loads the tenant's newest 200 `DocumentRecord`s and matches in memory
  (`document_scope.py`); a tenant with more than 200 documents naming an older one gets
  "no document matching" despite owning it. **Currently unreachable at the recorded scale
  target** (10 documents/tenant), so not urgent, but the right fix is cheap regardless: resolve
  an explicit `doc_id=` or exact filename with an indexed query instead of loading N candidates,
  which also removes the 200 cap as a concept.
- **`DocumentRecord.status` is a plain `str`, not a constrained type.** *(S)* Only four values
  are ever written (`STATUS_PENDING`/`PROCESSING`/`INGESTED`/`FAILED`), enforced by convention
  in Python and not at all in Postgres (no `CHECK` constraint) or in the API schema
  (`status: str`, not `Literal`). Low risk today since nothing else writes this column, but
  cheap to close with a `Literal` in the schema and a migration-added `CHECK`.

## Ops

- **No deterministic end-to-end pipeline test with fake providers.** *(M)* CI's Docker smoke
  test explicitly avoids ingestion and answer-generation provider calls (fake keys only), so
  nothing in CI exercises upload → enqueue → worker → parse → chunk → embed → Qdrant → rerank →
  generate → citations as one path. A fixture that fakes Voyage/Anthropic/the vision model would
  catch a wiring break between any two of those steps without needing Epic 2's golden set or a
  real provider call.
- **Worker retries don't distinguish transient from deterministic failures.** *(S)*
  `INGEST_RETRY` (`app/worker/app.py`) retries every exception up to 3 times with no
  `retry_exceptions` filter. The module's own comment already says retries can't fix a corrupt
  PDF — but a corrupt PDF still gets parsed and vision-captioned up to 3 times before it settles
  on `failed`. Classify: provider throttling/timeout/Qdrant-Postgres-unavailable are retryable;
  unsupported/corrupt/encrypted-document and validation failures are not.
- **Reconcile Postgres against Qdrant, in both directions.** *(M)* Versioned ingestion (2026-08-06)
  removed the failure where a re-ingest could lose a working document, and left two kinds of
  divergence behind, both silent. **Orphaned generations:** points inserted for a version whose
  publish UPDATE never landed, or whose `delete_superseded` failed. They are unreadable, so nothing
  ever asks for them, and the prune only removes versions *other* than the one it keeps -- so nothing
  reclaims them either. **Missing generations:** a row claiming an `ingestion_version` for which
  Qdrant holds no points, which reports `ingested` and answers nothing. A command that lists the
  distinct `metadata.ingestion_version` values per `doc_id` and diffs them against
  `documentrecord.ingestion_version` finds both, and can delete the first class and re-queue the
  second. Neither is reachable through the API, so this is an operator tool, not an endpoint.
  Wanted before an orphan can cost real money in resident memory -- i.e. not urgent at six
  documents, and squarely on the path to the 10k-tenant target.

- **Dedup concurrent enqueues for one document.** *(S)* Two uploads of the same bytes by the same
  tenant, close together, derive the same `doc_id` and stage the same row -- but each defers its
  own job, so two workers can ingest one document at once. Qdrant survives it -- each attempt inserts
  its own generation and the later flip wins -- but figure captioning is non-deterministic LLM output,
  so the two runs need not produce identical chunk sets, and the loser's points are pruned only if its
  own `delete_superseded` happened to run last. Inferred from reading the code, not reproduced. The fix is one `SELECT ... FOR UPDATE`
  on the existing row inside the transaction that already wraps the stage-and-defer, skipping the
  defer when the status is already `pending` or `processing`; the care needed is that a *genuine*
  re-upload after a completed ingest must still enqueue.
- **Stuck-job sweeper.** *(S)* `updated_at` already makes a worker that died mid-`processing`
  visible. Nothing sweeps or re-enqueues those, so the row sits in `processing` forever.
- **Backups.** *(M)* Postgres holds tenants, keys, and the document registry; there is no
  backup of any of it. Deferred, not dropped.
- **Correlation ids through api → job → worker.** *(S)* Today, tracing one document across the
  three requires matching on `doc_id` and timestamps by eye.
- **Alert on `failed` ingestion rate.** *(S)* Failures land in `error_message` and nobody looks
  unless a user complains.
- **Check `Cross-Origin-Embedder-Policy: require-corp` against the Streamlit UI in a real
  browser.** *(S)* nginx sets it on every response. On the JSON API it is inert (COEP is a
  document policy) and `Cross-Origin-Resource-Policy: same-origin` provably does not affect a
  CORS-mode `fetch` — the Fetch standard runs that check only when the response tainting or type
  is `"opaque"`, so the React client is unaffected and the headers must not be removed to
  "unblock" it. What is **untested** is COEP on the Streamlit *document*: it requires every
  cross-origin subresource to carry CORP itself. Streamlit bundles its assets today, so this
  holds; a version that reaches for a CDN font would break in a browser and nowhere else — no
  test, no log, no error server-side. Needs one Playwright load of the page behind nginx with
  the console captured.
- ~~**Revisit `slo-architect` when the app actually serves traffic.**~~ **Vendored 2026-08-05**
  once hosting went on the table — `.claude/skills/slo-architect`, MIT, provenance in
  `.claude/skills/VENDORED.md`. Note it ships three executable, unreviewed Python scripts, unlike
  every other vendored skill here. Nothing measures the API yet, so an SLO defined from it today
  would have no SLI behind it. Delete this line at the next prune.

## Portfolio and presentation

- **A short architecture video or annotated walkthrough.** The tenant-isolation and
  queue-atomicity reasoning is the strongest part of this project and the least visible from a
  README.
- **Structurizr DSL for the C4 model (context/container/component).** *(S)* Text-based,
  version-controlled diagrams — a system-*shape* view to complement `docs/upload-path.html`'s
  execution-*order* trace, which is a sequence through one path, not the whole architecture.
  Render with `structurizr-cli` (or the free workspace on structurizr.com) to SVG/PNG, checked
  in or built in CI, so the diagram lives next to the code it describes instead of drifting the
  way a hand-drawn one would. Worth heeding `upload-path.html`'s own warning either way: a stale
  diagram reads as authoritative, so whichever route ships needs the same "update it in the same
  commit or delete it" discipline.
- **Publish the eval results once Epic 2 lands.** A before/after on recall@k with the
  methodology is more convincing than any feature list.
- **Write up the silent-failure catalogue.** Captions that were vision-model refusals, a green
  test run that tested almost nothing, an answer scoped to the wrong document — all of them
  shipped, all were caught, none raised an exception. That's a genuinely interesting post.

---

## Considered and rejected

Kept so they don't come back without new information.

| Idea | Verdict |
|---|---|
| Neo4j / a graph database for document relationships | Rejected. `microsoft/graphrag` — the reference implementation — uses **no** graph database: networkx in memory, parquet on disk. Adding a fourth datastore buys nothing we can't do with what we have. `docs/TECHNICAL_DECISIONS.md`. |
| Import `microsoft/graphrag` as a dependency | Not possible. All 8 of its packages pin `requires-python >=3.11,<3.14`. Anything worth taking gets reimplemented. |
| SQLite for tests | Rejected after trying it. It surfaced a real tz bug, but testing on an engine the app never runs is how backend-specific bugs hide. The assumption is now pinned by an explicit test instead. |
| `slowapi` for rate limiting | Its storage and strategy imports are `limits`' **synchronous** modules and `extension.py:514` calls `hit()` inline, so every check blocks the event loop -- 65.5 ms vs 18.5 ms at 200 concurrent. `limits` itself **was** adopted (2026-08-03) via `limits.aio` + `implementation="redispy"`; the `redis<8` pin that this row used to cite as the blocker is on the *synchronous* `limits[redis]` extra only. |
| An agentic answer path | Deliberately not. `/ask` is a fixed retrieve → rerank → generate sequence; adaptive judgment is Epic 3's job and would buy nondeterminism here for nothing. |
| Making `/ask` scoping use a model to guess the document | Not yet. Deterministic matching handles explicit names; semantic reference ("the flyer", "my CV") genuinely needs a model **and** needs the eval harness to show the guessing helps more than it hurts. |
| **HMAC-with-pepper instead of a plain digest for API keys** | Rejected — correct advice, wrong threat model. A pepper defeats *offline brute force*, which requires the hashed input to be guessable; an API key here is 256 bits of CSPRNG output, so a stolen `key_hash` is already useless without inverting the digest. It also cannot be rotated: re-deriving `HMAC(new_pepper, key)` needs the plaintext keys, which we deliberately do not store, so changing the pepper invalidates every key at once. That is a worse operational position than today, bought for no gain. Revisit only if key entropy is ever reduced. |
| **Storing `key_hash` as `BYTEA` instead of hex** | Rejected. Saves 32 bytes/row — under 1 MB at the 10k-tenant target — against a real cost: the column stops being readable in `psql`. Cheaper to apply than it was (Alembic landed 2026-08-05, so this is a revision rather than a hand-written `ALTER`), but the readability cost stands and the saving is still under 1 MB. The genuinely useful halves of that suggestion were already done (`unique=True, index=True`, plus `prefix`/`last_used_at`/`revoked_at`) or have since shipped (expiry, scopes). |
