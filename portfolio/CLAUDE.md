# portfolio

RAG over scientific documents, plus an LLM eval framework and an agentic
human-in-the-loop curation layer.

Built: Epic 1 (retrieve -> rerank -> generate, multi-format uploads, Docker stack), Epic 4
Phases 1-3 (API-key auth, tenant scoping, per-tenant rate limiting, docs), and Phase 5.1
(ingestion behind a Postgres-backed job queue) -- see `EPIC_4_PLAN.md` for the rest. Not
built: Epics 2 and 3, designed in `docs/IMPLEMENTATION_PLAN.md` only -- no eval framework,
no agent. Don't assume code for them.

## Producer/consumer split

`POST /v1/documents` returns **202** and enqueues; the `worker` service ingests. Two rules
hold this together, and both fail quietly if broken:

- **The api must not import the ingestion stack.** `app/worker/app.py` carries no
  `import_paths` and defers by task *name* so it never imports `tasks.py` (which pulls
  Docling). Adding a convenient `from app.ingestion...` to a router or to `formats.py` costs
  ~2s of startup and ~157MB per api process and breaks nothing visibly.
  `tests/unit/test_upload_formats.py` pins it. `app/ingestion/formats.py` therefore keeps a
  *pinned* extension list, drift-checked against Docling in that same test.
- **The worker CLI points at `app.worker.tasks.app`, not `app.worker.app.app`.** Importing
  `tasks.py` is what registers the task. Point it at `app.py` and the worker connects fine,
  then rejects every job as unknown -- which reads as a queueing bug.

Status lives on `DocumentRecord.status` (`pending`/`processing`/`ingested`/`failed`). The task
owns `processing`/`failed`; `ingest_document` owns the terminal `ingested` write, because
`scripts/ingest.py` and Streamlit call it directly and bypass the queue entirely.

Docs: `README.md` describes the system as it is; `TECHNICAL_DECISIONS.md` says why each
choice was made and what was rejected; `docs/IMPLEMENTATION_PLAN.md` is the original plan,
kept as history and outdated on purpose. When a decision changes, update
`TECHNICAL_DECISIONS.md` -- not the plan.

## Skills

Ours, in `.claude/skills/`:

- **`verify`** — the gate, and the two ways it lies (silently skipped service-backed suites; the
  pre-release-interpreter workaround that also rewrites `uv.lock`). Use it instead of running the
  commands from memory.
- **`add-endpoint`** — the per-route checklist. Authorization here is per-route *and* per-query,
  so a forgotten `CurrentTenant` or a `doc_id` lookup without `tenant_id` in the WHERE clause is
  a silent leak rather than an error.
- **`run-stack`** — bringing the stack up, minting a key, and tracing one document across
  api → job → worker → Qdrant → registry when it misbehaves.

Plus 10 `qdrant-*` skills vendored verbatim from github.com/qdrant/skills at a pinned commit —
see `.claude/skills/VENDORED.md` for provenance and how to refresh. Reach for
`qdrant-multitenancy` before touching the tenant filter and `qdrant-search-quality` when Epic 2's
eval work starts, rather than re-deriving either.

One open finding from them: **no payload index exists on `metadata.tenant_id`**, and the
multitenancy skill calls for a keyword index with `is_tenant=true`. Harmless at 6 documents,
not at the 1k-user target. Details in `VENDORED.md`.

## Verification gate

Install the hooks once so this isn't memory-dependent:

    cd portfolio && uv run pre-commit install -c .pre-commit-config.yaml

