# Epic 4 — Production Rigor: implementation plan

Scope note: roughly half of Epic 4 depends on Epics 2 and 3, which are not built. This
plan covers the whole epic and marks blocked work explicitly rather than pretending the
epic is one unblocked unit. Phases 1-3 are buildable today; 4 is partial; 5 waits.

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

## Phase 5 — Blocked on Epics 2 and 3

Listed so the sequence is explicit, not to be attempted now:

| Item | Blocked on |
|---|---|
| `agent/nodes.py` structlog calls | Epic 3's agent |
| Rate limit on `/review` | Epic 3's review endpoint |
| `eval/agent_trace_assertions.py` + `tests/eval/` | Epic 3's agent **and** Epic 2's harness |
| Faithfulness SLO in `alerts.py` | Epic 2's RAGAS scores |
| User login UI + key-management screen | Product decision below |

**Open decision for the login half:** hand-rolling password auth means owning reset flows,
email verification, lockout, and timing-safe comparison. Recommend `fastapi-users` or an
external IdP (Keycloak self-hosted; WorkOS/Clerk/Auth0 hosted) with the tenant read from a
verified JWT claim. API keys stay hand-rolled — they're simple and safe with high-entropy
secrets. Does not block Phases 1-4.

## Dependencies added

| Package | Phase | For |
|---|---|---|
| `slowapi` | 2 | Rate limiting |
| `fastapi-users` *or* IdP client | 5 | Password login only, if not delegated |

No new dependency for Phase 1: `secrets` and `hashlib` are stdlib, `sqlmodel` and
`psycopg` are already present.

## Risks

- **The scope rename touches the security boundary.** A silent mistake in `_build_filter`
  leaks across tenants without erroring — which is why 1.8 asserts on the filter directly.
- **`init_db()` won't create the auth tables** unless `app.auth.models` is imported. Fails
  as a confusing runtime error, not at startup.
- **`last_used_at` writes** add a DB write per request if implemented naively.
- **Re-ingest required** after 1.3. Harmless now, would need a migration path with real data.
