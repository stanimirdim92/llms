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
- **Monetizing the app is now the plan (2026-08-07), not a maybe** — firmer than the hosting signal
  above, and it upgrades the "lower priority, don't build yet" items from the tenant-architecture
  review from speculative to genuinely on the roadmap: a user/role layer distinct from the
  API-key-is-the-tenant model (Phase 5.2's open question), an audit log, tenant-tiered rate/quota
  plans and billing hooks, and a siloed-deployment escape hatch for a customer who can't share
  infrastructure. None built yet. Row-level security (this session) and backups (above) both move
  up the list for the same reason a paying customer's data raises the cost of getting either wrong.
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

   **Answered, mostly, 2026-08-06.** A session started at the repo root listed *only* the built-in
   agent types (`claude`, `Explore`, `general-purpose`, `Plan`, `claude-code-guide`,
   `statusline-setup`) — none of the six in `portfolio/.claude/agents/`. So walk-up discovery is
   real and the definitions are invisible from a repo-root session, exactly as predicted. The
   delegated sweep that session had to run as `general-purpose` with the brief written inline, which
   worked well but pays none of the definitions' accumulated false-positive suppression. Still
   unmeasured: whether a session started **in `portfolio/`** sees them; that is the other half, and
   the decision (move to repo root vs. always start in `portfolio/`) waits on it. Cheap test: start
   a session there and read the agent list.
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

### 2026-08-07 (night) — two composite indexes, measured against a whale tenant rather than the average

Asked to follow up on "db performance is a must" from an article comparison, specifically a
composite `(tenant_id, created_at)`-style index suggested by that article for a similar table.

**The scale target itself was the wrong benchmark, and measuring first caught it.** Seeded
exactly this project's own standing target — 10,000 tenants × 10 documents — and both candidate
queries (`list_active_versions`, `list_document_records`) ran under 0.25ms on the existing
single-column `tenant_id` index alone, because 10 rows is nothing to filter or sort regardless of
indexing. An *average* of 10 documents/tenant is not the case that matters once monetization means
real, unevenly-sized tenants — so added one deliberate 20,000-document "whale" tenant and remeasured
against that. Real numbers, warmed up (repeated runs, not the first cold one -- rule 14):
`list_active_versions` 6.06ms → 2.2-3.9ms, `list_document_records` 6.04ms → 0.39-0.56ms. The gap
between those two improvements is structural, not incidental: the second query has a `LIMIT`, so
an index in output order lets Postgres stop after 100 rows; the first has none, by design (the
retrieval filter needs every active document's id), so indexing removes the heap I/O but not the
work proportional to the tenant's own document count. Recorded as a standing limit in
`docs/TECHNICAL_DECISIONS.md`, not something this pass fixes.

**Migration `c7e2a9f13b58`: a partial covering index and a plain composite.**
`ix_documentrecord_tenant_active_version` matches `list_active_versions`'s exact predicate
(`tenant_id`, `INCLUDE (doc_id, ingestion_version)`, `WHERE status = 'ingested' AND
ingestion_version IS NOT NULL`) for an index-only scan; `ix_documentrecord_tenant_uploaded_at` is
`(tenant_id, uploaded_at DESC)` for `list_document_records`. Confirmed the average-case tenant is
not regressed — both queries still resolve in well under 0.25ms there, and the planner picks
whichever index it judges cheaper without being told to.

**A second migration-transaction constraint found, this time before it caused damage.**
`CREATE INDEX CONCURRENTLY` is disallowed inside a transaction, and `init_db()` deliberately runs
the *entire* migration chain inside one transaction (the advisory lock has to cover it atomically)
— so `CONCURRENTLY` is not just unused here, it is currently *impossible* through this migration
path at all. Used plain (blocking) `CREATE INDEX` instead, since there is no production data yet,
and wrote down exactly what changes the day there is: a real deployment with live traffic needs
`CONCURRENTLY` run outside this chain, not a migration that runs unattended at boot. Same shape as
the RLS role split two entries below -- a constraint this project's own architecture creates,
worth stating rather than working around silently.

**A new existence test, not a performance test.** `test_the_tenant_hot_path_indexes_exist`
(`tests/unit/test_migrations.py`) asserts the two indexes are present after `init_db()`, and says
in its own docstring why it doesn't assert a timing number: a benchmark depends on hardware, cache
state and data shape in ways a merge gate can't control for, and the measured numbers belong in
`docs/TECHNICAL_DECISIONS.md`, read once, not re-derived by CI on every run. Mutation-confirmed by
removing one index from the migration and watching the test name it specifically.

**Verified the same way as the RLS work**: a real `postgres:18-alpine`, seeded via raw SQL
(`generate_series`, not the ORM — 130,000 rows through SQLModel would have taken the actual
measurement time), migrated through the real Alembic chain rather than by hand-applying the SQL,
then re-measured to confirm the migration produces the identical plan the ad-hoc index did. Full
suite: 391 passed, 0 skipped (390 plus the new test). `ruff --no-cache`, `ruff format --check`,
`ty check` all clean.

**Cross-checked against two external sources the user shared, both worth the check.** A FastAPI+RLS
blog post's example code (`SET LOCAL app.current_tenant = :tid`, with a bind parameter) fails on
real Postgres with the identical error class this session already hit once for `ALTER ROLE ...
PASSWORD` -- `SET` is a utility statement, not DML, and doesn't accept a placeholder in that
position. Confirmed by running it. `set_config(name, value, is_local)`, used here, is a plain
function call inside a normal query and *is* parameterizable -- documented as equivalent to `SET
LOCAL` in effect, but only one of the two forms is actually safe to write with a bound tenant_id.
The same post's `BYPASSRLS`-only admin role (distinct from a superuser, kept for a cross-tenant
admin-reporting feature this app doesn't have) is a cleaner pattern than this project's reliance on
`postgres_user`'s *incidental* superuser status -- noted as the right move if a genuine cross-tenant
admin feature is ever built, not retrofitted now since migrations here need full DDL rights
`BYPASSRLS` alone wouldn't grant anyway.

### 2026-08-07 (evening) — row-level security, a second Postgres role, and a structural regression test

Asked directly, independent of this project's own docs, whether there's a better production/
enterprise way to do tenant isolation than the pure application-level filter. Answer: the
application filter is the correct *first* layer and stays; what's missing is a database-enforced
second layer, so a query that forgot its own tenant check leaks nothing instead of leaking rows.
Implemented both pieces the user asked for.

**Row-level security on `documentrecord`** (migration `a4f8c1d92e07`), and the one fact that
decides the whole design: **Postgres superusers bypass RLS unconditionally, `FORCE ROW LEVEL
SECURITY` included** -- and the official postgres image always makes `POSTGRES_USER` a superuser.
A policy on a table whose queries run as that role would pass its own smoke test for the wrong
reason. So this needed a genuinely new, non-superuser role (`app_db_user`) that every
request-time query now connects as (`app/db.py::get_engine`, used by `get_session()`, api and
worker alike), while `get_admin_engine()` keeps `postgres_user` for Alembic and procrastinate's
one-time schema apply. That's a real reversal of `../CLAUDE.md`'s "one set of Postgres
credentials, don't reintroduce a parallel `DB_USER`" rule -- recorded as a stated exception
there and in `docs/TECHNICAL_DECISIONS.md`, not a silent one: that rule was about two names
drifting apart for the *same* credential, and this is a second credential for a different job.

**`app/registry/db.py::_set_tenant_context`** (`SELECT set_config('app.tenant_id', tenant_id,
true)`) runs first in every function touching `documentrecord`, centralized in the module that
already owns every query there. Two functions had never taken `tenant_id` at all --
`mark_document_processing`/`mark_document_failed` (`_set_status`) looked up by `doc_id` alone,
safe only because `upload_doc_id` makes it globally unique, not because the WHERE clause said so.
Now both take `tenant_id` and filter by it, matching every other function here, and `worker/
tasks.py`'s two call sites were updated to pass it (`tenant_id` was already sitting in scope,
unused for this).

**Two real mistakes, caught before landing rather than after:**

1. `ALTER ROLE ... WITH PASSWORD :password` doesn't accept a bind parameter -- it's DDL, and
   Postgres's wire protocol has no placeholder support there. Failed with a syntax error
   pointing at the placeholder itself rather than explaining why. Fixed with proper SQL-literal
   escaping (doubling embedded `'`), safe here because the value is an operator-controlled
   deployment secret, not request input.
2. My own mutation test for the `WITH CHECK` clause was wrong before it was right: I claimed
   deleting `WITH CHECK` (keeping `USING`) would let a cross-tenant insert through, and mutating
   it that way left the test **green**, not red. Postgres defaults an omitted `WITH CHECK` to the
   `USING` expression for a policy covering every command, which this one does -- so the clause
   I wrote is documentation, not the thing actually stopping the write. Found the real gap
   (`WITH CHECK (true)`, which overrides the default with a permissive one) and rewrote the
   test's own docstring to say so, rather than leaving a passing mutation test whose stated
   reasoning was false. This is rule 15 catching itself: a test that would pass with its own
   claimed guard deleted is documentation, and the mutation is what proved it.

**Structural enforcement, the other half of what was asked** (`tests/unit/
test_structural_boundaries.py`, no Postgres needed): an AST sweep asserting `DocumentRecord` is
queried (`select`/`update`/`delete`/`session.get`) from `app/registry/db.py` alone. Deliberately
narrower than "never reference `DocumentRecord`" -- an early version flagged `streamlit_app/
Home.py` and `documents.py` for legitimately *constructing* a row to pass to
`stage_document_record`, which is not the risk this test exists to catch. Mutation-confirmed by
injecting a throwaway `select(DocumentRecord)` into `documents.py` and reverting.

**A pre-existing gap found in passing, not fixed:** `../CLAUDE.md`'s connection-budget arithmetic
(`GUNICORN_WORKERS * (db_pool_size + db_max_overflow)`) didn't account for the new admin engine's
own small pool. Noted in `docs/EPIC_4_PLAN.md` rather than recalculated precisely -- in practice it
holds at most the one or two connections `init_db()` checks out once per process, but the ceiling
is real and this arithmetic should be re-derived if the exact number ever matters.

**Verified against a real Postgres**, brought up directly in this sandbox for the purpose (not
via the `verify` skill, which is reserved for explicit user invocation) -- `postgres:18-alpine` +
`redis:8-alpine`, both test databases created by hand. Full suite: **390 passed, 0 skipped**,
including the three `test_api_contract.py` tests that could only fail-for-lack-of-services before
this session (now genuinely passing against live infrastructure). `ruff --no-cache`, `ruff
format --check`, and `ty check` all clean. One `ty` wrinkle worth remembering:
`session.exec(text(...))`'s typed overloads don't cover a plain `Executable`, and SQLModel's
`session.execute()` carries a `@deprecated` decorator that `ty` treats as an error under this
project's `error-on-warning` -- the fix was `(await session.connection()).execute(...)`, the
plain SQLAlchemy `AsyncConnection` underneath, which SQLModel doesn't wrap at all.

**Standing directive updated:** the user said monetization is planned, which is why the "lower
priority" items from the earlier architecture review (user/role layer, audit log, tenant-tiered
quotas, a siloed-deployment tier) are staying on the list rather than being deprioritized as
speculative -- none built this session, all still open.

