# Memory

State that does not survive a new session otherwise. Read this first; update it last.

**What belongs here vs. the other docs** — the split is what keeps any of them worth reading:

| File | Holds | Changes when |
|---|---|---|
| `CLAUDE.md` | Rules and invariants. Imperative, timeless. | A new way to break the system is found. |
| `CHANGELOG.md` | What a *user* notices changed, and what breaks on upgrade. | Observable behaviour changes. |
| `docs/PATTERNS.md` | Recurring shapes and the failures they prevent. | The architecture changes. |
| `docs/TECHNICAL_DECISIONS.md` | Why each technology, and what was rejected. | A decision is revisited. |
| `docs/EPIC_*_PLAN.md` | What is planned and in what order. | Scope or sequencing moves. |
| `docs/IDEAS.md` | The parking lot — unscheduled ideas, and rejected ones with their reason. | Any time something occurs to you. |
| **`docs/MEMORY.md`** (this file) | **Where we actually are.** Standing directives, open questions, session log, measurements taken. | Every working session. |

The pair most likely to drift is this file's session log and `CHANGELOG.md`. Same events, different readers: the changelog says `Retry-After` is now safe to obey, this file says the counter granted 2 of 10 to a client that waited and records the measurement. If an entry explains *why*, it belongs here.

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
  `.python-version` is tracked and pins local dev at 3.13, so plain `uv venv` is correct —
  pydantic fails to build models on 3.14 pre-releases. It is excluded from the Docker build
  context, and CI overrides it per job and then *asserts* the interpreter it actually got.
  Note that `portfolio/.gitignore` no longer carries a `!.python-version` negation (the user
  removed it); the file stays committed because gitignore does not apply to tracked files, but
  it would vanish silently if it were ever untracked.
- **Never commit `.env`.** It holds a real LangSmith API key, and **this repository is
  public** — a key that reaches a commit is disclosed the moment it is pushed, whether or not
  the commit is later reverted. `.env.example` stays placeholders only.
- **Commit and push directly to `main`, and only `main`** (explicit permission; overrides the
  default branch restriction). The `claude/detailed-plan-o6lubt` working branch was retired
  2026-08-02 -- this is a WIP app and mirroring every commit to a second branch bought
  nothing. The *remote* branch could not be deleted from the container (the session's git
  proxy refuses ref deletion); it points at the same commit as main and is the user's to
  remove in the GitHub UI.
- **There is no dependency-minimisation rule, and don't invent one.** Stated by the user 2026-08-05
  after a dependency comparison leaned on package counts. `docs/EPIC_2_PLAN.md`'s "this adds **no
  dependency**" is a *fact* about parquet arriving free via Streamlit, not a value. The signals that
  actually matter when weighing a package: does it pin an existing package **backwards** (an eval
  tool dragging `huggingface-hub` back constrains the *ingestion* stack), does it reach the runtime
  image, does it monkey-patch anything (`nest-asyncio`), and what it adds to the CVE surface
  `pip-audit` scans. Raw package count is close to meaningless — measured: `.docker/Dockerfile` runs
  `uv sync --no-install-project --locked` with **no `--extra`**, so `[project.optional-dependencies]`
  never reaches the api, worker or Streamlit image. Eval tooling therefore belongs in an `eval`
  extra.
- **Hosting the app online is on the table** ("at some point", 2026-08-05) — a signal, not yet a
  decision, so don't build for it. What it changes when it firms up: `slo-architect` was parked with
  the explicit precondition "revisit when the app actually serves traffic"; Epic 4 Phase 4
  observability and the nginx `limit_req` idea are both filed as "not urgent while the API is not
  public"; **backups become the highest-consequence open item**, since nothing backs up the Postgres
  holding tenants, keys and the document registry; the prompt-injection entry's mitigating argument
  is "blast radius is self-inflicted", which weakens sharply with real tenants; and the Dependabot
  backlog stops being background noise. A server-backed eval or observability platform also stops
  being an imposition if a deployment exists anyway.
- Streamlit retires when the React UI lands (Epic 4 Phase 6). Don't invest in it beyond parity.
- Commit-signing warnings from the stop hook are expected and were accepted — signing cannot
  work in this container. Don't re-raise.

---

## Current state

**Built and verified:**

- **Epic 1** — retrieve → rerank → generate with citations, multi-format ingestion (Docling),
  structure-aware chunking, Qdrant + Postgres registry, Streamlit UI, full Docker stack.
- **Epic 4 Phase 1** — API-key auth, tenant scoping. Keys hashed at rest (SHA-512), shown
  once, base62 + CRC32 format, 30-day default expiry from a 30/60/90/365/never menu, per-key
  scopes, and full CRUD at `/v1/keys` plus a Streamlit page.
- **Epic 4 Phase 2** — rate limiting, now bucketed **per key** rather than per tenant. Redis
  sliding window via `limits` (hand-rolled Lua until 2026-08-03), fails open.
- **Epic 4 Phase 3** — docs, health checks, CI.
- **Epic 4 Phase 5.1** — ingestion behind a procrastinate job queue. `POST /v1/documents`
  returns 202; document row and job commit in one transaction.
- **No shared corpus** (removed 2026-08-03). Every document belongs to the tenant that uploaded
  it; a fresh install has nothing to search until someone uploads. Epic 2's golden set therefore
  has no document set to measure against and needs tenant-owned fixtures built first.
- **Explicit document scoping on `/ask`** — pulled forward out of Epic 2 because it fixed an
  observed defect rather than moving a metric. Naming a document by **filename or `doc_id`**
  scopes retrieval to it; an unowned identifier is a 404.
- **Alembic owns the schema** (2026-08-05), and **ingestion is versioned** (2026-08-06): an ingest
  inserts a generation and publishes it by flipping `DocumentRecord.ingestion_version`, so a failed
  re-ingest leaves the previous generation serving. `QdrantStore.upsert` deletes nothing. Both of
  these reversed a recorded decision, so a reader who half-remembers this project will remember the
  opposite — `docs/TECHNICAL_DECISIONS.md` records both reversals with the reasoning.

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
`ingested`); and **the nginx config, finally** — syntax via `nginx -t`, and the edge rate limiter's
behaviour against a stub upstream (2026-08-05). **Still unverified:** the Qdrant client over the
wire under concurrency. The nginx check used the locally-cached `nginx:1.29` because `1.31` (the
pinned tag) would not pull through the proxy; every directive involved is long-standing, but it is
not the pinned image.

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

- **slowapi vs the hand-rolled limiter** (2026-08-02, localhost Redis, steady state, best of
  five). Per-check latency is a wash: 0.32 ms sync, 0.36 ms async. Under concurrency the sync
  path blocks the event loop: 100 concurrent 21.4 ms vs 11.1 ms, 200 concurrent 65.5 ms vs
  18.5 ms. slowapi 0.1.10 has no async storage path at all -- it imports `limits.storage` and
  `limits.strategies`, the sync modules. Also: `uv add slowapi` unpinned does **not** error on
  our `redis>=8.0.0`; it silently resolves `limits==1.6` / `slowapi==0.1.6`. Only
  `limits[redis]>=5` reports unsatisfiable. Full write-up in `docs/TECHNICAL_DECISIONS.md`.
- **`limits` used directly is viable and was the thing worth evaluating** (2026-08-02).
  `RedisStorage("async+redis://...", implementation="redispy")` runs fully async on **redis-py
  8** -- the `<8.0.0` pin is on the *sync* extra only, and the redispy bridge wants
  `redis>=5.2.0` with no ceiling. Performance is a dead heat with ours (0.45/1.23/5.02/11.11 ms
  at 1/10/50/100 concurrent vs 0.36/1.20/5.09/11.05), **but** it raised
  `MaxConnectionsError` at 200 concurrent where ours completed in 18.5 ms, and `hit()` +
  `get_window_stats()` is two round trips where our script returns allowed/remaining/reset from
  one. **Kept ours on 2026-08-02, then adopted `limits` on 2026-08-03** — the user's call once
  the memory numbers below were on the table. Full accounting in
  `docs/TECHNICAL_DECISIONS.md`.
- **Redis cost per rate-limit key** (2026-08-03, `MEMORY USAGE` after 60 requests on one key).
  `limits` `SlidingWindowCounter` **120 bytes** (a string); `limits` `MovingWindow` **1464** (a
  list); the old hand-rolled ZSET 3120 (32-char uuid members). **In use: MovingWindow**, so
  ~29 MB at 10k tenants × 2 scopes, against ~62 MB for the ZSET. The 120-vs-3120 "26×" was the
  number that first justified the swap and it was a bad comparison — `limits`' cheapest strategy
  against our implementation. Like for like the figure is 2×, and the 26× bought a strategy that
  did not honour its own `Retry-After` (next entry).
