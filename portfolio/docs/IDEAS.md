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
  what it read.
- **Hybrid search (BM25 + dense).** *(M)* Exact identifiers, model numbers, and chemical
  formulae are where pure dense retrieval is weakest, and this corpus is full of them. Qdrant
  supports sparse vectors natively. Measure first.
- **Per-document-type chunking.** *(M)* A CV, a one-page flyer, and a 30-page paper currently
  share one strategy. The flyer becoming a single chunk was luck, not design.

## Cost and performance

- **Record token usage per answer.** *(S, high value)* `answer_service.py` never reads
  `response.usage`, so cost is only knowable while LangSmith tracing happens to be on — and
  that project is on a 14-day retention tier. Log `input_tokens`/`output_tokens`/`stop_reason`
  structurally per answer. Prerequisite for anything else in this section.
- **Raise `max_tokens` above 1024, or stream.** *(S)* One measured answer finished **11 tokens**
  under the ceiling. Structured-output requests sit right against it, and hitting it truncates
  mid-JSON — which reads as a model failure rather than a config limit.
- **Cheaper model for figure captions.** *(S)* Captioning uses the same model as answering.
  It is a bounded describe-this-image task; Haiku may be indistinguishable at a fifth the cost.
  Measurable against a handful of figures without any eval harness.
- **Batch API for corpus ingestion.** *(M)* Anthropic's Batches API is 50% off and ingestion is
  not latency-sensitive. Fits the worker model exactly.
- **Fast mode for interactive `/ask`.** *(S)* Opus-tier only and premium-priced, so probably
  wrong for this workload — noted so the question isn't reopened without the numbers.

## Scale — toward 10k tenants × 10 documents

- **Payload index on `metadata.tenant_id` with `is_tenant=true`.** *(S, becomes required)*
  Harmless at 6 documents; at ~1M points an unindexed tenant filter degrades toward a scan.
  Already an open question in `docs/MEMORY.md` — listed here because the *work* is small and
  well-understood.
- **Quantization.** *(M)* Scalar or binary quantization on the collection, to keep the working
  set in RAM at 16 GB. Costs recall; the `qdrant-performance-optimization` skill has the
  tradeoff. Needs recall@k to evaluate honestly.
- **Measure `processed_dir` growth.** *(S)* Still unmeasured — the attempt died on Docling
  timeouts. Determines whether processed artefacts can stay on local disk at target scale.
- **Object storage for uploads.** *(L)* Local disk doesn't survive a multi-instance deployment.
  Not needed until there is more than one api host.

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

## Auth

- **Key expiry.** *(S)* `ApiKey` has `created_at`, `last_used_at`, and `revoked_at` but no
  `expires_at`. A key that is never explicitly revoked is valid forever, which is the wrong
  default for a credential handed to CI.
- **Scopes.** *(M)* Every key can do everything its tenant can. A read-only key for a
  dashboard, or an ingest-only key for a pipeline, is the obvious next cut — and it is
  cheaper to add before there are keys in the wild than after.
- **Surface `last_used_at` in `create_tenant.py --list`.** *(S)* It is already recorded and
  already the input to "which of these keys can I safely revoke".

## Product surface

- **`DELETE /v1/documents/{doc_id}`.** *(S)* Currently the only way to remove a document is by
  hand in both Qdrant and Postgres — which the user has already had to do once.
- **Streaming `/ask`.** *(M)* 11s to first token is a long silence. Anthropic streams; the
  citation blocks arrive incrementally.
- **Conversations with persisted citations.** *(L)* Epic 4 Phase 5; noted so the ideas here
  stay connected to the plan.
- **Per-tenant usage and spend endpoint.** *(M)* Depends on recording usage above. Also the
  foundation for any quota that isn't purely request-count-based.

## Ops

- **Stuck-job sweeper.** *(S)* `updated_at` already makes a worker that died mid-`processing`
  visible. Nothing sweeps or re-enqueues those, so the row sits in `processing` forever.
- **Backups.** *(M)* Postgres holds tenants, keys, and the document registry; there is no
  backup of any of it. Deferred, not dropped.
- **Correlation ids through api → job → worker.** *(S)* Today, tracing one document across the
  three requires matching on `doc_id` and timestamps by eye.
- **Alert on `failed` ingestion rate.** *(S)* Failures land in `error_message` and nobody looks
  unless a user complains.

## Portfolio and presentation

- **A short architecture video or annotated walkthrough.** The tenant-isolation and
  queue-atomicity reasoning is the strongest part of this project and the least visible from a
  README.
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
| `slowapi` for rate limiting | Unsatisfiable: `limits[redis]` pins `redis<8` against this project's `redis>=8.0.1`, and its storage is synchronous, so every check would block the event loop. |
| An agentic answer path | Deliberately not. `/ask` is a fixed retrieve → rerank → generate sequence; adaptive judgment is Epic 3's job and would buy nondeterminism here for nothing. |
| Making `/ask` scoping use a model to guess the document | Not yet. Deterministic matching handles explicit names; semantic reference ("the flyer", "my CV") genuinely needs a model **and** needs the eval harness to show the guessing helps more than it hurts. |
| **HMAC-with-pepper instead of plain SHA-256 for API keys** | Rejected — correct advice, wrong threat model. A pepper defeats *offline brute force*, which requires the hashed input to be guessable; an API key here is 256 bits of CSPRNG output, so a stolen `key_hash` is already useless without inverting SHA-256. It also cannot be rotated: re-deriving `HMAC(new_pepper, key)` needs the plaintext keys, which we deliberately do not store, so changing the pepper invalidates every key at once. That is a worse operational position than today, bought for no gain. Revisit only if key entropy is ever reduced. |
| **Storing `key_hash` as `BYTEA` instead of hex** | Rejected. Saves 32 bytes/row — under 1 MB at the 10k-tenant target — against a real cost: the column stops being readable in `psql`, and there is no Alembic, so it is a hand-written migration on the auth table. The genuinely useful halves of that suggestion were already done (`unique=True, index=True`, plus `prefix`/`last_used_at`/`revoked_at`) or are now in **Auth** above (expiry, scopes). |