The `-c` is required (monorepo: git's hooks are at the root, the config lives here). Hooks are
`repo: local` calling `uv run`, so tool versions come from `uv.lock` rather than pre-commit's own
pins -- don't switch them to `astral-sh/ruff-pre-commit`, which reintroduces exactly that drift.
Python hooks are scoped `^portfolio/`; unscoped, pre-commit hands ruff the sibling projects' files.


All four before pushing. `ty.toml` sets `error-on-warning`, so a warning fails:

    uv run ruff check . && uv run ruff format --check .
    uv run ty check
    uv run pytest tests/unit
    cd .docker && docker compose config    # after any compose/Dockerfile edit

**Qdrant's filtering is covered; its network path is not.**
`tests/unit/test_qdrant_filtering.py` runs `_build_filter` through `qdrant_client`'s in-memory
engine with fake embeddings, so tenant isolation and the delete-then-insert contract are proved
by execution, in CI, with no server and no API keys. What remains untested is the real client
over the wire -- which is where the point-ID constraint escaped to production -- so don't say
"Qdrant is tested" without that qualifier.

The auth, rate-limit, and worker/registry suites hit a real Postgres or Redis and *skip* when
unreachable, so a green local run may have tested less than it looks; CI provides both services
and asserts none of the three skipped.

## Health checks

`GET /health/live` is static; `GET /health/ready` probes Postgres, Qdrant, and Redis and 503s
when a *required* one is down. Three things not to undo:

- **Liveness must not check dependencies.** A liveness probe failing on a Postgres blip gets the
  process restarted, which fixes nothing and turns a hiccup into a restart loop.
- **Redis is reported but not required.** Rate limiting fails open, so its outage degrades a
  guardrail, not the API. Marking it required would pull instances from rotation over an
  optional component.
- **Readiness must not construct `QdrantStore`.** Its `__init__` sends a throwaway *probe
  embedding* to detect vector size, so that would bill a Voyage call every 30 seconds and report
  Qdrant down whenever Voyage was. `health.py` uses a bare cached `AsyncQdrantClient`.

The container `HEALTHCHECK` targets readiness, so `depends_on: service_healthy` means "can
serve". It previously targeted `GET /`, which returned a static body and so reported healthy
with every dependency down.

Missing `ANTHROPIC_API_KEY`/`VOYAGE_API_KEY` fails the api at boot (`require_provider_credentials`
in the lifespan) and fails an individual *job* in the worker, so the reason lands in
`documentrecord.error_message` rather than killing the worker. Deliberately not a `Settings`
validator -- that would break the unit suite, `ty`, and `scripts/create_tenant.py`, none of which
need provider keys.

## Never

- **Never commit `.env`.** It holds a real LangSmith API key. `.env.example` stays a
  template with placeholders only -- no real secrets, ever.
- **Never remove the delete step from `QdrantStore.upsert`.** It deletes every point
  for the document's `doc_id` before inserting, and that is what makes re-ingestion
  correct -- not the point-id derivation. Chunk ids encode position
  (`{doc_id}-text-0000`, `fig-{page}-{index}`), so anything changing how many chunks a
  document yields (`chunk_max_tokens`, a Docling upgrade detecting one more figure,
  toggling `do_ocr`) shifts every later id: the new ids insert cleanly while the old
  points stay behind, still matching the tenant filter, still retrievable, now stale.
  There is no other cleanup path.
- **Never renumber figure ids** in `figure_extractor.extract_figures`. A picture item
  with no renderable image still consumes its `enumerate` index on purpose;
  `tests/unit/test_figure_ids.py` pins this.
- **`uv.lock` is committed, and `--locked` is used everywhere** (Dockerfile, CI). It was
  gitignored, which this file previously recorded as deliberate; that was reversed because it
  made builds non-reproducible -- the image re-resolved at build time, so CI could test a
  dependency set nobody deployed, and a stale local venv had nothing to sync against. After
  editing `pyproject.toml`, run `uv lock` and commit the result.
  **`--locked`, not `--frozen`** -- verified, because the names suggest the opposite of what they
  do: `--frozen` uses the lock without checking it, so a dependency added and not re-locked is
  silently omitted and fails at runtime as an ImportError. Only `--locked` errors with "the
  lockfile needs to be updated".

## Failure contracts

Things that look correct and aren't:

- **Qdrant point IDs must be an unsigned integer or a UUID.** Chroma accepted
  arbitrary strings; Qdrant rejects a `chunk_id` with a 400. Hence the uuid5
  derivation above. `chunk_id` itself stays in the payload metadata -- citations
  read it from there, never from the point ID.
- **Qdrant filters must be real `qdrant_client.models.Filter` objects.** The
  Mongo-style dict shorthand (`$in`/`$and`) only ever existed on the deprecated
  `Qdrant` class. Getting this wrong doesn't error -- it silently breaks tenant
  scoping, leaking one tenant's uploads into another tenant's results.
- **`QdrantVectorStore` has no native async client.** `asimilarity_search` is
  `VectorStore`'s thread-pool shim and `upsert` is sync. That's why
  `ingest_document` offloads through `asyncio.to_thread` instead of just being
  `async def`.
- **Docling parsing is CPU-bound.** Wrapping it in `async def` does not free the
  event loop; it has to go through `asyncio.to_thread` or one upload stalls every
  other request on that worker.
- **Compose `${VAR}` substitution cannot see `../.env`.** It resolves against the
  shell or a `.env` beside the compose file only. Anything a *service* needs from
  `portfolio/.env` must arrive via `env_file:`. This silently broke the postgres
  healthcheck once: the container had the real password while the healthcheck
  still checked the fallback.
- **`cap_drop: [ALL]` strips root's privileges too** -- they're capability-gated,
  not UID-gated. nginx needs `NET_BIND_SERVICE, SETUID, SETGID, CHOWN` (its master
  process chowns `/var/cache/nginx` even though the entrypoint scripts don't);
  postgres needs `CHOWN, SETUID, SETGID, DAC_OVERRIDE, FOWNER`. Drop any of those
  and the container crash-loops.
- **postgres `initdb` runs once, on an empty volume.** Changing `POSTGRES_*` after
  first boot does nothing until `docker compose down -v`.
- **postgres 18+ wants the volume at `/var/lib/postgresql`, not `.../data`.** From 18 the
  official images store data in a major-version-specific subdirectory so `pg_upgrade --link`
  doesn't cross a mount boundary. The pre-18 mount path makes the entrypoint refuse to start
  with "there appears to be PostgreSQL data in: /var/lib/postgresql/data (unused
  mount/volume)" -- which reads as a corrupt volume rather than a wrong path. Bumping the
  image major version means checking the mount, and a pre-18 volume needs `pg_upgrade` or a
  fresh volume; hence `postgres_data_v18`.
- **`SQLModel` datetime fields need an explicit `sa_column`** in any module using
  `from __future__ import annotations` with `datetime` imported under `TYPE_CHECKING`.
  Without it SQLModel infers the column type from an annotation that is a string it can't
  resolve, failing at *import* time with `issubclass() arg 1 must be a class` -- which
  reads like a library bug rather than a missing argument. Use
  `Column(DateTime(timezone=True))`, which also keeps values aware -- see the next entry.
- **...and `datetime` must ALSO be a runtime import in model modules.** `sa_column` fixes
  the import-time half only. `model_dump()` makes pydantic resolve those stringified
  annotations against the module's *runtime* globals, so a TYPE_CHECKING-only `datetime`
  raises ``PydanticUserError: `X` is not fully defined`` from inside `model_dump`. This is
  not hypothetical: it made every `save_document_record` call fail *after* the Qdrant upsert
  had already committed, so documents were searchable with no row in Postgres, and it
  survived for weeks because it only triggers when a row is actually written -- no import,
  lint, or type check sees it. Import `datetime` normally and `# noqa: TC003` the linter.
  `tests/unit/test_worker_enqueue.py` now covers the registry write path.
- **Postgres is the only database engine.** No SQLite anywhere -- not for tests, not for
  Epic 3's checkpointer or incoming queue. Datetime arithmetic in `auth/service.py` relies
  on `DateTime(timezone=True)` round-tripping an aware value, which is a *Postgres*
  guarantee; SQLite returns naive datetimes and would raise "can't subtract offset-naive
  and offset-aware datetimes". Rather than defensively normalizing, a test pins the
  assumption (`test_stored_timestamps_come_back_timezone_aware`) so a schema change that
  drops `timezone=True` fails loudly. Substituting SQLite in tests would hide exactly this
  class of bug.
- **`app/db.py::init_db` must import every model module.** `SQLModel.metadata` is
  populated as an import side effect, so a table whose module was never imported is
  silently skipped by `create_all` and only fails later as "relation does not exist".
- **Schema creation is guarded by a Postgres advisory lock, not just the asyncio one.**
  `init_db`'s `asyncio.Lock` only serializes coroutines inside one process, and the real
  concurrency is `GUNICORN_WORKERS` processes booting at once plus the `worker` container.
  Both `create_all`'s checkfirst and procrastinate's existence check are check-then-create,
  so the loser crashes at startup with `DuplicateObject: type "procrastinate_job_status"
  already exists` -- which reads as a database fault. Observed on the first real boot.
  `pg_advisory_xact_lock` is transaction-scoped on purpose: a session-level lock leaked by a
  crashed process would deadlock every later boot.
  `test_concurrent_processes_can_initialise_the_schema` pins it, and has to use real
  subprocesses -- an `asyncio.gather` version passes even with the lock removed.
- **procrastinate's schema is all-or-nothing.** `schema.sql` has 3 `CREATE TYPE`, 4
  `CREATE TABLE`, and 18 `CREATE FUNCTION`, none of them `OR REPLACE`, and the existence
  check keys only on `procrastinate_jobs`. A partially-applied schema (interrupted apply,
  or a hand-written partial drop) therefore fails every subsequent start and cannot be
  repaired incrementally -- reset with `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`
  on a throwaway database, or drop the volume.

## Config invariants

- **`PORT` is the single source of truth** for the api port: gunicorn's `--bind`,
  the compose port mapping, and nginx's upstream (baked in at nginx build time by
  `sed` on the `__API_PORT__` placeholder). Deliberately not nginx's `envsubst`
  templates -- those substitute every `$`-token and would wipe nginx's own
  `$scheme`/`$remote_addr` too. `GUNICORN_TIMEOUT` and `MAX_UPLOAD_SIZE_MB` reach
  nginx the same way (`REQUEST_TIMEOUT`/`MAX_UPLOAD_MB` build args), and the nginx
  build fails on any unsubstituted `__PLACEHOLDER__`.