- **The sliding-window *counter* does not honour its own `Retry-After`** (2026-08-03). Spend a
  10-request budget in a 2-second window; both strategies advertise `reset in 2.00 s`. After
  waiting 2.2 s, `MovingWindow` grants **10/10** and `SlidingWindowCounter` grants **2/10**, with
  the full budget back only at 4.2 s — twice the window. This is why the strategy changed the
  same day it shipped. Guard reliability, measured by reinstating the counter:
  `test_the_full_budget_returns_after_the_advertised_reset` red 5/5,
  `test_window_expiry_is_set_so_buckets_do_not_leak` red 5/5,
  `test_a_fresh_window_advertises_a_full_window_not_zero` red only 8/10.
- **`limits` defaults `max_connections` to 100** (2026-08-03) and its pool raises
  `MaxConnectionsError` rather than queueing — which is the 200-concurrent ceiling recorded
  above, now explained rather than observed. Reproduced with both the moving window and the
  counter, so it belongs to the storage bridge, not the strategy. `redis_max_connections` in
  `Settings` overrides it.
- **Window retention differs by strategy** (2026-08-03). `SlidingWindowCounter` keeps a key for
  **2× the window** (measured 119999 ms at a 60 s window) because the current count must outlive
  its own window to be weighted as the next one's "previous". `MovingWindow`, in use, keeps it for
  **1×** (59999 ms). The test bound is `1×` deliberately — `2×` would still pass and would stop
  that test noticing a strategy change.
- **`fastapi-limiter` 0.2.0** is the only other live async option (delegates to
  `pyrate-limiter` 4.x, redis-8 compatible). Rejected on specifics: its 429 is a bare
  `HTTPException(429)` with no `Retry-After` or `X-RateLimit-*` and `try_acquire_async` returns
  a bool so a callback cannot compute them, and its bucket key embeds the route's **index in
  `app.routes`**, so inserting a route renames every existing bucket.

---

## Open questions

Unresolved, and blocking or shaping something. Each needs a decision or a measurement, not
more discussion.

1. **Identity for Epic 4 Phase 5.2.** User accounts sit on top of the existing API-key tenant
   model, and the relationship between "tenant" and "user" hasn't been decided. Blocks 5.2
   onward.
2. **Do the three `.claude/agents/` definitions resolve from a repo-root session?** Measured
   2026-08-05: definitions are picked up **at session start only** -- adding one mid-session and
   invoking it fails with "Agent type not found", and this is not a path problem, since probes at
   `portfolio/.claude/agents/` *and* at the repo root both failed in the same session while skills
   added that session were picked up twice. What is *not* measured is the interaction with the
   documented walk-**up** discovery rule: this session's working directory is the repo root, and
   walking up from there never reaches `portfolio/.claude/agents/`. Skills are found downward, which
   is why they work. If a fresh session cannot see the three agents, move them to the repo-root
   `.claude/agents/` and accept that their descriptions then load for the three dormant course
   directories too. One restart answers it.
3. **`processed_dir` disk footprint at 100k documents.** Still unmeasured — the attempt failed
   (Docling `partial_success`, 1/16 pages, fifteen timeouts on arXiv 2008.10896). Needs
   hardware that can finish a parse. Determines whether processed artefacts can stay on local
   disk at target scale.
4. ~~**Payload index on `metadata.tenant_id`.**~~ **Resolved 2026-08-03.**
   `qdrant_store._ensure_payload_indexes` indexes it with `is_tenant=True`, plus
   `metadata.doc_id` as a plain keyword. Verified against a real `qdrant/qdrant:v1.18.3`
   container, because it *cannot* be verified in-memory -- `qdrant_client`'s local mode warns
   "Payload indexes have no effect in the local Qdrant" and reports an empty `payload_schema`,
   so an in-memory assertion would have been vacuous. What remains open is the *effect at
   scale*: nothing has measured a tenant-filtered query at 1M points, with or without the
   index, so "required at 100k" is still an argument rather than a measurement.
5. ~~**Usage is not recorded anywhere.**~~ **Resolved 2026-08-03.** Every answer now logs
   `stop_reason`, `input_tokens` and `output_tokens` structurally, and `Answer.truncated` reaches
   `AskResponse` and the Streamlit page. What is still missing is `cost_usd` — the per-model price
   table Epic 2 Phase 2.2's parquet schema wants. Kept in the list rather than deleted so the
   half that shipped is not mistaken for the whole.
6. **Whole-document extraction.** "Fill this schema from document X" is not a similarity query
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

### 2026-08-06 (latest) — versioned ingestion: the write half of review P0 #2

**What shipped.** An ingest mints an `ingestion_version`, hashes it into every point id
(`uuid5(ns, f"{version}:{chunk_id}")`), inserts without deleting, and publishes with one UPDATE
(`activate_document_version`). `Retriever` reads `list_active_versions` and passes both `doc_ids` and
`versions` into the filter. `delete_superseded` prunes after the flip and is allowed to fail. Alembic
revision `307f47df6135`, which **refuses a non-empty `documentrecord`** -- points written before it
carry no version and would be permanently unsearchable while still reporting `ingested`. The live
database was empty, which is the only reason that refusal was affordable.

**Where the version does *not* go: `chunk_id`.** It is a public response field
(`CitationResponse.chunk_id`) that `README.md` documents and Streamlit prints, so putting the version
there churns every citation on every re-ingest and leaks an attempt id into the API. Only the point id
needs to differ. Delegating that question was worth it -- the survey found the third consumer I would
have missed.

**Three findings I would not have reached alone**, all from delegated read-only sweeps and all
confirmed at source before being written down:

- **`MatchAny(any=[])` returns zero points and does not widen** (probe-verified). So the empty-list
  guard cannot be tested through the engine: the dangerous mutation (`if versions:` rather than
  `is not None`) emits *no condition at all*, and a test asserting "an empty list finds nothing"
  passes under exactly that mutation. Assert the raise. Both empty-list guards now live in
  `test_retrieval_consistency.py` with that reasoning written down; I had briefly added a duplicate in
  `test_qdrant_filtering.py` and removed it in favour of a comment saying why it cannot live there.
- **The migration boundary is an outage for a populated database**, not just an inconvenience -- hence
  the refusal above, with the remedy in the message.
- **`figure_extractor` wrote `<figure_id>.png`**, a position-addressed path in the sticky
  `processed_dir` cache, with the caption cache *next to it* already content-addressed for exactly
  this reason. Versioning made it a live defect rather than a latent one: generations now coexist by
  design, and "the previous generation keeps serving" is the whole fallback -- but the image files do
  not roll back with it, so a re-ingest that shifted the figure order overwrote a file a live chunk
  still cited, and `Home.py` renders that path beside the old caption. Now
  `<figure_id>-<sha256[:16]>.png`. Two tests, both mutation-confirmed. This is the one place where the
  change I was making *created* the exposure, which is the kind of thing a per-slice agent cannot see
  and a whole-context read can.

**A defect I introduced and the fixture hid.** The four service-backed suites built their schema with
`SQLModel.metadata.create_all`, so `ingestion_version` never appeared on an existing `portfolio_test`
and twelve tests failed with `column ... does not exist` -- the exact failure Alembic was adopted to
end, reproduced inside the test fixture. **CI could not have caught it**: a fresh service container has
no old table, so it only bites a developer with a database from last week. All four now run
`app.db._migrate_to_head`. `test_migrations.py`'s pre-Alembic simulation had the same flaw in reverse:
`create_all` built *today's* models, so the revision adding the column hit `DuplicateColumn`. It now
upgrades to `_INITIAL_REVISION` and drops `alembic_version`, which is the real historical schema and
stays right as revisions land.

**Also corrected:** `delete_superseded` was typed `-> int` and documented as returning points removed,
while returning a hardcoded `0`. Qdrant's delete answers with a status, not a count. Now `-> None`,
with the reason recorded.

**Mutations run, all confirmed red on their own test and green elsewhere:** a second `new_id()` for the
flip; swallowing a failed flip; letting a prune failure propagate; the version dropped out of the point
id; `if versions:`; the prune selector's `must_not` weakened; the prune losing its tenant condition;
`rowcount == 0` not raising; the flip's tenant dropped from the WHERE; `error_message` not cleared; the
stamp pinned at head instead of the initial revision; the stamp branch deleted; the figure path back to
`<figure_id>.png`. Two of them found real weaknesses in my *tests* rather than the code -- the prune
test's bystander originally used a different `doc_id`, so it passed with the tenant condition deleted.

