# Epic 4 — Production Rigor: implementation plan

Scope note: parts of Epic 4 depend on Epics 2 and 3, which are not built. This plan covers
the whole epic and marks blocked work explicitly rather than pretending the epic is one
unblocked unit. Phases 1-3 are **built**; 4 is partial (latency SLO yes, faithfulness no);
5 and 6 are buildable today and are the largest remaining work; a separate section lists
what genuinely waits on Epics 2 and 3.

Phases 5 and 6 were previously one "blocked on a product decision" placeholder. They are
now the application layer — Phase 5 is the backend (users, conversations, document CRUD,
async ingestion), Phase 6 is the React + TypeScript UI on top of it.

Epics 2 and 3 now have their own plans -- `docs/EPIC_2_PLAN.md` and `docs/EPIC_3_PLAN.md` -- so the
blocked items below name a phase there rather than a whole epic.

Already done ahead of this epic (not repeated below): the multi-stage Dockerfile and
`.docker/` layout, gunicorn + UvicornWorker, docker-compose (qdrant/postgres/redis/nginx),
`.dockerignore`, `.env.example`, LangSmith env bridging in `config.py`, `app/logs.py`
(structlog + stdlib bridge), and `/v1` route versioning.

## Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Identity source | DB-backed `tenants` + `api_keys` | Rotation and per-key revocation; static keys in `Settings` can't do either |
| Scope model | **Collapse** — `session_id` becomes `tenant_id` | The retrieval filter is then derived entirely from auth, with no client-supplied component. Add `workspace_id` later if per-project scoping is ever wanted |
| Rate-limit key | Per tenant | Per-IP punishes shared egress and is trivially evaded |
| Rate-limit backend | Redis | `slowapi`'s in-memory counters are **per gunicorn worker**, so with N workers the real limit is N x the configured one |
| Cloud deploy | Skipped | Runs on local hardware; a deploy target is maintenance for no current gain |

## Naming conflict to resolve first

The original plan (now `docs/IMPLEMENTATION_PLAN.md`) calls for `api/middleware/auth.py`,
but this is a **FastAPI dependency**, not middleware — it must run per-route with access to
path params and be overridable in tests, which middleware isn't. Plan uses
`app/api/deps.py` (FastAPI convention) rather than misnaming the mechanism. Resolved:
Phase 3 recorded the correction in the plan's own header.

---

## Phase 1 — Authentication and tenant scoping ✅ BUILT

Delivered as planned, with these deviations worth recording:

- Engine/session moved from `registry/db.py` to a new **`app/db.py`**, since auth needs the
  same engine and importing it from a module named for the document registry would misstate
  ownership. `registry/db.py` keeps only `save_document_record`.
- `AskRequest` gained `extra="forbid"`, so a stale client still sending `session_id` gets a
  422 rather than being silently downgraded to corpus-only results.
- **Streamlit had to authenticate too.** It calls the pipeline in process, so the FastAPI
  dependency never runs for it; it now asks for a key and resolves it through the same
  `auth.service.resolve_tenant`, rather than minting a tenant id as it used to.
- Added `pytest-asyncio` (dev only) so the auth path has database-backed tests, against a
  real Postgres, skipped when none is reachable. Contradicts this plan's original "DB tests
  belong in an integration suite" note -- the coverage was worth it on the one path where a
  silent regression means cross-tenant reads. CI runs a `postgres:18-alpine` service and
  asserts these tests did **not** skip, since a silently-skipped auth suite looks identical
  to a passing one.
  An interim version used in-memory SQLite instead, replaced after it hid a real tz bug —
  see `docs/TECHNICAL_DECISIONS.md` § Database for why Postgres-only extends to tests.
- `langgraph-checkpoint-sqlite` swapped for `langgraph-checkpoint-postgres`, and Epic 3's
  planned SQLite `incoming_queue` becomes a Postgres table: one database engine, project-wide.
- 1.6 (streaming upload) **not** done, as flagged optional. The size check still runs after
  a full `await file.read()`, so `max_upload_size_mb` bounds what's stored, not what's
  buffered. Noted in `documents.py`.

Since verified on the real stack: `init_db` runs against a live Postgres (including the
advisory-lock path, which the first real boot is what surfaced), and the queued path has been
observed end to end — `POST /v1/documents` → job row → `worker` consuming it → Qdrant points →
an `ingested` registry row. What remains unverified on real infrastructure is Qdrant's client
over the wire under concurrency, and the nginx config's syntax.