- **Compose needs `--env-file` or none of that works.** Run it as
  `docker compose -f .docker/docker-compose.yml --env-file .env up` from `portfolio/`.
  Compose reads `${VAR}` from the shell or a `.env` in the *project directory*
  (`.docker/`) -- never from `portfolio/.env`, and `env_file:` on a service doesn't
  help (different mechanism). Measured: both documented invocation styles silently
  used the fallback defaults. And the halves disagree, so it doesn't error --
  `PORT=9000` in `.env` alone gives gunicorn on 9000, a mapping of `8000:8000`, and
  an nginx upstream on `api:8000`.
- **Timeouts are one value, not three.** gunicorn `--timeout` and nginx's
  `proxy_read_timeout`/`client_body_timeout` are all 600s from `GUNICORN_TIMEOUT`,
  because the shorter one silently becomes the real budget: nginx-first is a 504 with
  the worker still burning CPU, gunicorn-first is a SIGKILL mid-parse that reaches the
  client as a bare connection failure naming nothing. `proxy_connect_timeout` stays 75s
  on purpose -- nginx caps it there regardless, so a larger number is decoration.
  The 600s gunicorn value is a stopgap for synchronous ingestion; `client_body_timeout`
  is not (bytes still arrive over the wire once uploads become jobs).