**Not done, named rather than dropped:** a startup assertion for the connection-budget ceiling
(already flagged before this session, unrelated to RLS); re-deriving the exact new ceiling with
the admin engine included; deciding whether `BLE001`-style blind-except detection should actually
be turned on now that it demonstrably already is (a live question from the ruff mistake earlier
today, not resolved here).

### 2026-08-07 (later) — the deferred doc-bloat cleanup, and a stale claim my own prior commit repeated

Asked to do the bloat-reduction pass `MEMORY.md` deferred on 2026-08-05 (~250 lines in
`TECHNICAL_DECISIONS.md` § rate limiting, ~75 here re-narrating the rate-limiter swap, 113 lines
of superseded Phase 1 plan in `EPIC_4_PLAN.md`, fifteen cross-file duplicate clusters). Re-measured
rather than trusted the two-day-old count, per rule 13 — this project's own habit of re-deriving
rather than believing a prior number paid off immediately (see below).

**What actually moved:** `EPIC_4_PLAN.md` 690 → 590 lines (Phase 1's superseded original-plan
appendix collapsed from ~112 lines to a 10-line pointer at current code; its 1.7/1.8/Verification
subsections deleted outright — `test_auth_scoping.py` was never created, the real file is
`test_tenant_scoping.py`, so that appendix wasn't just stale, it named a file that doesn't exist;
Phase 5.1's own original-plan section similarly condensed; the "Risks" section lost four
Phase-1 risks that are resolved and one procrastinate-migration risk that Alembic's adoption
already closed). This file's own rate-limiter-swap entry: 76 lines → 14, pointing at
`docs/TECHNICAL_DECISIONS.md` § Rate limiting where every fact in it now lives in fuller form.
`TECHNICAL_DECISIONS.md` itself: removed a near-verbatim `MaxConnectionsError` repeat, a
dangling self-referential note ("this paragraph said X" pointing at itself, post-correction),
and one of three restatements of the 26×-vs-2× memory correction. `CLAUDE.md`'s Postgres-only
and Docling-import-measurement failure contracts now point at `TECHNICAL_DECISIONS.md` for the
"why" instead of restating it — consistent with the document-set's own split, which CLAUDE.md
apparently doesn't yet follow for every entry.

