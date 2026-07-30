# Epic 4 — Production Rigor: implementation plan

Scope note: parts of Epic 4 depend on Epics 2 and 3, which are not built. This plan covers
the whole epic and marks blocked work explicitly rather than pretending the epic is one
unblocked unit. Phases 1-3 are **built**; 4 is partial (latency SLO yes, faithfulness no);
5 and 6 are buildable today and are the largest remaining work; a separate section lists
what genuinely waits on Epics 2 and 3.

Phases 5 and 6 were previously one "blocked on a product decision" placeholder. They are
now the application layer — Phase 5 is the backend (users, conversations, document CRUD,
async ingestion), Phase 6 is the React + TypeScript UI on top of it.

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
  An interim version used in-memory SQLite instead, which did surface a real tz-comparison
  bug -- but testing auth on an engine the app never runs is how backend-specific bugs hide,
  so it was replaced. The assumption that bug exposed is now pinned by an explicit test
  (`test_stored_timestamps_come_back_timezone_aware`) rather than by defensive code.
- `langgraph-checkpoint-sqlite` swapped for `langgraph-checkpoint-postgres`, and Epic 3's
  planned SQLite `incoming_queue` becomes a Postgres table: one database engine, project-wide.
- 1.6 (streaming upload) **not** done, as flagged optional. The size check still runs after
  a full `await file.read()`, so `max_upload_size_mb` bounds what's stored, not what's
  buffered. Noted in `documents.py`.

Not verified here: no live Postgres or Qdrant in the dev sandbox, so `init_db` against real
Postgres and end-to-end cross-tenant retrieval remain to be checked on real infrastructure.

### Original plan (for reference)