**Gate:** 383 passed, **0 skipped** (Postgres and Redis both up locally); ruff, ruff format and ty
clean. The skip count is the number that matters and it is the one I read.

**Still open:** reconciliation in both directions, now written up in `IDEAS.md` rather than left as a
sentence in this log -- an orphaned generation is unreadable *and* uncollected, since the prune only
removes versions other than the one it keeps.

### 2026-08-06 (later) — the over-commenting pass, and what it found

The user said the code is hard to read; the external review's §7 says the same ("reviewers must read
historical incident reports to understand small functions"). Both are right, and I had been making it
worse all session -- every fix landed with a ten-line comment.

The rule applied: rule 15 says a comment records the *failure*, not the mechanism -- and not the
history of how the mechanism arrived. So each comment kept the sentence saying what breaks, and the
narrative moved to `docs/TECHNICAL_DECISIONS.md` § Secrets in Settings, which now also carries an
explicit list of what was displaced from where. Nothing was deleted outright.

**`app/config.py`: 369 -> 314 lines, 99 -> 56 comment lines.** The clear win, and the file the review
named. What went: a `get_secret_value()` count that was wrong in both halves, the `worker_concurrency`
field's obituary, `manifest_path`/`raw_pdf_dir` archaeology, and the CORS defaults' drift narrative.
What stayed, tightened: every "must stay under", "do not reintroduce", "defaults it to 100".

**And the useful negative result: the other two files mostly did not need it.**
`document_scope.py` lost 10 lines, `qdrant_store.py` 5. Their comments explain non-obvious *regex*
and *filter* behaviour -- first-match-wins alternation ordering, why filenames are matched against
real names rather than pulled from prose, why an empty `MatchAny` is not the same as no condition.
That is exactly where a comment earns its place, so trimming further would have deleted constraints
to hit a number. Only the archaeology went: the `|global` alternative, the corpus-era filter shape.

Worth stating plainly: **the repo-wide comment count barely moved** (599/5495 -> 610/6345), because
this session added `retriever.py`, the migrations and three test suites, all commented. The ratio
improved from 10.9% to 9.6%. The remaining density is concentrated in `streamlit_app/Home.py` (55)
and `figure_extractor.py` (35), neither examined yet.

### 2026-08-06 — review P0 #2 and #3: cross-store reads, and Alembic