**Delegated the cross-file sweep** (11 files, excluding this one and `.claude/`) to a read-only
agent rather than eyeballing ~3,150 lines myself — a textbook wide-shallow-fixed-question case.
It found the "document set" table claim doesn't reproduce inside the files it scanned at all —
the 2026-08-05 "five places" count was almost certainly counting root `/home/user/llms/CLAUDE.md`
and this file, both excluded from that sweep's scope, so a fresh full-repo sweep would be needed
to actually close that item. It confirmed Postgres-only (6 locations, not the claimed number
either) and the Docling-import measurement (4, not ~6), and surfaced five more clusters of the
same shape not on the original list (tenant-isolation core sentence, the `session_id`
vulnerability history, Qdrant point-id UUID requirement, the corpus-removal narrative, the
`MovingWindow`-vs-Counter measurement). Only the top two and one light trim got fixed this
session — the rest are named above for whoever picks this up next, not because they're wrong to
fix, but because this pass already ran long and every edit needs the same "does this actually
still say the true thing" check the next finding required.

**The finding that mattered more than the line count.** While fixing `EPIC_4_PLAN.md`'s stale
Phase 1 appendix, read the actual `POST /v1/documents` handler to check a claim before deleting
it, and it does exactly what Phase 5.1 says: writes the file and returns 202, no Docling call in
that process at all. That made three separate documents' stated reason for `GUNICORN_TIMEOUT`
provably false — "ingestion is synchronous today" — including **my own commit from earlier
today**, which raised the same claim forward without checking it against Phase 5.1 having shipped
the same day the timeout was last bumped. Docling's own `document_timeout=90` (hardcoded in
`app/ingestion/parser.py`) is what actually bounds a large-PDF parse now, and it runs in `worker`,
which has no gunicorn timeout at all. Corrected in `.docker/Dockerfile`, `.env.example`,
`CLAUDE.md` and `TECHNICAL_DECISIONS.md` — flagged as "looks vestigial, not silently changed",
since lowering a value the user just deliberately set is a different call than documenting it
accurately, and this file doesn't get to make that call unilaterally.