The security-critical phase. Everything else in Epic 4 is additive; this one closes two
live holes: `/ask` accepts a client-supplied `session_id` (any caller can read another
tenant's documents), and `session_id`/`file.filename` flow unvalidated into filesystem
paths (arbitrary file write).

### 1.1 Models — `app/auth/models.py` (new)

```python
class Tenant(SQLModel, table=True):
    id: str = Field(primary_key=True)  # uuid7 hex, server-generated
    name: str
    created_at: datetime | None = Field(sa_column=Column(DateTime(timezone=True), server_default=func.now()))


class ApiKey(SQLModel, table=True):
    id: str = Field(primary_key=True)  # uuid7 hex
    tenant_id: str = Field(foreign_key="tenant.id", index=True)
    key_hash: str = Field(index=True, unique=True)  # sha256 hex of the full key
    prefix: str  # first ~12 chars, for display only
    name: str  # human label ("ci", "laptop")
    created_at: datetime | None = ...
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
```

**Gotcha:** `SQLModel.metadata` is global, so `init_db()` only creates these if the module
has been imported. `registry/db.py::init_db` must import `app.auth.models` explicitly, or
the tables silently never exist.

**Hashing:** plain SHA-256, deliberately *not* argon2/bcrypt. Keys are 256 bits of
`secrets.token_urlsafe(32)` — there is nothing to brute-force, and a slow KDF on every
request is self-inflicted latency. Argon2 becomes correct only in Phase 5's password login,
where the secret is low-entropy.

**Key format:** `pf_live_<43 url-safe chars>`. Prefixed so leaked keys are greppable and
detectable; `prefix` stored separately so the UI can list keys without holding the secret.

### 1.2 Dependency — `app/api/deps.py` (new)

```python
async def current_tenant(x_api_key: Annotated[str | None, Header()] = None) -> str
```

- Missing header → 401.
- `sha256(key)` → single indexed lookup on `key_hash` where `revoked_at IS NULL`. O(1).
- Miss → 401 with an identical message and timing path to a revoked key (don't leak which).
- Stash `request.state.tenant_id` for Phase 2's rate-limit `key_func`.
- Return `tenant_id`.

`last_used_at`: a DB write on every request is a real cost. Update at most once per minute
per key (compare in Python, skip the write), or defer entirely — decide when measured, and
note the choice in the code rather than silently writing every request.

### 1.3 Scope rename — `session_id` -> `tenant_id`

Mechanical but touches the security boundary, so it gets tests rather than trust:

- `app/ingestion/models.py`: `Chunk.session_id` -> `tenant_id`; `GLOBAL_SESSION` -> `GLOBAL_TENANT` (value stays `"global"`).
- `app/vectorstore/qdrant_store.py`: `_chunk_metadata` emits `metadata.tenant_id`; `_build_filter(chunk_types, tenant_id)` filters `MatchAny(any=[GLOBAL_TENANT, tenant_id])`.
- `app/ingestion/pipeline.py`, `chunker.py`, `figure_extractor.py`, `scripts/ingest.py`: parameter rename.
- `app/registry/models.py`: `DocumentRecord.session_id` -> `tenant_id`.
- Requires a re-ingest (`docker compose down -v`). Safe now: `upsert` already deletes by `doc_id` first, and there is no production data.

### 1.4 Router changes

- `AskRequest.session_id`: **deleted**, not made optional — absent fields can't be spoofed.
- `documents.py`: drop the `session_id` Form field; add `tenant_id: Annotated[str, Depends(current_tenant)]`.
- `UploadResponse.session_id` -> `tenant_id` (informational; the caller already knows who it is).
- Both routers gain the dependency; `_build_filter` is reachable only from it.

### 1.5 Filesystem hardening

Needed regardless of auth, since `file.filename` is client-controlled under every design:

- `file.filename` -> `Path(file.filename).name`; reject empty, `.`, `..`, and dotfiles.
- Validate `tenant_id` against `^[0-9a-f]{32}$` before it becomes a path segment — belt and braces, since it is now server-generated.
- After joining, assert `resolved.is_relative_to(settings.upload_dir.resolve())` and refuse otherwise. Cheap, and catches any future path-building mistake.

### 1.6 Optional, same handler — streaming upload

`file_bytes = await file.read()` buffers the whole upload, and the size check runs *after*,
so `max_upload_size_mb` doesn't bound memory at all: a 500 MB body is fully resident before
rejection. At 100 concurrent 20 MB uploads that's 2 GB before Docling starts. Fix is to
stream to disk in chunks with a running SHA-256 and an incremental size check that aborts
mid-stream. Included here only because it edits the same handler — split it out if Phase 1
is getting long.

### 1.7 Tenant/key CLI — `scripts/create_tenant.py` (new)

Creates a tenant plus its first key and prints the key **once**. Also `revoke_key.py`, or a
`--revoke` flag. Enough to use the API before Phase 5's UI exists.

### 1.8 Tests — `tests/unit/test_auth_scoping.py` (new)

The cross-tenant test is the one that matters:

- No `x-api-key` -> 401; unknown key -> 401; revoked key -> 401.
- **Tenant A's key cannot retrieve tenant B's chunks** — assert on the built filter, so it holds without a live Qdrant.
- Corpus chunks (`GLOBAL_TENANT`) remain visible to every tenant.
- A traversal filename (`../../evil.py`) is reduced to a basename and stays under `upload_dir`.
- `AskRequest` **rejects** an extra `session_id` field rather than ignoring it (guards against the old shape creeping back).

### Verification

`ruff` + `ty` + `pytest tests/unit`, then manually: `curl` without a key -> 401; with a key
-> 200; ingest as tenant A and confirm tenant B's `/ask` cannot cite A's document.

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

- `TECHNICAL_DECISIONS.md`: consolidate the rationale currently spread across README rows
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
  referenced "README" for content that is now in the plan or in `TECHNICAL_DECISIONS.md`.
- `TECHNICAL_DECISIONS.md` is 16 sections, each with the rejected alternative and what
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
"no Alembic for one table" (see `TECHNICAL_DECISIONS.md`) stops being the whole story —
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
- **`app/ingestion/formats.py` was the other Docling importer** — it derived its extension list
  from Docling's `FormatToExtensions` at import time. The README's claim that these helpers are
  "deliberately dependency-free (no docling import)" was simply false. Now a pinned list with a
  drift check in the test suite: `import app.api.main` went 8.74s/830MB → 6.78s/673MB. Pinning
  is also the better posture for an upload allowlist, which shouldn't silently widen on a
  dependency bump.
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

Today `POST /v1/documents` blocks for the whole ingest (10s–2min measured). A browser UI
cannot hold that: no progress, no cancel, and one worker occupied per upload. The 10-minute
gunicorn/nginx timeout now in place is the stopgap that keeps today's behaviour from
failing outright; it is not the fix.

- `DocumentRecord.status` grows `pending` / `processing` / `failed` alongside `ingested`,
  plus `error_message` and `updated_at`. The status column already exists and is already
  written — this widens its vocabulary rather than adding a concept.
- `POST /v1/documents` writes the row and enqueues in one transaction, returns **202** with
  the `doc_id`. `GET /v1/documents/{doc_id}` reports status. Polling is enough; SSE for
  upload progress is not worth a second streaming surface.
- Failures must land as `status="failed"` with a message. Right now nothing catches
  exceptions inside `ingest_document`, so a failed ingest leaves no row at all and the UI
  cannot distinguish "failed" from "never uploaded".
- `worker` becomes a compose service on the same image, `depends_on` postgres.
- **Bound the concurrency.** Docling is CPU-bound and already uses `DOCLING_NUM_THREADS`
  (default `os.cpu_count()`). Worker concurrency × Docling threads must not exceed the
  box's cores, or parallel ingests get slower than sequential ones. On the target 8-vCPU
  machine: 2 concurrent jobs × 4 threads.

### 5.2 Identity — the open decision, with a recommendation

The user's position: "really not sure how to do user logins", and email verification is
required. That combination argues for delegating.

**Recommended: self-hosted Keycloak** as one more compose service. It provides
registration, email verification, password reset, lockout, MFA, and OIDC discovery. The app
gets a `current_user` dependency that verifies a JWT against Keycloak's JWKS, and
provisions a `Tenant` + `User` row on first login. Costs: ~512MB–1GB of JVM heap on a
16GB box that also runs torch and Docling, plus a realm/client configuration surface that
is genuinely large for 1k users.

Alternative if Keycloak is too much: **own it**, with `argon2-cffi` for password hashing
(*not* the API keys' SHA-256 — opposite threat model, see `TECHNICAL_DECISIONS.md`),
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

---

## Blocked on Epics 2 and 3 (not a phase)

Listed so the sequence stays explicit. None of it is attemptable now, and none of it
blocks Phases 5 or 6:

| Item | Blocked on |
|---|---|
| `agent/nodes.py` structlog calls | Epic 3's agent |
| Rate limit on `/review` | Epic 3's review endpoint |
| `eval/agent_trace_assertions.py` + `tests/eval/` | Epic 3's agent **and** Epic 2's harness |
| Faithfulness SLO in `alerts.py` | Epic 2's RAGAS scores |

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

- **The scope rename touches the security boundary.** A silent mistake in `_build_filter`
  leaks across tenants without erroring — which is why 1.8 asserts on the filter directly.
- **`init_db()` won't create the auth tables** unless `app.auth.models` is imported. Fails
  as a confusing runtime error, not at startup.
- **`last_used_at` writes** add a DB write per request if implemented naively.
- **Re-ingest required** after 1.3. Harmless now, would need a migration path with real data.

Added for Phases 5-6:

- **`doc_ids` on `/ask` is a new cross-tenant read** if the ids aren't verified as owned
  before they reach the filter. Same silent-failure shape as the original `session_id` bug:
  it returns results rather than erroring.
- **Cookie auth plus permissive CORS is a total bypass**, because Starlette answers
  wildcard-plus-credentials by reflecting the caller's own origin. Guarded in `config.py`
  as of this phase's groundwork, with `tests/unit/test_cors.py` pinning it.
- **A 10-minute gunicorn timeout means one stuck request holds a worker for 10 minutes.**
  With `GUNICORN_WORKERS=2`, two of them stall the service. This is why 5.1 is a
  prerequisite and not a later optimisation.
- **Worker concurrency × `DOCLING_NUM_THREADS` can oversubscribe the box**, making parallel
  ingests slower than sequential ones. Neither number is meaningful alone.
- **Share links outlive the intent behind them.** A live (non-snapshot) shared link keeps
  querying the owner's corpus, so it leaks documents uploaded after it was created. The
  snapshot requirement in 5.8 is the mitigation and it is not optional.
- **procrastinate brings schema migrations** into a project that deliberately had none.
  Deploys gain a schema-apply step, and forgetting it fails at runtime as a missing table.