**P0 #2 — Qdrant and Postgres disagreeing about what is searchable.** Points are upserted, *then*
the registry row is written, so a failure between them leaves retrievable chunks behind a row saying
`processing` or `failed`. `Retriever.retrieve` now filters on the registry, in the retriever rather
than the router because `/ask` and Streamlit both arrive there -- same lesson as the upload path.
(The function was `list_ingested_doc_ids`; the versioned-ingestion entry above replaced it with
`list_active_versions`, so don't grep for the old name.)

The trap was the empty case. `_build_filter` used `if doc_ids:`, so an empty allow-list fell through
to *no* document condition: "nothing is ingested" would have become "search everything", worse than
the bug. It now raises on an empty list.

**Mutation testing earned its keep, twice.** My first version had two guards -- an early return for
an empty ingested set, then a check on the intersection -- and deleting the first changed no test,
because the second covered it. A guard whose removal keeps the suite green is documentation, so they
are one branch now; re-mutated, deleting it turns two red. That is rule 15 catching *redundant code*
rather than a missing test, which is the use I had not seen before.

Only the read path. **Closed later the same day** -- versioned ingestion shipped (see the entry above),
so `upsert` no longer deletes and the write path can no longer lose a searchable version. Reconciliation
for orphans in either direction is still open and now lives in `IDEAS.md`.

**P0 #3 — Alembic.** `init_db` runs `alembic upgrade head` inside the advisory lock, replacing
`create_all`. Four things that took real care, each verified rather than assumed:

- **`include_object` excludes `procrastinate_*`.** They are not in `SQLModel.metadata`, so
  autogenerate reads them as "should not exist". Removed the filter and regenerated: it emitted
  `drop_table` for all four. It would have deleted the job queue on the next migration.
- **A pre-Alembic database is stamped, not migrated.** `create_all` left tables and no
  `alembic_version`; `upgrade head` there raises `DuplicateTable` on *every* boot. Mutation-confirmed
  by disabling the stamp branch. Verified end to end with a seeded tenant row that survived.
- **`alembic.ini` and `migrations/` must be COPYed into the image.** The Dockerfile copies explicit
  paths, so they were absent and the container would have booted and failed at the first query. Found
  by checking the COPY list, not by a test.
- **The commands need the *sync* connection.** `run_sync` provides it; handing them the
  `AsyncConnection` fails inside `Dialect.has_table` with a message about internal dialect use, which
  reads as an alembic bug.

Also dropped `fileConfig` from `env.py`: alembic's template calls it, it needs logging sections in
the ini, and this project configures logging once through structlog.

CI gained `alembic check` (mutation-verified: adding a model field without a revision fails it) and
`test_migrations.py` joined the skip guard, now six suites. That guard has been wrong twice in this
file's history, so the count is worth watching.

**Still open from the review:** P0 #4 is the AI quality gate, which is Epic 2 entire -- a golden set,
recall@k, the CI regression gate -- not a patch. Sections 2-8 untouched.

### 2026-08-05 (end of day, later) — the same-filename content swap (external review P0 #1)

The user supplied a deep external review and said to take **point 1 only**. Verified it at source
before touching anything, and it is real. The most serious defect found in this project so far.

**The defect.** Uploads were stored at `<upload_dir>/<tenant_id>/<safe_filename>` -- **no `doc_id`
in the path**. Two documents sharing a filename therefore shared a path:

1. A uploaded as `report.pdf` -> `doc_id=A`, bytes at `tenant/report.pdf`.
2. B uploaded, different bytes, also `report.pdf` -> `doc_id=B`, overwrites the same path.
3. Worker A dequeues, reads the path it was handed, gets **B's bytes**.
4. B's content is parsed, chunked, embedded and stored under **A's** identity.

And the evidence was then erased: `_parse_and_chunk` recomputed `content_hash` from whatever it had
actually read and `save_document_record` wrote that back over the value the upload staged, so A's row
was internally consistent and wrong.

**One thing the review did not name, which decided the fix.** The damage was *sticky*, not
transient: the parse cache is `processed_dir/<doc_id>.json` and figures are
`processed_dir/<doc_id>/figures`, so B's parsed output and captions persisted under A's `doc_id` and
a later correct re-ingest of A would hit that cache and read B again. A lock around the write would
not have helped; the path had to change.

**Fixed in two layers.** `document_upload_path` now owns the layout --
`<root>/<tenant>/<doc_id>/<filename>`, with the filename kept as the *leaf* deliberately, because
`chunk_document` stores `file_path.name` as chunk metadata and that is what
`retrieval/document_scope.py` matches a question against; a `<doc_id>.pdf` leaf would make
document-name scoping match on a content hash. And `expected_digest` travels with the job, checked
**before the parse**, failing closed with a new `ContentMismatchError`.

**Streamlit had its own copy of the bug** -- it built `tenant_dir / safe_filename(...)`
independently. Both writers now go through the one helper, which is the actual lesson: the duplicate
path construction is *why* the two could diverge.

**Two judgement calls worth keeping.** `expected_digest` is **required, not defaulted**, on
`ingest_document` and `_parse_and_chunk` -- a default of `None` would let a caller silently opt out
of the integrity check by forgetting an argument, which is the thing the parameter exists to prevent.
`ty` then found all seven stale call sites for free. But it *is* optional on the procrastinate
**task**, because job arguments are JSON rows already in `procrastinate_jobs` when a deploy lands: a
required parameter would fail every in-flight job permanently with a TypeError. Rule 8 -- absent data
means the pre-existing behaviour -- and it logs `worker.ingest_without_digest` at warning, because
the pre-existing behaviour is the one with the defect.

**Six tests, three mutations, all red.** Removing `doc_id` from the path turns two red; disabling the
digest comparison turns one red; and *moving the verification after the parse* also turns it red --
with the check late, `ContentMismatchError` is never what surfaces, because Docling tries to parse
the swapped bytes first. That third mutation is the one that proves the ordering claim rather than
asserting it.

**And it corrects something I wrote this morning.** I had recorded `content_digest` as "write-only,
its question unreachable", reasoning that since `doc_id` is derived from the bytes, bytes can never
change under a fixed id. True of the *id*, false of the *file*: the collision was on the path, not
the id. My reasoning was about the wrong object. The field is now read on every ingest.

Not done, deliberately, and still open from the review: the other three P0s (Qdrant/Postgres dual
write, no Alembic, no AI quality gate) plus everything in sections 2-8. The user said point 1 only.

### 2026-08-05 (end of day) — edge rate limiting, four vendored skills, and the nginx config finally tested

**`limit_req` at nginx, from `docs/IDEAS.md` § Ops on the user's "go".** Two zones keyed on
`$binary_remote_addr`: general at 20r/s burst 40, uploads at 30r/m burst 10, both an order of
magnitude above the app's per-key budgets because this is a flood shield and not a fairness device.
`limit_req_status 429` so the edge and the app answer the same status.

Three design points worth keeping:

- **Health is exempted by mapping its key to the empty string**, because there is no `limit_req
  off;`. The alternative — a separate `location` — means a second copy of the whole proxy block,
  and a location that declares its own `limit_req` stops inheriting the server-level ones. Shedding
  a readiness probe would take the container out of rotation to protect it.
- **Both `limit_req` directives sit at `server` level**, for that same inheritance reason: in
  `location /` they would leave any later location silently unlimited. Same trap `nginx.conf`
  already documents for `add_header`, quieter failure.
- **IP here, API key in the app, and that is not the contradiction it looks like** next to
  `TECHNICAL_DECISIONS.md` rejecting an IP key. nginx cannot see a verified key; trusting
  `$http_x_api_key` would hand an attacker unlimited buckets by varying a header.

**Verified by execution, not by reading**, which matters because a limiter that parses but does not
limit is the definition of documentation-not-verification. Ran nginx with a stub upstream and a
sidecar curl:

| Request | Allowed | Distinguishes |
|---|---|---|
| `/health/ready` ×200 | **200** | exemption works (a limited path allowed 41) |
| `POST /v1/documents` ×60 | **11** | upload zone binds — burst 10 + 1 |
| `GET /v1/documents` ×60 | **41** | discriminates by method |
| `POST /v1/ask` ×60 | **41** | discriminates by path |

Those four numbers are mutually exclusive, so a wrong map regex would have shown up as the wrong one
rather than as a plausible pass. The shed status was 429, confirming `limit_req_status`.

**And a bug I introduced and caught in the same pass.** I added `nginx -t` to the nginx Dockerfile,
which would have failed every build: the `upstream` block resolves `api:8000` at config-parse time,
and `api` is a compose service name with no DNS during `docker build`. Removed, with the reason
written where someone would otherwise re-add it. The related trap is worse and is now recorded
there too — **nginx aborts on the first `[emerg]`, and `include conf.d/*.conf` is the last line of
`nginx.conf`**, so an unresolvable upstream means `default.conf` is never parsed at all. My first
test run "failed" on the upstream and had silently validated nothing about the limiter.
`--add-host api:127.0.0.1` fixes it.

This also closes a long-standing gap: **the nginx config had never been syntax-checked** ("no nginx
binary in the sandbox"). It has now, though on the locally-cached `nginx:1.29` rather than the pinned
`1.31`, which would not pull through the proxy — noted rather than glossed.

**Four skills vendored**, both on the user's call. Three `langsmith-*` (evaluator, dataset, trace) —
LangSmith is already wired here, so these document a service in use; MIT, manifest-only licence, same
weaker provenance as the langchain set. And **`slo-architect`**, reversing this morning's "not now"
because hosting moved its stated precondition. It is the first vendored skill that ships **executable
Python**, so `ruff.toml`'s exclusion is now covering real `.py` files rather than fenced blocks, and
`VENDORED.md` says the scripts are unreviewed and unrun.

**One conflict surfaced rather than averaged.** The user's "leave evals to LangSmith" collides with
`EPIC_2_PLAN.md` Phase 2.2, which decided against LangSmith-only because *"the regression gate must
work offline and in version control."* Hosting does not change what CI needs, so that is a **revisit**
and not a stale reason. Recorded in `VENDORED.md`: the skills cover the judged half, while `recall@k`,
routing accuracy, the parquet run rows and the committed baseline stay local. A future session
reading "leave evals to LangSmith" as settled will have overturned a written decision without
noticing.

Backups stay in `IDEAS.md` — the user will handle it with a cloud backup later. Stop raising it.

### 2026-08-05 (later still) — three more agents, and why not five

The user proposed a role-based team: two senior engineers, QA, architect, code reviewer. Pushed back
on the framing and they had already been shown the reason without either of us planning it — the
`add-endpoint`/`route-audit` incident earlier the same day. Delivered three of the five, re-cut by
task shape.

**Why not the two coders.** Every route here touches the tenant boundary, so a writing agent hits a
failure contract almost immediately, and `../CLAUDE.md` says those are never delegated. The decisive
evidence was local: the two read-only surveys that morning returned excellent breadth *and* several
confident findings that were wrong on inspection. For a sweep that costs one verification pass. From
a coder it is committed code. The mechanism that does work for parallel implementation —
worktree-isolated subagents per file-disjoint slice, or `/batch` — needs a precise brief, not a role,
so there is nothing to define in advance.

**Why not a generic code reviewer.** `/code-review`, `/security-review`, `/simplify` and `/review`
already exist. Take one of a pair, not both. What *is* additive is a review against contracts no
outside reviewer can know, so `contract-review` is explicitly told to report nothing a competent
reviewer without this repository would also find.

**Named by task, not by role,** and this is the durable part: a job title has no fixed question,
which is the property that makes a delegated sweep work. It also invites the persona drift that got
`postgres-pro` and `adversarial-reviewer` rejected in the skills triage — and a reviewer defined by
its role produces findings to fill the role, which is exactly what `adversarial-reviewer`'s "each
persona MUST find at least one issue" made explicit. Now written into `../CLAUDE.md` as a general
rule with the writing-versus-reading asymmetry beside it.

Also checked the docs page the user linked rather than assuming: Claude Code's own basis for
splitting is who coordinates, whether workers must talk, and whether they touch the same files.
Agent *teams* — the closest surface to the original proposal — is experimental, disabled by default,
and does not isolate teammates in worktrees, so file partitioning is manual.

`test-gaps` is the one to reach for most often, and its brief carries the three shapes that have
already fooled this suite: a boundary test with `limit=1` that cannot tell "some budget returned"
from "all of it", a membership assertion where an exact-set assertion is possible (the tenant filter
admitted `global` for months underneath one), and an `asyncio.gather` test of a cross-*process* race
that passed with the advisory lock removed.

### 2026-08-05 (later) — a redundancy sweep that mostly found errors

Asked to remove redundant comments from the `.md` and `.py` files. Delegated two read-only surveys
(the first real use of the delegation agreement) and kept every verdict: one agent read all 51
non-test Python files and examined 339 comment/docstring units, the other read 20 markdown files in
full. **Four comments were actually redundant. Eight Python comments and about ten documented claims
were wrong**, which is the more useful result and not what anyone asked for.

**The one that matters most, because it happened inside the guard against it.**
`.claude/skills/add-endpoint/SKILL.md` item 5 justified putting `tenant_id` in the WHERE clause by
claiming `doc_id` is a plain content hash, so two tenants uploading the same file share one id. That
is false -- `upload_doc_id` salts the digest with `tenant_id` -- and item 7 of the *same file* said
so, so the skill contradicted itself. `docs/PATTERNS.md` §2 had already caught and written up this
exact correction, including the warning that "a wrong *reason* attached to a right *rule* is how the
rule gets 'simplified' away later". Then `.claude/agents/route-audit.md`, written earlier the same
day, copied the wrong half into the agent whose entire job is auditing that boundary. The
prediction came true within hours, in the file written to prevent it.

The fix was one edit doing two jobs: `route-audit.md` no longer restates the checklist at all, it
points at the skill. A second copy of a checklist is the mechanism by which the wrong reason
survives, so the dedup *is* the correction. The rule itself never changed -- a `doc_id` is
client-supplied on the way in, so how it was generated constrains nothing.

**Counts that nobody can reconcile.** Three separate ones were wrong: `config.py` claimed eight
`.get_secret_value()` call sites "worth grepping for" and the grep returns six, while naming only
four places -- and `CLAUDE.md` repeated the eight. `api/main.py` promised "three things break" and
listed two. `registry/models.py` justified the `ingested` default with "the two callers" and named
one. A count that disagrees with its own list is worse than no count, because the reader assumes the
list is the stale part.

**Five stale claims left by the corpus removal**, all in the same shape as the `m=0` incident:
`uploads.py`'s `content_digest` justified itself with a revised arXiv paper whose `doc_id` was the
arXiv id -- so its stated purpose is now *unreachable*, since every surviving `doc_id` changes when
the bytes do, and the field is write-only today; `chunker.py`'s `filename=""` default pointed at the
deleted `scripts/ingest.py`; `scripts/create_tenant.py` said it was "the only way to get a usable
key" while `routers/keys.py` said the opposite in as many words.

**And the skip count, which is rule 12's own subject.** `CLAUDE.md` and the `verify` skill said five
service-backed suites; `PATTERNS.md` said three, `TECHNICAL_DECISIONS.md` said two, `README.md` said
"both". CI loops over five -- and `portfolio-ci.yml`'s own header comment still said three. So the
one rule this project calls "the most expensive false confidence" was understated in four places at
once, including the workflow that enforces it.

Two more corrected: `TECHNICAL_DECISIONS.md` still headed the rate-limit section "hand-rolled on
`redis.asyncio`" and said "Keyed per tenant" forty lines after saying "Per key, not per tenant"; and
its graphrag rejection rested on `>=3.14` vs `<3.14` being unsatisfiable, which stopped being true
when the floor dropped to 3.13. The graphrag *verdict* survives on per-document cost; the argument
does not, and is now struck rather than deleted.

**What was deliberately not done.** The markdown survey also returned a bloat list -- ~250 lines in
`TECHNICAL_DECISIONS.md` § rate limiting where four facts are each stated three times, ~75 lines in
this file re-narrating the same swap, 113 lines of superseded Phase 1 plan inline in
`EPIC_4_PLAN.md` -- plus fifteen duplicate clusters that currently *agree* (the document-set table
in five places with five different row lists; "Postgres only" in eight; the api-must-not-import-
Docling measurement in six). Those are rewrites, not fixes, and folding them into a commit of
verified corrections would make the diff unreviewable. Left for a deliberate pass.

**On the delegation itself:** it worked, and the caveat in `../CLAUDE.md` held exactly as written.
The agents found breadth no single pass would have — 339 comment units, 20 files — and produced
several confident items that were wrong on inspection, plus an `UNSURE` bucket that was the right
call twice. Every kept finding was re-verified at source before it was edited.

### 2026-08-05 — the skill set, and what a skill costs to keep

Two sessions of skill work, logged together because the second only makes sense as the first one's
rule applied again. Provenance and per-skill reasoning live in `.claude/skills/VENDORED.md`; what
belongs here is the selection rule and the calls it produced.

**The rule: a skill's description is always in context, so an untriggered skill is not free.** It
dilutes triggering for `verify`, `add-endpoint` and `changelog` — the three that actually stop
bugs here. Every candidate therefore gets two checks in order: **licence and provenance**, then
**fit against what this project has already decided.** A skill fails on either.

Landed 2026-08-04 ([`ab9a162`](https://github.com/stanimirdim92/llms/commit/ab9a162),
[`59ffb8f`](https://github.com/stanimirdim92/llms/commit/59ffb8f)): a project-owned `changelog`
skill plus the `CHANGELOG.md` it produced, and **four of twenty-two** langchain skills.

Landed 2026-08-05: **one of ten** `pg-aiguide` skills — `postgres-database-migration`. It lands on
a gap already written down twice (no Alembic; `create_all` never adds a column) and its trigger
list is narrow — migration verbs only.

**Two rejections worth keeping, because both were the same failure in different clothes.**
`langchain-rag` triggers on "ANY RAG system" and recommends `RecursiveCharacterTextSplitter`,
OpenAI embeddings and Chroma — three things `docs/TECHNICAL_DECISIONS.md` records rejecting.
`pg-aiguide`'s `postgres` hub triggers on "any PostgreSQL database work" and routes to
`pgvector-semantic-search`, which triggers on "Implement RAG with PostgreSQL" — against a project
whose vector store is Qdrant. **Generalising: take narrow leaves from these repos, never the
hubs.** A hub's job is to claim a whole topic, and the topics here are decided. Both exclusions
are now in `CLAUDE.md` because a skill that contradicts the decision record argues back, which is
rule 6 turned into a live hazard.

Two Postgres candidates the user found were also rejected. `duthaho-postgresql` failed the
*first* check — skillsdirectory.com 403s through the proxy and no canonical repository was
found, so there is no licence to cite and no commit to pin. The content, once the user pasted it,
would have failed the second anyway; notably one of its two migration examples presents
`ADD CONSTRAINT ... UNIQUE` as routine, which is the form that blocks reads and writes for a full
index build. `postgres-pro` was honestly MIT and failed on fit: ~1170 of its 2071 lines are
replication, JSONB and extension management, none of which exist here.

**Apache 2.0 §4(d) came up for the first time.** `timescale/pg-aiguide` ships a `NOTICE`
("Copyright 2025 Timescale, Inc., d/b/a Tiger Data") and redistribution has to carry its
attribution, so that vendoring has two licence files where qdrant's has one. Checked rather than
assumed that qdrant/skills ships no `NOTICE` — it does not, so that entry stays complete as is.

**A stale claim found and fixed in three files while writing this up.** `VENDORED.md`,
`docs/IDEAS.md` and this log all said the `m=0` + `payload_m` trade was blocked on *both* halves
of its precondition, because "every query reads the shared corpus alongside the tenant's own
documents". The corpus was removed on 2026-08-03 — hours after that sentence was written — so
every query is single-tenant and cross-tenant search is now impossible, not merely rare. Only the
unmeasured indexing throughput still blocks the trade. Worth noting how it survived: the sentence
was true when written, in a file nobody had reason to re-read, and the removal commit had no
reason to grep for it.

**Then a 440-skill repo, `alirezarezvani/claude-skills`, scanned end to end — and nothing taken.**
MIT and cleanly licensed, ~300 of it business content, ~137 engineering. Per-skill verdicts are in
`VENDORED.md` so nobody pays for that scan twice. Three things learned that generalise beyond it:

- **A skill that ships executable tools can be worse than one that ships prose.**
  `rag-architect`'s `retrieval_evaluator.py` computes precision@k, recall@k, MRR and NDCG — against
  a **TF-IDF retriever it implements itself**. Run it here and the numbers look like Epic 2 metrics
  while describing a system with no Qdrant, no Voyage embeddings and no reranker. Rule 11 wearing a
  CLI. Contrast `senior-prompt-engineer`'s evaluator, which takes *your* contexts and answers as
  input and so grades the real thing — right shape, still declined, because its ROUGE-L
  faithfulness is a lexical proxy where `EPIC_2_PLAN.md` chose RAGAS, and it would be a third voice
  on eval after that plan and `qdrant-search-quality`.
- **A skill can fail by re-importing something this project already dropped.** `karpathy-coder` is
  the root `CLAUDE.md`'s rules 1–4, same source — but it enforces them with a complexity checker
  thresholding on file lines, imports, nesting depth and cyclomatic complexity, and that file says
  outright the extensions "built on arbitrary thresholds" were dropped deliberately. Taking it
  would smuggle them back under the name of the rules that replaced them.
- **A skill that produces one finding and then costs context forever is a finding, not a skill.**
  `ai-security`'s scanner is regex matching over prompts, which is not this system's exposure — but
  its § *Indirect Injection via External Content* named a real gap. Verified: retrieved chunk text
  goes verbatim into Anthropic `document` blocks via `_build_document_blocks`, and **the word
  "injection" appears nowhere in `app/` or in any doc here**, so the absence was silence rather
  than a decision. Three things keep it off the urgent list — documents are tenant-scoped so the
  blast radius is self-inflicted, Epic 1 has no tools to abuse, and the `document` block is
  Anthropic's own channel for source material rather than string concatenation (that last one is
  **plausible and unverified**, and is flagged as such). Recorded in `docs/IDEAS.md` under Auth,
  with a note to re-read it at Epic 3 where the agent gets tools.

`slo-architect` was the only near miss and is parked in `docs/IDEAS.md`: good work, but SLIs,
error budgets and burn-rate alerts need production traffic and an on-call rotation to mean
anything — unlike the LangGraph skills, which needed only code to exist. That is the difference
between "install ahead of use" and "install ahead of *existing*".

No `CHANGELOG.md` entry for any of this. Nothing under `.claude/` or `docs/` changes what a caller
observes, which is the skill's own noise filter working as intended.

### 2026-08-03 (later still) — the Qdrant tenant payload index

Closed the one finding the vendored `qdrant-*` skills had produced and that had been sitting open
since they were added: **no payload index existed at all.**
`qdrant_store._ensure_payload_indexes`, called from `__init__` after the collection is created,
now indexes `metadata.tenant_id` with `is_tenant=True` and `metadata.doc_id` as a plain keyword.

The part worth remembering is not the change, it is **that this could not be tested the way
everything else about Qdrant is tested here.** `test_qdrant_filtering.py` runs against
`qdrant_client`'s in-memory engine, which warns "Payload indexes have no effect in the local
Qdrant" and reports an empty `payload_schema` — so any in-memory assertion about an index passes
whether or not the index was ever requested. Verified once against a real `qdrant/qdrant:v1.18.3`
container instead (`metadata.tenant_id` → `data_type=keyword, is_tenant=True`;
`metadata.doc_id` → `is_tenant=False`; `metadata.chunk_type` absent; a second identical call
returns `completed`, so no existence check is needed). The unit tests assert the *calls* and say
so in their docstrings rather than implying they prove the effect.

Both new tests mutation-tested: dropping `is_tenant` turns one red, and hoisting the `try` to
wrap the whole loop turns the other red (one field's failure would otherwise silently cost the
other its index).

`is_tenant` is not a synonym for "indexed", and that is the thing a future reader is most likely
to get wrong: a plain keyword index makes the filter cheap to *evaluate*, while `is_tenant` is
what makes each tenant's vectors co-located so the reads are sequential.

Two things deliberately not done, both recorded with their preconditions in `docs/IDEAS.md`:
`metadata.chunk_type` gets no index (no production caller passes `chunk_types`), and the `m=0` +
`payload_m` per-tenant-HNSW trade from `qdrant-scaling` stays untaken — it is conditional on
indexing throughput being the bottleneck *and* cross-tenant search being rare, and at the time of
writing both were false. (**Corrected 2026-08-05:** removing the corpus later the same day made
every query single-tenant, so the second half now holds. Only the unmeasured indexing throughput
still blocks it. `docs/IDEAS.md` carries the current version.)

### 2026-08-03 (later still) — the shared corpus is gone

The user asked what `app/registry/` was for, then confirmed that a tenant sees "own + global",
then said the demo corpus had no relevance and to remove it. Offered two readings -- delete the
data, or delete the concept -- and they chose the concept. Right call, and the reason is worth
keeping: the data-only version would have left `GLOBAL_TENANT` machinery unused inside the
security filter, and unused code in a filter is what a later reader mistakes for load-bearing.

**What went.** `GLOBAL_TENANT`, `scripts/fetch_corpus.py`, `scripts/ingest.py`,
`data/manifest.json`, `tests/unit/test_fetch_corpus.py`, `Settings.manifest_path`,
`Settings.raw_pdf_dir`, the `data/manifest.json` COPY in the Dockerfile, and
`registry.db.list_scope_candidates`.

**What the change actually turned on**, beyond deleting things:

1. **`_build_filter` matches one tenant with `MatchValue`, not a one-element `MatchAny`.** A list
   invites a second element, which is precisely the leak the function exists to stop.
2. **It raises on an empty `tenant_id`.** `None` used to mean "corpus only" and was *safe because
   the corpus existed*. With the corpus gone the same permissive signature would mean "no tenant
   condition at all" -- every tenant's chunks, to a caller who supplied nothing, silently, since a
   too-wide filter returns rows rather than raising. This is the sharpest instance of rule 8 this
   project has: removing the thing a default pointed at makes the default dangerous.
3. **`tenant_id` lost its default everywhere** -- `Chunk`, `chunk_document`, `ingest_document`,
   `Retriever.retrieve`, `AnswerService.answer`. The old default was `GLOBAL_TENANT`. That churned
   ~20 test call sites, which is the point: each now says which tenant it means.
4. **Two registry queries collapsed into one.** `list_scope_candidates` existed *only* because the
   corpus made "what may I scope to" wider than "what do I own". They had disagreed once already
   (H1: a 404 on every curated paper). The surviving difference is a `limit` at the call site.

**Tests: deleted where the concept went, strengthened where it did not.** Removed 4 in
`test_worker_enqueue.py`, 2 in `test_qdrant_filtering.py`, 3 corpus-CLI tests in
`test_ingest_failures.py`, and all of `test_fetch_corpus.py`. Two rewrites matter more than the
deletions: `test_tenant_cannot_reach_another_tenants_documents` now asserts the permitted set
**exactly** rather than `a in / b not in` -- the weak form passed for months while the filter also
admitted `global` -- and a new parametrized test pins the empty-tenant `ValueError`. 353 pass,
0 skipped, 0 failed.

**One consequence I nearly shipped.** `data/manifest.json` was the only tracked file under
`data/`, so deleting it left a fresh clone with **no `data/` directory** -- and compose's
`../data:/app/data` bind mount would then have Docker create it owned by root, breaking the first
upload for the non-root `appuser` with an error pointing at the application. Added `data/.gitkeep`
explaining exactly that.

### 2026-08-03 (later) — the rate limiter moved onto `limits`

The user asked why a battle-tested library was not being used, was given the tradeoff, and
called it: switch. Done, and the interesting part is what the switch cost, because "use the
library" undersells it.

**`limits` supplies counting and has no opinion about anything else.** Fail-open, the headers,
the per-loop client, and the settings-driven limits all stayed ours — and those are where all
four of this project's historical rate-limit bugs lived. The library replaced the ~45 lines that
had never broken.

**Two bugs were found during the swap that the old code did not have**, both from trusting
`limits`' output rather than checking it:

1. `get_window_stats` derives the reset as `current_expires_in % expiry` against a TTL of *twice*
   the window. Correct inside the window; at the instant one opens it computes `120 % 60 == 0`,
   so the **first request against a fresh key advertised `X-RateLimit-Reset: 0`** — retry now,
   with the budget already spent. For a low-traffic key that is the common request. Clamped in
   `_reset_seconds`, with a mutation-tested guard.
2. `limits` fails **closed**. An unreachable Redis raises out of `hit()`, so the `except` in
   `check` is now load-bearing in a way it was not before, and there is a second test for a
   failure *between* `hit` and `get_window_stats` — that window would otherwise 500 a caller
   whose budget was already spent.

**One test was deleted rather than weakened.** The concurrency test asserted that grants report
distinct `remaining` values counting down to zero. That held when one Lua call returned the
decision and the numbers together; it cannot now, because `remaining` is a second round trip.
The assertion is gone and the reason is written where it was. Under concurrency the advertised
`remaining` can disagree with what the next request is granted — a real regression, accepted.

**One test changed shape.** The window-boundary test injected a clock, which worked while the
trim was arithmetic we wrote. `limits` rolls on Redis key expiry, so a time-injected version
would pass with the mechanism entirely broken. It now uses a real one-second window and really
waits (~1.2 s of suite time) — one point on the line instead of the exact boundary.

**And an IDEAS entry went stale within the hour.** "Shorten the rate-limit ZSET member" was
written from the memory measurement, and the same measurement then argued for adopting `limits`,
which deleted the ZSET. Left struck through as an example rather than silently removed.

Gate: 372 passed / 0 skipped, three consecutive runs.

**Then the strategy was wrong, and reading the `limits` docs is what caught it.** The user asked
whether we should change strategy. `SlidingWindowCounterRateLimiter` had been chosen hours earlier
purely on memory (120 bytes/key against 1464 for the exact one) — and an approximation adopted to
save 27 MB on a 16 GB box should have been suspicious on its face. Measured properly, the counter
**does not honour its own `Retry-After`**: spend a 10-request/2-second budget, both strategies say
"reset in 2.00 s", and after waiting 2.2 s the exact one grants 10/10 while the counter grants
**2/10**, not recovering fully until 4.2 s. A client that does exactly what the header says still
gets a 429, and the natural reaction is a tight retry loop — the precise failure the sliding
window exists to prevent. Switched to `MovingWindowRateLimiter`; the `X-RateLimit-Reset: 0` clamp
became dead code and was deleted rather than left looking defensive.

Three things worth carrying forward from that:

1. **The 26× memory headline was a bad comparison** and I wrote it into four files. It put
   `limits`' *cheapest* strategy against *our* implementation. Like for like it is 2×, and the
   26× is what bought the wrong strategy. Corrected everywhere.
2. **A test with `limit=1` cannot tell "some budget returned" from "all budget returned".** The
   first version of the window test used a single slot, which the counter also returns — so it
   passed while the strategy was broken. It now spends four and asserts all four come back.
3. **Guard reliability is itself measurable.** Reinstating the counter:
   full-budget-returns red 5/5, the 1×-vs-2× TTL bound red 5/5, the fresh-window-reset test red
   only **8/10** (the modulo lands on zero only within a millisecond of the window opening). The
   third is documented as a hint, not a guard, rather than being counted as one.

**And the "run it three times" agreement was retired the same day**, because the user asked what
the third run was actually doing and the answer was "the same thing as the first". pytest orders
tests identically every run, so three passes can catch timing races and state leaking *between*
runs, and nothing about a test that passes only because another ran first -- which is the flake
the rule existed for. Worse, the two flakes that originally motivated it (a shared test database
and a `DROP SCHEMA` race) were both order flakes, found by reading the failure rather than by
repetition. Replaced with `pytest-randomly`: one pass, random order, `random` reseeded per test.
Verified it is not inert (two seeds give different collection orders) and that the suite survives
it (five seeds, 372 passed each). CI runs `-v` on purpose -- `-q` suppresses the seed line, and
without the seed a randomised failure cannot be reproduced. Locally, `--randomly-seed=last`
replays and `-p no:randomly` answers "was it the order or the test?".

### 2026-08-03 — the remaining 21 review findings, and three rounds of agent review

All 51 findings from the 2026-08-02 external review are now closed. The batches, and the
verification each survived, are in the commit bodies (`35f9c3d`, `4731f2c`, `a2b91d1`, `4ed76b5`,
`360fb1f` and the follow-up). What belongs here is what the *reviews of my own fixes* found,
because the pattern repeated three times and is the transferable part:

**Every round of agent review found a defect in the previous round's fixes, including one
critical.** Not diminishing returns -- round 3 was the most valuable. In order:

1. My M8 caption cache was keyed on `figure_id` and therefore **collided** rather than missed: a
   newly-inserted figure was handed the caption written for whatever used to sit at its index. My
   docstring asserted the opposite in as many words, and the test *named* for that property
   asserted only call counts and ids, which a collision satisfies. Now content-addressed.
2. Then the content-addressed version deduplicated only against the cache on disk, not within a
   batch -- so a logo on ten pages still cost ten calls on the first ingest and got ten
   *different* captions. My test pre-warmed the cache, so it could not see it. Same construction
   flaw as (1), one commit later.
3. My table-caption dedup compared `caption in markdown`, and docling's serializer escapes `_` as
   `\_` and HTML-escapes `&`/`<`/`>` -- so three of six realistic scientific captions still
   doubled. The test counted raw occurrences, which stays 1 when the second copy is escaped.
4. `truncated` was forwarded to `AskResponse` by one line that no test covered: deleting it left
   the whole suite green while every truncated answer reported as complete.
5. Unifying the two `_state` renderers averaged a real difference (the Streamlit page has its own
   date columns) instead of surfacing it -- rule 6, in a commit whose message cited rule 6.

**The transferable lesson:** a test that asserts *cost* (call counts) or *shape* (ids, lengths)
passes under a correctness bug. Assert content, and make the fixture able to distinguish wrong
content from right -- captions derived from the input, not from batch position.

**Also learned about the tooling:** four of the ~40 numbers I wrote into comments this session
were wrong on checking (`libssl3` "a few hundred KB" -- it is already in the base image;
"six transitive packages" -- two; "32-char doc_id" -- 65; "hangs with no timeout" --
`huggingface_hub` sets a 10s ETag timeout). Rule 13 applies to prose in comments, not just to
dependency claims.

**Standing gaps this session did not close:** whether Anthropic truncates the *citation list*
along with the text under `max_tokens` is asserted in three places and unverified; and the nginx
image's `apt-get` layer cannot build behind this sandbox's proxy (the config itself is proven to
parse via `nginx -t` inside `nginx:1.29`).

**`streamlit` publishes on `0.0.0.0` on purpose** -- `api` and the three data services were moved
to `127.0.0.1`, and an earlier version of this entry listed `streamlit` with them as an open gap.
It is not one: nginx proxies only `portfolio_api`, so loopback-binding 8501 would make the UI
SSH-tunnel-only, and the page renders nothing before a key is pasted. The reasoning now lives on
the `ports:` block itself. What *is* still open is fronting it with nginx, so it inherits the
timeouts, body-size cap and security headers the api gets only by sitting behind the proxy.

**The smoke job had never actually run its assertions, and hid a real stack bug.** Worth reading as
one story, because the first cause masked the second:

1. Two runs died at `Bring the stack up` in ~5 seconds on
   `Post "https://auth.docker.io/token": read: connection reset by peer` -- an anonymous Docker Hub
   token flake pulling `python:3.14-slim`, not our code. It reds the one job that builds the images
   and skips every assertion below it, so the step is now retried three times, then `::error::`.
   Verified against a stub `docker`: 1 invocation on success, 3 then exit 0 when the first two
   fail, 3 then exit 1 when all three do.
2. With that noise gone the run got 7m41s in and failed for real:
   `failed to mkdir /var/lib/docker/volumes/portfolio_model_cache/_data/torch: file exists`.
   **The Dockerfile pre-created `huggingface/` and `torch/` inside the `model_cache` mount point.**
   Content at a mount point is copied into a fresh named volume during container *create* (not
   start), and `api`, `worker` and `streamlit` all mount that one volume, so their creates raced
   the copy. The mount point itself must stay -- Docker applies its ownership to the volume root,
   and a root-owned mount point leaves appuser unable to cache anything -- but its *contents* must
   not: `huggingface_hub` and `torch.hub` both `makedirs(exist_ok=True)`, so pre-creating them
   bought nothing.

Both reproduced rather than reasoned about. Six concurrent `docker create` on a fresh volume with
two empty dirs at the mount point → EEXIST; with the mount point empty → 48 concurrent creates,
zero errors, `_data` still `appuser:app`, `mkdir -p torch/hub` still works from inside.

**The race fired once in eight rounds**, which is the part that matters for CI: a green bring-up
would not have told us a re-added `mkdir` was safe. So the guard is not the bring-up -- it is a
deterministic step asserting `/home/appuser/.cache` is empty in the built api image, red against
the pre-fix image and green against the fixed one.

**And this is what the smoke job is for.** Four commits of fixes went in while the only job that
builds the images had failed at step 6 every time. Nothing else in the gate can see a
compose/Dockerfile interaction -- `docker compose config` parses compose, and unit tests never
build an image. A red job whose cause was dismissed as "just a registry flake" is rule 12 wearing
different clothes.

**Confirmed green on `141a52c`** -- the first run in which this job executed its assertions rather
than dying at step 6. Every one passed: the mount point is empty in the built image, `/health/ready`
returned 200 on the *first* poll with postgres, qdrant and redis all reachable from the api
container, nginx's generated upstream proxies, auth is enforced through the proxy, and the worker
claimed its queue. Measurements for the next session: the cold image build is **7m35s** (torch +
Docling dominate), the whole job 7m52s, and the four other jobs finish in 2m20s. So a `main` push
is green in ~2.5 minutes and *fully* green in ~8.

### 2026-08-02 — an external review of 51 findings, and two rounds of fixing it

The user had another Claude Code session audit `portfolio/` and pasted the report: 1 critical,
6 high, 21 medium, 23 low. **It was accurate** -- 14 findings spot-checked against the code,
all 14 held. Treat that report as trustworthy if it comes up again.

**Fixed so far (30 of 51):** C1, all six H, M3 M4 M10 M11 M12 M15 M16 M18, L1 L9 L11 L15.
Commits `e23e499`, `7e7df28`, `4731f2c`.

**Two agent reviews of my own fixes, both of which found real defects in them.** Worth
repeating the pattern rather than the details, because both were the same mistake:

1. My H2 fix (filename scoping across spaces/parens) passed its test and **did not work**.
   `mentions_a_document` is a gate `/ask` early-returns on; I widened the resolver and left
   the gate narrow, and the test called the resolver directly. There is now a test that
   drives gate and resolver together.
2. Seven fixes were **mutation-vacuous** -- revertible with the suite green -- including the
   headline H4 handler, one commit after I had invoked rule 15 against someone else's vacuous
   test. Six now go red under mutation. M18 (Streamlit) stays unverifiable: no test harness.
3. A docstring I wrote confidently was **false**: registering a handler for bare `Exception`
   does not put it inside `CORSMiddleware` -- Starlette installs it *as* `ServerErrorMiddleware`,
   the outermost layer. Measured, then corrected.

**The suite was flaky and that invalidated every earlier "green".** Runs varied 230-234 on an
unchanged tree. Two causes: M4 (one fixed key id bucketed against real Redis, so tests began
429ing once the file grew) and `test_concurrent_processes_can_initialise_the_schema` running
`DROP SCHEMA public CASCADE` on the shared test database while three subprocesses raced to
rebuild it. That test now gets a throwaway database of its own; the other three DB suites
truncate instead of dropping, at setup as well as teardown. **Five consecutive runs: 249
passed, 0 skipped.** (The "run it three times" advice that closed this entry was replaced on
2026-08-03 by `pytest-randomly` -- see that day's log entry. Those two flakes were *order*
flakes, which is exactly what three identically-ordered runs could not have found; they were
caught by reading the failure, not by repetition.)

**Found while fixing, not in the report:** `X-RateLimit-*` vanished on every `APIError` path
(404/422), because the handler builds a fresh response and only the 429 passed its own copy.
Now stashed on `request.state` and re-attached.

**Left (21):** M1 (the user is doing this one), M2, M5-M9, M13, M14, M17, M19-M21, and the
L-tail L2-L8, L10, L12-L14, L16-L23.

**M1 is bigger than "unused dependencies".** `googlemaps`, `pyzbar`, `brightdata-sdk`,
`playwright`, `cairosvg`, `cssutils` are *smads_ai's* dependency set (pyzbar decodes the QR in
its `company_info.py`, googlemaps drives its `google_places.py`), and `[project.urls]` points
at `github.com/cs83/smartico-ai`. The manifest was copied from that project, so classifiers,
description and author are suspect too -- it wants rewriting, not pruning.

### 2026-08-02 — scopes, per-key rate limits, key CRUD, 30-day default expiry

Four asks in one turn: 30-day default expiry from a 30/60/90/365/never menu; scopes as
"option B", a scope set checked per route; 403 for scope failures; rate limiting per key. Plus
a mid-turn fix: `--revoke` looked keys up by id alone with no tenant check.

**Shape.** `app/auth/scopes.py` holds the vocabulary and the pure comparison functions
(`granted`/`has_scope`/`unknown_scopes`/`exceeds`). `Principal` (tenant, key id, scopes) came
out of `resolve_principal`; `resolve_tenant` is now a thin wrapper, kept because most callers
genuinely only want the retrieval scope. `require_scopes` in `deps.py` checks per route.

**Three things that are easy to get wrong and are now pinned:**

1. **An empty scope list means *every* scope.** Keys minted before the column existed have no
   list. Reading `if not key.scopes` as a denial would have revoked all of them.
2. **…which makes an omitted list on `POST /v1/keys` an escalation.** `exceeds([], holder)` is
   vacuously empty, so the guard never fires, and storing `[]` means unrestricted — a
   `keys:write`-only key could mint itself an unrestricted one. The route materialises an
   omitted list into the caller's own scopes.
3. **Overriding `current_tenant` in tests no longer authenticates anything.** `require_scopes`
   and `rate_limited` both hang off `current_principal`, so the seam moved. Five contract
   tests failed exactly this way; the `add-endpoint` skill was corrected.

**`require_scopes` became a callable class**, purely so the route table is introspectable: a
closure hides its requirement in a cell, and `test_scopes.py` walks every route and fails on
any `/v1` route with no requirement — the assertion a newly added route silently falsifies.

**Key CRUD lives in `app/auth/management.py`, not the router.** The Streamlit page
(`streamlit_app/pages/1_API_keys.py`) manages keys in process, exactly as `Home.py` ingests in
process, so the escalation guard and the tenant filter had to be one implementation. The router
is now only the translation from refusal to status code. Same reasoning as
`ingestion/uploads.py`, and it raises its own exceptions rather than `APIError` for the same
reason.

**Verified beyond the suite:** the Streamlit page driven end to end with `streamlit.testing.v1`
against real Postgres (authenticate → list → mint with `["ask"]` and 90 days → the row in
`psql` shows `{ask}` and 90 days), and all three CLI revoke paths (no `--tenant` refuses, wrong
tenant refuses, right tenant revokes). The smoke tenant was deleted afterwards; `apikey` is
empty again.

Schema: `apikey.scopes varchar[] NOT NULL DEFAULT '{}'` added by hand-written `ALTER` on the
dev database (`create_all` does not add columns — see the entry below).

### 2026-08-01 — key expiry, and the API key declared in OpenAPI

`ApiKey.expires_at` added, `NULL` = never. Checked in the `WHERE` clause beside the revocation
check, using `func.now()` — the *database's* clock, so a skewed api process cannot honour a key
past its deadline. Expired reads as unknown, same as revoked. CLI gained `--expires-in DAYS`
and a `_state()` column; it now says out loud when a key has no deadline.

**Deliberately opt-in, not the default.** Defaulting to a deadline is the safer policy and is
recorded in `docs/IDEAS.md` as a decision still to take.

**Operational trap worth remembering — now in `CLAUDE.md`:** `create_all` creates missing
*tables*, never missing *columns*. Adding a field to an existing model changes nothing;
`init_db` reports success and the next query fails with `column ... does not exist`. With no
Alembic, a new column means dropping the table or hand-writing the `ALTER`. `apikey` was empty,
so it was dropped and recreated.

Also, from a mid-session question: the key is now an `APIKeyHeader` security scheme rather than
a bare `Header()` parameter, so `/docs` has an Authorize button and a generated client models
it as a credential instead of a per-call argument. `auto_error=False`, or FastAPI's own 403
would make an absent key distinguishable from an invalid one. Three contract tests pin it.

Tests were mutation-checked: deleting the expiry clause fails 3 of them.

### 2026-08-01 — key format: base62 + CRC32 checksum

Read three sources on API key design (GitHub's 2021 token-format post, Zuplo, jamdesk) and
compared them line by line against what exists. **Most of what they recommend was already
done** — CSPRNG entropy, prefix, hash-only storage, show-once, display prefix, indexed unique
hash, `last_used_at`/`revoked_at`, per-key rate limiting, and the no-bcrypt reasoning that two
of the three explicitly endorse. Confirmation, recorded in `docs/TECHNICAL_DECISIONS.md` so
the next review doesn't redo the comparison.

Three things changed, all free because `apikey` is still empty: base62 instead of base64url
(`-` truncates a double-click selection, so a user copying a key gets a fragment and an opaque
401), a 6-character CRC32 checksum, and a matching gitleaks rule. Key is now 57 characters.

**The checksum is an integrity check, not a security control** — CRC32 is not cryptographic
and anyone can compute a valid one. It buys offline rejection of typos and fabrications
(1-in-2³² false accept), nothing more. A test pins that reading, because the dangerous
misunderstanding is one upgrade in someone's head away.

Still not built, and the only real gaps the review found: **key expiry** and **scopes**
(`docs/IDEAS.md` § Auth).

### 2026-08-01 — API key review: shape check tightened, hash moved to SHA-512

An external review of `app/auth/keys.py` produced three suggestions. One was taken (exact-
length shape check — the old `len > 16` let a prefixed multi-megabyte body reach the hash).
Two were rejected with reasons now in `docs/IDEAS.md`: an HMAC pepper (right advice, wrong
threat model — and it can never be rotated, because re-deriving digests needs the plaintext
keys) and `BYTEA` storage (under 1 MB saved at target scale, against an unreadable column and
a hand-written migration with no Alembic). The review's real value was the two gaps it
surfaced in passing: **no key expiry and no scopes**, both now in `docs/IDEAS.md` § Auth.

Then hashing moved SHA-256 → **SHA-512** at the user's request. Recorded here because the
timing was the whole decision: the `apikey` table had **zero rows**, verified before changing
anything, so this was free. At any other time it is a full re-key of every tenant — plaintext
keys are never stored, so no digest can be recomputed. **`hash_key` is now frozen**, pinned by
a test asserting a known key's exact digest. Reasoning and the two rejected alternatives
(SHA-512/256, not in `hashlib`'s guaranteed set; SHA-3, slower for a property we don't use)
are in `docs/TECHNICAL_DECISIONS.md`.

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

### 2026-08-01 — filename in chunk metadata ([`85ff4e2`](https://github.com/stanimirdim92/llms/commit/85ff4e2))

(This entry was titled "redis image pinned, filename in chunk metadata" and never mentioned the
redis pin. The reasoning for that pin is real and lives in `redis/Dockerfile`'s own comment,
which is the right place for it; the title has been trimmed to what the body actually covers.
A log entry promising something it does not deliver is worse than a shorter one, because the
next reader searches for it and concludes it was never written down.)

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