**Not done, named rather than silently skipped:** clusters A/B/D from the sweep (tenant-isolation
sentence in README+CLAUDE.md, the `session_id` vuln history in 3-4 files, the corpus-removal
narrative in 3 files); the "document set" table's real duplicate locations, which need a sweep
that includes root `CLAUDE.md` and this file; and the pre-existing `ruff check` failure (10
`RUF100` "unused noqa" errors, confirmed present with this session's changes stashed out —
unrelated to anything touched here, not investigated further).

**Verification:** no application code touched. `docker compose config` against a throwaway `.env`
(never committed) came back clean. `ruff check .` fails, but identically with this session's diff
stashed — see above, not this session's regression.

**Addendum, same session, asked to keep going — and a mistake made and then caught.** First
attempt: diagnosed the ten `RUF100` "unused noqa" errors as `ruff.toml` never having selected
`BLE` (flake8-blind-except), reasoning that `B` (bugbear) is a different plugin. **Wrong.**
`ruff`'s `extend-select` matches by raw *code prefix string*, not by plugin identity, so `"B"`
also matches `BLE001` — it is not bugbear-only. Removed the ten `# noqa: BLE001` comments by
hand (preserving the reasoning after `--`, unlike `ruff --fix`, which deletes the whole comment)
and got "All checks passed!" — which was `.ruff_cache` serving a stale result, not the true
state. Caught only because a *later*, unrelated task (reviewing `add-endpoint`) happened to
re-run `ruff check` on a single file and got a different answer than the just-checked whole
project; `rm -rf .ruff_cache && ruff check --no-cache .` settled it: all ten sites are real
`BLE001` violations, correctly suppressed the whole time. **Reverted** — all ten `# noqa:
BLE001` comments restored verbatim, verified clean with `--no-cache` this time. The commit that
removed them (`d1e1742`) is wrong and superseded by the revert; not force-rewritten since it was
already pushed to `main`. Whether `BLE001` should actually be enforced project-wide, now that
it demonstrably already is, was never the question here.