### Original plan (for reference)

Condensed rather than reproduced in full, because two of its central design choices no longer
hold and an unflagged code sketch reads as current when it isn't. It specified
`GLOBAL_TENANT`/a shared corpus matched via `MatchAny` — removed 2026-08-03, there is no shared
tenant now, see `CLAUDE.md` § The tenant boundary — and its `ApiKey` sketch predates per-key
`scopes` entirely. What it got right and is still true: SHA-512 over argon2 (keys are
high-entropy, not passwords, so a slow KDF buys nothing until Phase 5's password login), the
`pf_live_`-prefixed base62+CRC32 key format, and `app/api/deps.py` over middleware so tests can
override per route. The real models, dependency and filter are `app/auth/models.py`,
`app/api/deps.py::current_tenant`, and `app/vectorstore/qdrant_store.py::_build_filter` — read
those and `docs/TECHNICAL_DECISIONS.md` § Authentication rather than this section.
`last_used_at`'s write-frequency question, open when this was written, is resolved in
`app/auth/service.py`'s own docstring.

### 1.6 Optional, same handler — streaming upload

`file_bytes = await file.read()` buffers the whole upload, and the size check runs *after*,
so `max_upload_size_mb` doesn't bound memory at all: a 500 MB body is fully resident before
rejection. At 100 concurrent 20 MB uploads that's 2 GB before Docling starts. Fix is to
stream to disk in chunks with a running SHA-256 and an incremental size check that aborts
mid-stream. Included here only because it edits the same handler — split it out if Phase 1
is getting long.

The planned CLI and test suite are both built and superseded by the real files: `scripts/create_tenant.py`
and `tests/unit/test_tenant_scoping.py` (the plan named `test_auth_scoping.py`, which was never
created — the cross-tenant assertion landed under the name above instead).

---

## Phase 2 — Rate limiting ✅ BUILT

Depends on Phase 1 for the tenant key.

- Add `slowapi`. Wire the existing `REDIS_*` env vars into `Settings` — currently declared
  in `.env.example` but read by nothing, so Redis has been running as unused infra.
- `Limiter(key_func=lambda r: r.state.tenant_id, storage_uri=redis://...)`.
- Limits: tighter on `POST /v1/documents` than on `/v1/ask` — ingestion costs Docling CPU
  plus Anthropic and Voyage calls, so it's the expensive endpoint, not the query path.
- 429 handler consistent with the existing `PortfolioError` shape.
- Test with a fake/in-memory limiter; assert the N+1th request is refused.

Deferred: `/review` doesn't exist until Epic 3.

---

## Phase 3 — Documentation ✅ BUILT

- `docs/TECHNICAL_DECISIONS.md`: consolidate the rationale currently spread across README rows
  and code comments — chunking, reranker, embeddings, Qdrant (incl. point-ID and delete-then-insert
  contracts), pool sizing, the tenant-scope collapse and why, tracing choice.
- README rewrite: becomes a real project README (quickstart, architecture, what's built vs
  planned); plan content moves into history. Fold in the `deps.py`-vs-`middleware/` correction.

Built as specified, plus:

- The old README moved to `docs/IMPLEMENTATION_PLAN.md` via `git mv` (rename preserved in
  history) rather than being deleted and rewritten in place. Its new header lists every
  point where the plan and the code now disagree — `middleware/` vs `deps.py`, `slowapi`,
  the `session_id` → `tenant_id` security fix, the test count — so a reader who lands there
  first isn't misled.
- The README's "Known gaps" section states the four things that are *not* covered:
  the 6-vs-45-paper corpus, the un-run Epic 1 spot-check, that no test exercises Qdrant,
  and that uploads buffer fully in memory before the size check.
- Stale pointers fixed: `CLAUDE.md`, `app/api/deps.py`, and `app/registry/models.py` all
  referenced "README" for content that is now in the plan or in `docs/TECHNICAL_DECISIONS.md`.
- `docs/TECHNICAL_DECISIONS.md` is 16 sections, each with the rejected alternative and what
  would justify revisiting it. `CLAUDE.md` now states which doc to update when a decision
  changes, so the plan doesn't get edited back into being a live document.

---

## Phase 4 — Observability (partially blocked)

- `streamlit_app/pages/3_Observability.py`: links into the LangSmith project. Buildable now,
  but thin until Epics 2/3 generate traces worth looking at.
- `app/observability/alerts.py`: threshold check -> webhook. **Latency SLO works now;
  faithfulness needs Epic 2's RAGAS scores**, so build the latency half and leave a named
  gap rather than a placeholder that looks complete.

---

## Phase 5 — Application backend: users, conversations, document CRUD

The backend the React app of Phase 6 consumes. Split from Phase 6 deliberately: this is
roughly three times the work, and bundling them means nothing is verifiable until
everything is. Every item here is testable over HTTP with `curl` and no frontend.

**Prerequisite that isn't obvious:** uploads must stop being synchronous. See 5.1.

### Decisions taken for this phase

| Decision | Choice | Why |
|---|---|---|
| Tenant ↔ user | `User` **belongs to** `Tenant`, exactly one member for now | Confirmed with the user. 1:1 today, but the FK costs nothing now and adding it later is a migration on live data |
| Job queue | **`procrastinate`** | See "Job queue" below — `arq` is maintenance-only |
| Chat-thread naming | **`Conversation`**, never "session" | `session_id` used to be the retrieval scope and removing it was a security fix; reusing the word makes the boundary unreadable |
| Password auth | **Delegate to an IdP** (recommendation; see 5.2) | Email verification, reset, and lockout are all table stakes and all someone else's solved problem |
| Document sharing | **Not in this phase** | Needs per-document ACLs; conversation snapshots don't |

### Job queue — why not `arq`, and why `procrastinate`

`arq` was the original plan. It is in **maintenance-only mode** (upstream: "we'll continue
to fix critical security issues […] but don't expect work on new fixes"), so it is not
abandoned but is not a thing to start new work on — the same call already made about
`fastapi-users`. Verified against the repo, not assumed from a version number.

Candidates checked for resolvability under `requires-python = ">=3.14"` with this
project's existing pins (`uv lock`, the method that caught the `slowapi` conflict): all of
`procrastinate`, `rq`, `celery`, `saq`, `arq` resolve. So resolvability doesn't decide it.

**`procrastinate`**, on these grounds:

- **Async-native.** `ingest_document` is `async def` over an async SQLAlchemy engine.
  Celery and RQ are sync-first: every job would be a `def` wrapping `asyncio.run(...)`,
  opening a fresh event loop and a fresh connection pool per job.
- **Transactional enqueue**, which kills a specific failure mode rather than being a nice
  property. Postgres-backed means the `DocumentRecord` row and the job land in **one
  transaction**: there is no window where a document exists with no job (stuck "pending"
  forever, and the UI's job is to show exactly that) or a job exists with no row. With
  Redis as the broker those are two systems and the gap is real.
- **No new infrastructure.** It uses the Postgres already running, via `psycopg` 3 which
  is already a dependency. Redis stays purely a rate-limit counter store, consistent with
  the existing "Redis is a cache, Postgres is the database" split.
- Actively released, `Development Status :: 5 - Production/Stable`.

Rejected, with reasons rather than a shrug:

| Option | Why not |
|---|---|
| `celery` | Sync-first; async support is still not native. Heaviest config surface (broker + result backend + beat) for one job type |
| `rq` | Simple and solid, and **fork-per-job would isolate a Docling segfault better than procrastinate's in-process workers** — the one real argument against this recommendation. Still sync-first, and adds a second queue system alongside Postgres |
| `saq` | Async-native and arq-shaped, so the closest drop-in. Loses the transactional-enqueue property; smaller install base |
| `taskiq` | Ships `Development Status :: 3 - Alpha` in its own metadata. Not for a production framing |

**Deviation to accept explicitly:** procrastinate ships its own SQL migrations, so
"no Alembic for one table" (see `docs/TECHNICAL_DECISIONS.md`) stops being the whole story —
deploys gain a `procrastinate schema --apply` step. That's a real cost of the choice and it
belongs in the decision record, not discovered at deploy time.

### 5.1 Uploads become jobs — `app/worker/` ✅ BUILT

Delivered as specified. Deviations and findings worth recording:

- **Transactional enqueue needed proving before designing around it.** `procrastinate.contrib.sqlalchemy`
  is psycopg2-based and sync-only, so the advertised SQLAlchemy integration doesn't fit this
  stack at all. The working path is `defer_async(connection=...)` with the raw
  `psycopg.AsyncConnection` unwrapped from the async session
  (`session.connection()` → `get_raw_connection()` → `.driver_connection`). Verified against a
  live Postgres before building on it: deferring inside a transaction and rolling back leaves
  0 jobs, committing leaves 1.
- **`_raw_connection` type-checks the driver.** `DB_DRIVER` is a `Settings` field, so pointing
  it at `postgresql+asyncpg` would hand procrastinate's psycopg connector an asyncpg
  connection and fail deep inside with an error naming neither. Now raises at the boundary.
- **The api was importing Docling to enqueue.** The first version put `import_paths` on the
  App, which makes `configure_task` import `tasks.py` → the pipeline → Docling. Measured at
  ~10s inside the first upload request. Fixed by deferring **by name** with no `import_paths`,
  and pointing the worker CLI at `app.worker.tasks.app` instead. A test pins that the name
  matches the registered task, since that check moved from import time to runtime.
- **`app/ingestion/formats.py` was the other Docling importer**, found the same day — full
  measurement and reasoning in `docs/TECHNICAL_DECISIONS.md` § Keeping the ingestion stack out
  of the api process rather than restated here.
- **Found a pre-existing bug that had never worked:** `save_document_record` raised
  `PydanticUserError` on every call, because `model_dump()` needs `datetime` resolvable at
  runtime and `registry/models.py` imported it under `TYPE_CHECKING`. Every ingest wrote to
  Qdrant and then failed before the Postgres row. It survived because no test touched the
  registry and the symptom looks like a database problem. Confirmed against `HEAD` before
  fixing, and the new tests fail without the fix.
- **procrastinate's schema is applied in `init_db`**, guarded by a `to_regclass` existence
  check because `schema.sql` uses bare `CREATE TABLE` and is not idempotent. Chosen over a
  documented `procrastinate schema --apply` deploy step, which fails as "relation does not
  exist" when forgotten. Version *migrations* still need the CLI — a stated boundary, not a
  claim to have handled them.
- **Breaking API change**: `chunk_count` is gone from the upload response, since nothing has
  been parsed when the 202 is written. Returning 0 would have preserved the shape and lied.
- No `SLO`/observability wiring, no `GET /v1/documents` list, no `DELETE` — those are 5.5.

### 5.1 Original plan (for reference)

Condensed: it described a synchronous `POST /v1/documents` (blocking for the whole 10s–2min
ingest, with the gunicorn/nginx timeout as the only thing standing between that and an outright
failure) as the problem 5.1 solves, and every bullet under it — the widened status vocabulary,
the 202 response, failure landing as `status="failed"`, `worker` as a compose service, and
bounding worker concurrency against `DOCLING_NUM_THREADS` — is now built, verified, and
(the concurrency bound) already explained in `docs/TECHNICAL_DECISIONS.md` § Ingestion latency
rather than restated here.

### 5.2 Identity — the open decision, with a recommendation

The user's position: "really not sure how to do user logins", and email verification is
required. That combination argues for delegating.

**Recommended: self-hosted Keycloak** as one more compose service. It provides
registration, email verification, password reset, lockout, MFA, and OIDC discovery. The app
gets a `current_user` dependency that verifies a JWT against Keycloak's JWKS, and
provisions a `Tenant` + `User` row on first login. Costs: ~512MB–1GB of JVM heap on a
16GB box that also runs torch and Docling, plus a realm/client configuration surface that
is genuinely large -- though at the 10k-tenant target it is more defensible than it was
at 1k.

Alternative if Keycloak is too much: **own it**, with `argon2-cffi` for password hashing
(*not* the API keys' plain digest — opposite threat model, see `docs/TECHNICAL_DECISIONS.md`),
`itsdangerous` for signed session cookies, and a transactional-email provider. Budget for
what that actually includes: verification tokens, reset tokens with single-use semantics,
lockout, timing-safe comparison, and the tests to prove each one.

Either way:

- **The browser must not use `x-api-key`.** A long-lived key in `localStorage` is
  exfiltrable by any XSS and cannot be revoked per-tab. Browser requests authenticate with
  a short-lived credential in an `httpOnly` cookie; API keys stay for programmatic access.
  Two entry points, one identity resolution — `current_tenant` becomes the shared tail.
- Cookies mean **CSRF protection** (double-submit or `SameSite=Strict` plus origin checks)
  and mean CORS must name real origins. The wildcard-plus-credentials guard added in
  `config.py` exists so that combination can't be reached by accident.
- **Login needs its own rate limit.** The existing limiter keys on tenant, which is useless
  for an endpoint you hit *before* knowing the tenant. Credential stuffing needs an
  IP-and-email-keyed bucket. Delegating to an IdP means this is Keycloak's problem.
- **Signup is a cost control, not just hygiene.** Every upload is Docling CPU plus one
  vision call per figure plus one embedding call per chunk. Open signup on a public URL is
  an uncapped Anthropic bill, so email verification gates ingestion, and per-tenant quotas
  (documents stored, tokens/month) land in this phase rather than after the first surprise.

### 5.3 Conversations — `app/conversations/`

- `Conversation`: `id`, `tenant_id` (indexed), `user_id`, `title`, `created_at`,
  `updated_at`. Titles generated from the first question — one cheap LLM call, a legitimate
  judgment call rather than a deterministic one.
- `Message`: `id`, `conversation_id` (indexed), `role`, `content`, `created_at`, **plus the
  citations and retrieved chunk ids as JSONB**. Persisting only the text loses provenance
  on reload, which is the one thing this product sells.
- `POST /v1/conversations`, `GET /v1/conversations`, `GET /v1/conversations/{id}`,
  `PATCH` (rename), `DELETE`. All tenant-scoped through the existing dependency.
- **Multi-turn retrieval needs a condensation step.** "What about the second one?" embeds
  to nothing useful. Before retrieval, rewrite the question against the last N turns into a
  standalone query. This is not optional polish — it is the difference between the second
  turn working and not.
- `/v1/ask` gains an optional `conversation_id`; without one it stays the stateless
  single-turn endpoint it is today, so existing API clients don't break.

### 5.4 Document scoping on `/ask`

An optional `doc_ids` filter, so a question can target one document instead of everything.
`_build_filter` takes another `MatchAny` condition; the API doesn't expose it yet.

**Every id must be verified as owned by the calling tenant before it reaches the filter.**
Otherwise this is a fresh cross-tenant read: name someone else's `doc_id` and the tenant
condition is satisfied by the *other* clause. Belongs in the same test file as the existing
scoping assertions.

### 5.5 Document CRUD

- `GET /v1/documents` — list for the tenant, paginated, with status.
- `DELETE /v1/documents/{doc_id}` — and this is more than it looks. Four things must go:
  the Qdrant points (`QdrantStore.delete_document` exists), the file under
  `data/uploads/<tenant_id>/`, the registry row, and a decision about messages that cite
  it. Recommendation: keep the messages, mark the citation dangling in the response — a
  chat log that silently rewrites itself is worse than one that says a source is gone.
- `DELETE /v1/account` — cascades all of the above for every document, plus conversations.
  Needed for GDPR and trivially forgotten.

### 5.6 Search

Two of the three possible meanings, chosen deliberately:

- `GET /v1/documents?q=` — filename/metadata match in Postgres.
- `POST /v1/search` — semantic chunk search: embed, retrieve, rerank, **no generation**.
  Fast and cheap next to `/ask`, and it's the honest primitive behind "search".

Chat-history search is skipped for now; it needs Postgres FTS and it is the least-used of
the three.

### 5.7 Streaming `/ask`

Yes, this is mostly easy — with two caveats worth stating before it's built.

- `ChatAnthropic.astream` and an SSE response is the straightforward part.
  `proxy_buffering off` is **already set** in `conf.d/default.conf`, which is the usual
  thing that breaks SSE behind nginx.
- **Caveat 1: it doesn't help time-to-first-byte as much as expected.** Retrieval and
  reranking both complete before the first token — that's the multi-second part. Streaming
  removes the generation wait, not the retrieval wait. If the goal is a responsive UI, emit
  progress events for the retrieval stages too, otherwise the stream just starts late.
- **Caveat 2: errors after the first byte can't be a 4xx/5xx.** The status line is already
  sent, so a mid-stream failure has to be an in-band error event the client explicitly
  handles, and the existing `PortfolioError` handler cannot help. Every streaming API gets
  this wrong once.
- Citations arrive as Anthropic content-block deltas, so the payload shape differs from the
  non-streaming response. Keep `POST /v1/ask` as-is and add `POST /v1/ask/stream` rather
  than making one endpoint return two shapes.

### 5.8 Sharing — conversation snapshots only

A public link is unauthenticated read access to tenant-scoped content, so the shape matters
more than the feature:

- A **frozen snapshot** — answer text and citations copied at share time. Not a live query.
  A live shared link re-runs retrieval as the owner, so documents uploaded *later* leak
  through a link they've forgotten about.
- Unguessable token (`secrets.token_urlsafe`), revocable, optional expiry.
- **Never serves the underlying document**, only the quoted citation text.
- Document sharing between users is explicitly out: it needs per-document ACLs, which is a
  change to the payload schema and the filter, i.e. its own phase.

### 5.9 Tests

There are currently **no HTTP-level tests at all** — all eight files are unit-level. A
consumed API contract changes that calculus:

- `httpx.ASGITransport` against the app for the auth, CRUD, and conversation routes.
- Cross-tenant negative tests on every new endpoint: list, get, delete, share, `doc_ids`.
  The pattern from `test_tenant_scoping.py` applies to each one.
- A test that a `failed` ingest leaves a `failed` row, since the whole point of 5.1 is that
  the UI can distinguish failure from absence.

---

## Phase 6 — React + TypeScript frontend

Consumes Phase 5. Nothing here is buildable before it.

- **Location** `portfolio/web/`, Vite + React + TypeScript. Its own `package.json`; the
  repo-root CI workflow gains a second job scoped to `portfolio/web/**`.
- **Typed client generated from OpenAPI**, via `openapi-typescript`. FastAPI already emits
  the schema and every route and field already carries descriptions, so this is free and
  keeps the client from drifting. Don't hand-write request types.
- **Screens**: signup/login (or IdP redirect), document list with upload + per-document
  status polling, conversation list, a conversation view with streaming answers and
  inline citations, search, and share-link management.
- **Citations are the differentiator**, so render them as first-class UI — click a citation,
  see the quoted chunk with its page number — not footnote markers.
- **Serving**: nginx serves the static build and proxies `/v1` to `api`. Today it proxies
  `/` wholesale, so `conf.d/default.conf` needs a real location split.
- **Streamlit's fate must be decided, not left to drift.** Once this exists,
  `streamlit_app/Home.py` is redundant *and* it is the one component calling the pipeline
  in-process rather than over HTTP — the reason it needed its own auth path. Recommendation:
  delete it when Phase 6 ships, and remove the `streamlit` compose service with it.

---

## Operational hardening (unplanned, done after 5.1 shipped) ✅ BUILT

Four gaps found by reviewing the repo rather than by following the plan. None were in it.

- **`uv.lock` is now committed**, with `--locked` in the Dockerfile and CI. It was gitignored and
  `CLAUDE.md` recorded that as deliberate; reversed because it made builds non-reproducible —
  the image re-resolved at build time, so CI could pass against a dependency set nobody deployed.
  It is also what broke a local venv in practice: nothing to sync *against*.
  `--locked`, not `--frozen`: verified that `--frozen` uses the lock without checking it, so a
  dependency added and not re-locked builds fine and fails later as an ImportError.
- **`/health/live` + `/health/ready`** replace `GET /`, which returned a static body — so the
  container `HEALTHCHECK`, `depends_on: service_healthy`, and nginx all reported healthy with
  every dependency down. Readiness probes Postgres/Qdrant/Redis concurrently and 503s on a
  required outage; Redis is reported but *not* required, because rate limiting fails open.
  Readiness deliberately avoids `QdrantStore`, whose `__init__` sends a throwaway probe
  embedding — that would have billed a Voyage call every 30 seconds and reported Qdrant down
  whenever Voyage was.
- **Missing provider keys now fail at boot** for the api, and fail an individual *job* in the
  worker so the reason lands in `documentrecord.error_message`. Not a `Settings` validator: that
  would break the unit suite, `ty`, and `scripts/create_tenant.py`, none of which need keys.
- **Qdrant filtering and the HTTP layer are now tested** (19 new tests, 116 total).
  `test_qdrant_filtering.py` runs the real `_build_filter` through `qdrant_client`'s in-memory
  engine with fake embeddings, so cross-tenant exclusion and the delete-then-insert contract are
  proved by execution rather than by asserting the filter's shape — and run in CI with no server
  and no keys. `test_api_contract.py` covers 401 on every route, the `extra="forbid"` 422, the
  extension allowlist, 413, and readiness semantics. **Still untested: the live Qdrant client
  over the wire**, which is exactly where the point-ID constraint escaped.

Not done from that review: no stuck-job sweeper, no `GET /v1/documents` list or `DELETE`
(5.5), no metrics, no request-correlation id, no payload index on `metadata.tenant_id`
(see `.claude/skills/VENDORED.md`).

### Backups — deliberately deferred

**There are no backups of anything.** Qdrant and Postgres each live in a single Docker volume;
losing or corrupting either destroys every document, tenant, and API key with no recovery path.
No `pg_dump`, no Qdrant snapshot, no restore drill.

Deferred on the owner's call while the project is pre-alpha: there is no production data to lose
yet, and a backup mechanism nobody has restored from is theatre anyway. Recorded here rather than
dropped, because the moment there is a real user this becomes the highest-priority gap in the
repo — and it is the kind of thing that gets remembered only after it matters.

What it would involve, so the decision can be revisited cheaply:

- `pg_dump` on a schedule, covering `tenants`/`api_keys`/`documentrecord` *and* procrastinate's
  tables — the queue lives in the same database, so a partial restore resurrects jobs for
  documents that no longer exist.
- Qdrant snapshots via its own snapshot API (not a volume copy: copying a live storage directory
  is not crash-consistent).
- The two must be restored **together and consistently**. A Postgres restore newer than the
  Qdrant one leaves rows whose points are missing; the reverse leaves orphaned points that still
  match a tenant filter and are still retrievable. This is the part that makes it real work
  rather than two cron jobs.
- `data/uploads/<tenant_id>/` too, or accept that re-ingestion is impossible after a restore.
- **A restore drill in CI or a runbook.** Untested backups are the default failure mode.

### Second review pass: CI/CD, pre-commit, supply chain ✅ BUILT

- **`.pre-commit-config.yaml`**, all project-tool hooks `repo: local` calling `uv run` so the
  ruff/ty that gate a commit are the versions `uv.lock` pins -- not pre-commit's own separately
  pinned copies, whose drift shows up as "passes locally, fails CI on formatting". Fast checks on
  commit, the suite on push. Includes a hook that refuses `.env` outright, since
  `detect-private-key` catches PEM blocks and not `ANTHROPIC_API_KEY=...`. Every Python hook is
  scoped `^portfolio/`: pre-commit passes git-root-relative paths, so unscoped it handed ruff the
  sibling projects' files and reported 4 errors from code this project doesn't govern.
- **`.github/dependabot.yml`** for `uv`, `github-actions`, `docker` (three Dockerfiles) and
  `docker-compose` (the service image tags). Verified the `uv` ecosystem is GA and reads
  `uv.lock` -- which is only possible because the lock is now committed. Minor/patch grouped into
  one PR per ecosystem; majors deliberately ungrouped, since postgres 17->18 is exactly the bump
  that needs someone reading release notes.
- **CI restructured**: explicit `permissions: contents: read` (unset, the token defaults to the
  repo setting, often write); `concurrency` cancelling superseded PR runs but never main's; and
  the single job split into `static` (fast, no services), `test` (services + the no-skip
  assertion), `security`, and `stack`.
- **`security` job** runs `pip-audit` over `uv export`'s pinned set -- the versions that actually
  ship, not a fresh resolution -- and **fails** on a finding. Currently clean across 265
  packages. Real-but-unfixable findings get an explicit `--ignore-vuln <ID>` with a comment,
  rather than a disabled job.
- **`stack` job** builds the images and smokes the running stack: waits on `/health/ready`,
  asserts every dependency reports `ok`, runs `nginx -t` *inside* the compose network (a
  standalone run can't resolve the `api` upstream), checks readiness and a 401 through the proxy,
  and greps the worker's log for the ingest queue. This is the class of failure CI has never seen
  -- every Docker bug so far reached a human first. Gated off pull requests because the api image
  installs torch and Docling. Dummy provider keys are enough: the boot check only asserts
  non-empty, so nothing calls out.

---

## Blocked on Epics 2 and 3 (not a phase)

Listed so the sequence stays explicit. None of it is attemptable now, and none of it
blocks Phases 5 or 6:

| Item | Blocked on |
|---|---|
| `agent/nodes.py` structlog calls | Epic 3's agent |
| Rate limit on `/review` | Epic 3's review endpoint |
| `eval/agent_trace_assertions.py` + `tests/eval/` | Epic 3's agent **and** `docs/EPIC_2_PLAN.md` Phase 2.3 |
| Faithfulness SLO in `alerts.py` | `docs/EPIC_2_PLAN.md` Phase 2.3 (RAGAS scores) |

## Prerequisite for load, not a phase

**The Qdrant payload index on `metadata.tenant_id` (`is_tenant=true`) must exist before this
system carries real traffic.** It was recorded as a deferred nicety while the target was 1k
tenants x 2 documents; at 10k x 10 -- order 1M points -- an unindexed tenant filter on every
query degrades toward a scan. One `create_payload_index` call at collection setup. Details in
`.claude/skills/VENDORED.md`, verdict in `docs/TECHNICAL_DECISIONS.md` § "Scale target".

Two sizing consequences of the same revision. Neither is an open question -- both have
numbers -- but each needs a decision that has not been made:

- **Connections.** The arithmetic is already in `app/config.py`: each gunicorn worker owns
  its own engine, so the ceiling is `GUNICORN_WORKERS * (db_pool_size + db_max_overflow)`
  against Postgres' `max_connections` (100 by default). At the shipped defaults that is
  `2 * (10 + 5) = 30` -- fine. An 8 vCPU box wants `2*cpu+1 = 17` workers, which is
  **`17 * 15 = 255`, over the limit by 2.5x**, and the `worker` container's own pool is on
  top of that. Three ways out -- lower `db_pool_size`, raise `max_connections`, or put
  PgBouncer in front -- and the decision is which, not whether. Nothing enforces the
  invariant at startup today, so exceeding it surfaces as connection errors under load
  rather than as a boot failure; a startup assertion is the cheap half of the fix.
- **Disk. Still unmeasured, and an attempt to measure it failed informatively.**
  `processed_dir` holds one parsed Docling JSON per document plus a PNG per surviving
  figure; `upload_dir` holds the original upload. Per-document cost is therefore driven by
  page count and figure count, not by file size -- but no number exists yet, and none should
  be invented. Parsing one 16-page corpus paper (2.7MB, arXiv 2008.10896) to obtain one
  **failed**: Docling returned `partial_success` with 1 of 16 pages parsed and fifteen
  `document timeout exceeded` errors. That is a genuine finding independent of disk sizing:
  the sandbox has no GPU and limited CPU, and a real paper exceeded the per-document
  timeout. Whether production hardware clears it is unknown, which makes **ingest latency and
  timeout budget on real corpus documents a load-test item in its own right** -- the 10s-2min
  figure quoted in `README.md` comes from small documents.
  Two things follow regardless of the eventual number: `processed_dir` is rebuildable by
  re-parsing and so should be an evictable cache with a retention policy, unlike
  `upload_dir`; and the measurement wants a machine that can actually finish a parse.

## Dependencies added

| Package | Phase | For |
|---|---|---|
| `slowapi` | 2 | Rate limiting — **rejected, not added**; see Phase 2 |
| `procrastinate` | 5 | Job queue for async ingestion (replaces the planned `arq`) |
| IdP client (`authlib`/`python-jose`) *or* `argon2-cffi` + `itsdangerous` | 5 | Depends on 5.2's outcome |
| Transactional email provider SDK | 5 | Verification and reset mail, if not delegated |
| `openapi-typescript` (npm, dev) | 6 | Generated API client |

No new dependency for Phase 1: `secrets` and `hashlib` are stdlib, `sqlmodel` and
`psycopg` are already present.

## Risks

Phase 1's risks (the scope-rename filter mistake, `init_db()` needing `app.auth.models`
imported, `last_used_at` write cost, the 1.3 re-ingest) are gone from this list because Phase 1
is built and each one resolved into either a test or a shipped mitigation — see the phase's own
section rather than a risk register for work that's done.

Added for Phases 5-6:

- **`doc_ids` on `/ask` is a new cross-tenant read** if the ids aren't verified as owned
  before they reach the filter. Same silent-failure shape as the original `session_id` bug:
  it returns results rather than erroring.
- **Cookie auth plus permissive CORS is a total bypass**, because Starlette answers
  wildcard-plus-credentials by reflecting the caller's own origin. Guarded in `config.py`
  as of this phase's groundwork, with `tests/unit/test_cors.py` pinning it.
- **Worker concurrency × `DOCLING_NUM_THREADS` can oversubscribe the box**, making parallel
  ingests slower than sequential ones. Neither number is meaningful alone.
- **Share links outlive the intent behind them.** A live (non-snapshot) shared link keeps
  querying the owner's corpus, so it leaks documents uploaded after it was created. The
  snapshot requirement in 5.8 is the mitigation and it is not optional.
- **procrastinate's schema needed a deploy step of its own** — resolved by 5.1 shipping, not by
  this phase: `init_db` applies it automatically (guarded by a `to_regclass` existence check),
  the same way Alembic now owns every other table's schema. Left here as the reason that
  guard exists, not as an open risk.