- **`cors_allow_credentials` + `"*"` origins is refused at startup.** Starlette answers
  that pair by reflecting the caller's own `Origin` with `Allow-Credentials: true`, so
  every site on the internet becomes trusted. The wildcard default is only inert while
  credentials are off and `cors_allow_headers` is empty. `tests/unit/test_cors.py` pins
  it; don't relax the guard to make a frontend work -- name the origins.
- **`POSTGRES_USER`/`PASSWORD`/`DB` is one set serving two consumers**: the postgres
  image, and `app/config.py`'s `Settings`, which assembles `DATABASE_URL` from them.
  Don't reintroduce a parallel `DB_USER`/`DB_PASSWORD`/`DB_NAME`.
- **`requires-python` is `>=3.14`** because `uuid.uuid7()` is 3.14 stdlib and the
  Dockerfile pins `python:3.14-slim`. Caveat for local work: if the only 3.14 available
  is a pre-release, pydantic may fail to build models on it
  (`_eval_type() got an unexpected keyword argument 'prefer_fwd_module'`). That's the
  interpreter, not this code -- run the suite on 3.14 final, or temporarily relax the
  floor to test and restore it before committing.

## The tenant boundary

`tenant_id` is the *only* thing scoping retrieval, and a wrong filter returns results
rather than raising -- it fails silently, as cross-tenant data access.

- It must come from `api/deps.py::current_tenant` (a verified API key) and nowhere else.
  Never from a request body, query string, or form field. `AskRequest` sets
  `extra="forbid"` so a client trying to smuggle one gets a 422 instead of being ignored.
- `streamlit_app/Home.py` calls the pipeline **in process**, so the FastAPI dependency
  never runs for it. It authenticates via `auth.service.resolve_tenant` instead -- one
  auth implementation, not two. It must never mint its own tenant id.
- `GLOBAL_TENANT` (`"global"`) is the shared corpus: readable by all, owned by none. Real
  ids are `uuid7().hex`, so no tenant can ever be issued that value.
- `tests/unit/test_tenant_scoping.py` asserts on the built filter directly, which is why
  it catches leaks without a live Qdrant.

## Rate limiting

- Hand-rolled in `app/rate_limit.py`, deliberately not `slowapi`: `limits[redis]` requires
  `redis<8.0.0` against this project's `redis>=8.0.1` (uv calls it unsatisfiable), and its
  redis-py storage is synchronous, so every check would block the event loop.
- The check is a **Lua script** so it is atomic. A read-then-write version lets concurrent
  requests all observe a count under the limit and all proceed.
- **Fails open**: unreachable Redis allows the request and logs a warning. A guardrail's
  outage must not become the API's outage. `docker-compose.yml` therefore has `api` wait on
  redis being healthy, so the gap isn't silently open at startup.
- The Redis client is cached **per event loop**, not per process -- a `redis.asyncio` client
  binds its pool to the creating loop, so a process-wide singleton breaks under repeated
  `asyncio.run()` (Streamlit, CLIs, per-test loops).
- `api/main.py`'s error handler must forward `exc.headers`; it overrides FastAPI's default,
  so dropping them silently strips `Retry-After` from every 429.