**The lesson worth keeping:** "All checks passed" from a tool that caches is not the same claim
as "all checks passed against the current state," and the difference is invisible until a second,
unrelated run exposes it. `--no-cache` (or clearing `.ruff_cache`) is the honest way to ask ruff
the question this project actually needs answered after an edit that could change lint results.

Then, on the *actual* remaining work: re-checked clusters A/B/D from the sweep before cutting
them, and didn't. `README.md`'s tenant-isolation sentence serves a first-time reader who
shouldn't have to open `CLAUDE.md`, and `CLAUDE.md`'s corpus-removal and tenant-boundary entries
are condensed failure-contract context (6-8 lines, not near-verbatim copies of
`TECHNICAL_DECISIONS.md`'s longer version) — the same "already right-sized" shape the 2026-08-05
sweep found for `document_scope.py` and `qdrant_store.py`. Not every flagged duplicate is bloat;
these earn their repetition.

Gate, with the noqa comments correctly back in place: ruff clean (`--no-cache`), ty clean,
`pytest tests/unit` — 313 passed, 68 skipped, 3 failed. The 3 failures (`test_api_contract.py`,
budget/header assertions) need a live Postgres/Redis this sandbox doesn't have and are **not**
among the six documented skip-guarded suites, so they fail outright rather than skip; confirmed
identical via `git stash` with this session's changes removed, so pre-existing and not
investigated further. The `verify` skill was not invoked to work around this — it's reserved for
explicit user invocation and its workflow isn't to be replicated by other means.

**Then asked whether `add-endpoint` is correct, especially the tenant part — it is, verified
against source.** Item 5's WHERE-clause reasoning and item 7's 404-vs-403 claim both match
`get_document_record`'s docstring, `upload_doc_id`'s actual salting, `PATTERNS.md` §2, and
`test_naming_an_unowned_document_is_404_through_http` exactly. One real regression found in the
process, in code the skill points to rather than in the skill itself:
`test_worker_enqueue.py::test_the_flip_cannot_publish_into_another_tenants_row` still opened with
"`doc_id` is a content hash, so two tenants uploading the same file share one" — the exact false
claim `PATTERNS.md` §2 documents as corrected on 2026-08-05, quietly reintroduced in a test
docstring a markdown-only sweep would never reach. Fixed. Also tightened the skill's item 4,
which read as if `require_scopes` comes `from app.auth.scopes` — it's in `app.api.deps`; only the
scope constants live in `app.auth.scopes`.

### 2026-08-07 — reviewing the user's manual commits, and a timeout number that drifted twice in one day

Handoff session, asked to check seven commits that landed on `main` outside a documented session
(one Claude "fixes" commit with no write-up, and the user's own `23b0a79`). Real bug fixes among
them checked out (`e7e5ba6` postgres healthcheck, `6a7f6f0` Streamlit commit-vs-stage), but
`GUNICORN_TIMEOUT` moved three times the same day -- 600s to 100s (`c92a30a`) to 120s (`23b0a79`,
"to improve large PDF processing") -- and only the running config caught up. Found by reading, not
by a report: `CLAUDE.md`'s own "Timeouts are one value, not three" bullet said **190s in one
sentence and 100s in the next**, `docs/TECHNICAL_DECISIONS.md` said 100s throughout, and
`.docker/nginx/Dockerfile`'s `ARG REQUEST_TIMEOUT` standalone default said 630 -- which is not a
timeout value that was ever current, it looks like the new `--graceful-timeout` number (also
630, also new that day) landed in the wrong ARG. None of it was live-dangerous, because compose
always passes the real value as a build arg and overrides nginx's own default, but it is the same
"a count that disagrees with its own list" failure this project flagged on 2026-08-05, now with
timeouts instead of comment counts.

**Fixed:** the nginx `ARG` default (630 → 120), the Dockerfile's own CMD comment (was still
arguing for raising *to* 120 while the flag already read 120), `CLAUDE.md` and
`TECHNICAL_DECISIONS.md`'s prose (both now say 120s, consistently), and documented
`GUNICORN_GRACEFUL_TIMEOUT` for the first time -- it was a real, functioning env var with zero
mention in `.env.example`, `CLAUDE.md`, or `TECHNICAL_DECISIONS.md`. Its default (630s) is stated
as *unjustified* rather than given a made-up reason: the only real constraint is `>=
GUNICORN_TIMEOUT`, and 630 happens to satisfy that today by coincidence, not derivation. `CHANGELOG.md`
gained the `#### Changed` entries neither `c92a30a` nor `23b0a79` had written.

**Not done, and asked about but not resolved:** the larger doc-bloat cleanup `MEMORY.md` deferred on
2026-08-05 (duplicate clusters, ~250 redundant lines in `TECHNICAL_DECISIONS.md`, ~75 here) -- the
user said "stuck" rather than scoping it, so only the concrete drift above was fixed. Whether pushes
this session go to `main` (this file's standing directive) or the session's designated branch is
also still unresolved; pushed to the branch as the conservative default.

**Verification:** no application code changed, so ruff/ty/pytest are unaffected by this pass.
`docker compose config` was run against a throwaway `.env` copied from `.env.example` (this repo
has no committed `.env`, and compose's own README warns `--env-file` is not optional) and came
back clean; the throwaway file was deleted immediately after, never committed.

### 2026-08-06 (night) — the Streamlit upload was broken by my own change, for one commit

Reported from a genuine first run: `DocumentNotFoundError: no document row for ...`, Qdrant holding a
collection with points, Postgres holding nothing. **Streamlit only; the API path was fine.**

**Cause, entirely mine.** When `ingest_document`'s terminal write became an UPDATE, Streamlit needed a
committed `pending` row for the flip to update, so I added a `_stage` helper -- and pointed it at
`stage_document_record`, which **deliberately does not commit** (the API route commits the row and the
queue job together, and that is the whole reason the staging variant exists). The row was rolled back
when the session closed, the upsert had already written the generation to Qdrant, and the flip raised.
Every Streamlit upload, orphaning a generation each time.

**And I made it harder to find, the same morning.** A reverse search for `save_document_record` -- the
stage-and-commit function -- found only tests, so I deleted it as production code kept alive by its own
suite and moved a copy into the test module. The search was correct and the inference was wrong: the
caller existed and was the broken one. **A function whose only callers are tests can mean a broken
caller rather than a dead function**, and the reverse search is weakest exactly where the code is
untested. Restored, with the incident in its docstring.

**Fixed, and the test that was missing now exists.** The two writers differ *only* in whether they
commit, which is invisible from inside the writing session -- SQLAlchemy shows the row on its own
connection either way -- so
`test_the_two_row_writers_differ_only_in_whether_they_commit` reads both from a **second** session.
Mutation-confirmed in both directions: drop the commit from `save_document_record` and 8 tests go red
(1 of them only this one meaningfully); add a commit to `stage_document_record` and the
rollback-atomicity test plus this one go red. It is the only test that catches both.

**The standing gap this exposed:** Streamlit is the one write path with **no test at all**, and it is
also the path that reaches `ingest_document` directly. Both times a write-path contract moved this
week, Streamlit was the caller left behind. Either it gets a smoke test or it retires with Phase 6 --
recorded in `CLAUDE.md`'s failure contracts, since "nothing references this" is not evidence there.

### 2026-08-06 (evening) — the stack from scratch, and a healthcheck that could not fail

The user hit `FATAL: database "portfolio" does not exist` on `api` and `worker`, crash-looping, after
deleting the tables and the database by hand. Two mechanisms, and separating them is the whole
diagnosis:

- **The database cannot come back on restart.** postgres' entrypoint bootstraps only when `PGDATA` is
  empty (it tests for `PG_VERSION`), so a later start skips `initdb`, `CREATE DATABASE
  $POSTGRES_DB` and `docker-entrypoint-initdb.d` alike. The recorded contract said this about
  *changing* `POSTGRES_*`; dropping the database by hand is the same failure from the other side, and
  that half was not written down. `down -v` is the fix, because the volume is the state.
- **The tables were a symptom, not a second fault.** `init_db` runs `alembic upgrade head` at api
  boot and cannot connect at all while the database is missing, so nothing migrates.

**And the reason nothing warned: `pg_isready` does not connect to the database it is given.** Measured
in the running container -- `pg_isready -d absolutely_no_such_db` exits **0** ("accepting
connections") where `psql -d absolutely_no_such_db -c 'select 1'` exits **2**. So `-d "$POSTGRES_DB"`
in the healthcheck was decoration and `depends_on: service_healthy` gated on nothing: compose called
postgres healthy and started api and worker into a crash loop whose message reads as an application
fault. Healthcheck is now `psql … -tAc 'select 1'`. Mutation-confirmed in both directions on the same
container and the same volume, using a compose override that points `POSTGRES_DB` at a name the
volume never created: **unhealthy** under `psql` (exit 2, `FATAL` visible in the health log),
**healthy** under `pg_isready`. Nothing was destroyed to prove it.

**Then the gate caught its own trap.** The first post-reset run reported `330 passed, 53 skipped`:
`down -v` destroys `portfolio_test` and `portfolio_migrations_test` too, the fixtures read an
unreachable database as "no service, skip", and the run looks green. Recreated both with `createdb`
-> `383 passed, 0 skipped`. Recorded in the `verify` skill, because reading the skip count is the only
reason it was noticed.

**What could not be done here: the images do not build.** `nginx`, `api`, `worker` and `streamlit` all
`apt-get`, and this environment's egress policy answers `403 Forbidden` for `deb.debian.org:80`. The
proxy README says to report a 403 rather than route around it, so the stack was verified with
`postgres`/`qdrant`/`redis` in containers (no apt needed) and the application code from the local
venv. **Nothing about the images themselves is verified by this session** -- the earlier note that the
nginx config is unvalidated without a working build still stands.

*Also observed:* the six `portfolio/.claude/skills/` skills and this project's subagents are **not**
visible at the start of a repo-root session, but the skills appeared mid-session once files under
`portfolio/` were being edited -- directory-scoped discovery, resolving late. Open question #2 is
about the agents, which did **not** appear the same way; worth re-testing deliberately.

### 2026-08-06 (late afternoon) — versioned ingestion: the write half of review P0 #2

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

### 2026-08-03 (later) — the rate limiter moved onto `limits`, then its strategy changed hours later

Switched the hand-rolled Lua limiter to `limits` on the user's call, then switched its *strategy*
again the same day: `SlidingWindowCounterRateLimiter` was chosen first, on a memory argument, and
turned out not to honour its own `Retry-After` — measured, not reasoned about, so worth stating
as the actual finding: a client that waited exactly as long as the header said still got a 429.
Replaced with `MovingWindowRateLimiter`. Pruned from here 2026-08-07 because every fact in this
entry — the slowapi comparison, the two bugs the swap introduced (an `X-RateLimit-Reset: 0` edge
case, fail-open needing to be re-added since `limits` fails closed), the corrected 26×-vs-2×
memory figure, and the mutation-test guard-reliability numbers — is now in
`docs/TECHNICAL_DECISIONS.md` § Rate limiting, in more complete form than this narrated it.

Gate: 372 passed / 0 skipped.

Also retired the "run the suite three times" agreement the same day, once asked what the third
run was actually catching (nothing a single randomised run wouldn't). Replaced with
`pytest-randomly`; the reasoning is in `../CLAUDE.md` § Working agreements now, not here.

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
