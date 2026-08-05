# portfolio

RAG over scientific documents, plus an LLM eval framework and an agentic
human-in-the-loop curation layer.

Built: Epic 1 (retrieve -> rerank -> generate, multi-format uploads, Docker stack), Epic 4
Phases 1-3 (API-key auth with scopes, expiry, and CRUD; tenant scoping; per-key rate
limiting; docs), and Phase 5.1 (ingestion behind a Postgres-backed job queue) -- see
`docs/EPIC_4_PLAN.md` for the rest. Not built: Epics 2 and 3, designed in
`docs/IMPLEMENTATION_PLAN.md` only -- no eval framework, no agent. Don't assume code for
them. The one exception is `app/retrieval/document_scope.py`, pulled out of Epic 2 early:
naming a filename in an `/ask` question scopes retrieval to that document. It is **not** the
intent router, and there is still no golden set and no metric, so nothing measures whether
an answer is good.

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
Streamlit calls it directly and bypasses the queue entirely.

## Docs, and which one to write in

**Read `docs/MEMORY.md` first in a new session.** It holds what this file deliberately does not:
where the work actually is, the user's standing directives, open questions, measurements
already taken, and a session log. Nothing else carries that across sessions. **Update it at
the end of any session that changed something** -- the protocol is at the top of the file.

- `README.md` -- the system as it is.
- `CHANGELOG.md` -- what a *user* would notice changed, and what breaks on upgrade. Keep it to
  observable behaviour: routes, response fields, env vars, defaults, removals. The reasoning
  belongs in `docs/MEMORY.md`; if an entry needs a paragraph of "because", it is in the wrong
  file. `.claude/skills/changelog` has the conventions.
- `docs/PATTERNS.md` -- the recurring shapes and the failure each one prevents. Also lists what is
  deliberately *absent*, so a reviewer doesn't "fix" it.
- `docs/TECHNICAL_DECISIONS.md` -- why each choice, and what was rejected. Update this when a
  decision changes, **not** the plan.
- `docs/EPIC_*_PLAN.md` -- what is planned, in order.
- `docs/IDEAS.md` -- the parking lot: anything that might be worth doing but isn't scheduled,
  plus a *considered and rejected* table so dead ideas don't come back. Add freely; an idea
  that graduates moves into an epic plan and is deleted from there.
- `docs/IMPLEMENTATION_PLAN.md` -- the original plan, kept as history and outdated on purpose.

A durable imperative rule goes *here*. Current state goes in `docs/MEMORY.md`. Mixing them buries
the rules in changelog.

**The repo root `../CLAUDE.md` holds the general rules** -- the 15 numbered coding rules, the
document-set split above, the working agreements on secrets, lockfiles, and the gate, and the
delegation rule for subagents. It is loaded alongside this file, so don't restate it here. What
belongs *here* is anything true of only this project: the failure contracts below are the point,
because each names a specific file and a specific way that file fails.

## Subagents

Six in `.claude/agents/`, **all read-only**, none permitted to report that it ran anything.
`../CLAUDE.md` holds the rule about what is never delegated -- the gate, a failure-contract edit,
and the final verdict on a finding. They are named by *task*, not by job title: a role name
("senior engineer", "QA") invites persona drift and has no fixed question, which is the property
that makes delegation work here.

Sweeps -- wide, shallow, one fixed question:

- **`doc-consistency`** — sweeps the document set for claims the code no longer supports or that
  contradict another document. It exists because a sentence that was true when written, in a file
  nobody re-reads, is this repo's most common defect: three files claimed the `m=0`/`payload_m`
  Qdrant trade was blocked by a shared corpus that had been removed hours earlier, and it was
  found by accident months later. Run it after any removal or rename.
- **`route-audit`** — every route in `app/api/routers/` against the `add-endpoint` checklist. The
  boundary is re-established per route *and* per query, so exhaustive beats spot-checking; the
  definition carries the known false positives (health routes have no auth or rate limit on
  purpose) so they stop being re-reported.
- **`candidate-triage`** — licence and provenance first, then fit against the recorded decisions,
  for anything third-party. Encodes the traps that have actually sunk candidates here: hub skills
  that route to a rejected stack, shipped "evaluators" that measure their own toy retriever, and
  descriptions broad enough to fire on every task.

Per-change checks -- run against a diff or a proposal:

- **`contract-review`** — a diff against § Never, § Failure contracts, § Config invariants and
  `PATTERNS.md`. Deliberately **not** a general code review: `/code-review`, `/security-review` and
  `/simplify` already do that and cannot know that dropping one `delete` from `QdrantStore.upsert`
  leaves retrievable stale points with the suite green. It is told to report nothing a competent
  outside reviewer would also find.
- **`test-gaps`** — what the change leaves untested, and which tests would still pass with the guard
  deleted (rule 15). It **must not run the suite**; a pass reported by an agent is a claim, which is
  rule 12 one level removed. Carries the three shapes that have fooled this suite before: a boundary
  test with a limit of one, a membership assertion where an exact-set assertion is possible, and an
  in-process test of a cross-process race.
- **`design-review`** — a proposal against `TECHNICAL_DECISIONS.md`, `IDEAS.md`'s rejected table and
  the epic plans, *before* it is built. Its one required distinction is **revisit** (the reasoning
  still holds and must be overturned) versus **stale conflict** (the reason expired, as the graphrag
  Python-floor argument did) — those need opposite responses.

**No coder agent, deliberately.** Every route here touches the tenant boundary, so a writing agent
hits a failure contract almost immediately, and the surveys run on 2026-08-05 produced good breadth
*plus* several confident findings that were wrong on inspection — a cost that is one verification pass
for a read-only sweep and committed code from a coder. When work genuinely is file-disjoint (a rename
across N call sites, a mechanical migration), spawn worktree-isolated subagents per slice or use
`/batch`, and integrate and run the gate here. That needs a precise brief, not a role.

**Definitions are picked up at session start only**, and discovery walks **up** from the working
directory rather than down as skills do. Both measured; the probe detail and the open question about
whether a repo-root session resolves these are in `docs/MEMORY.md`.

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
- **`changelog`** — what belongs in `CHANGELOG.md` versus `docs/MEMORY.md`'s session log, and why
  most commits produce no entry at all.

Vendored verbatim, at pinned commits, with provenance and refresh steps in
`.claude/skills/VENDORED.md`:

- **10 `qdrant-*`** from github.com/qdrant/skills. Reach for `qdrant-multitenancy` before touching
  the tenant filter and `qdrant-search-quality` when Epic 2's eval work starts, rather than
  re-deriving either.
- **`langchain-dependencies`** and three `langgraph-*` (`fundamentals`, `persistence`,
  `human-in-the-loop`) from github.com/langchain-ai/langchain-skills. The LangGraph three are
  installed ahead of use, for Epic 3's agent; `langgraph-persistence` is the one to read before
  wiring the Postgres checkpointer.
- **`postgres-database-migration`** from github.com/timescale/pg-aiguide — one skill of that
  repo's ten. Read it before writing any `ALTER TABLE` by hand, which is the only way a column
  gets added here: there is no Alembic and `create_all` never adds one (see the failure contract
  below). It carries the lock level of every common DDL operation, which is the thing that
  decides whether a one-millisecond statement stalls the whole API. Note that **`CREATE INDEX
  CONCURRENTLY` cannot run inside a transaction** and `init_db` does all its DDL inside one, so a
  concurrent index needs its own autocommit connection — the skill can't know that.

**Take narrow leaves from these repos, never the hubs.** A hub claims a whole topic, and the topics
here are decided, so a hub argues back at the decision record — which is worse than no skill.
`langchain-rag` and `pg-aiguide`'s `postgres` are both excluded on that ground and must stay
excluded; `VENDORED.md` has the per-skill reasoning and should not be restated here.

**The one finding the qdrant set produced is closed** (2026-08-03): `qdrant_store._ensure_payload_indexes` indexes
`metadata.tenant_id` with **`is_tenant=True`** and `metadata.doc_id` as a plain keyword, from
`QdrantStore.__init__`. **`is_tenant` is not a synonym for "indexed"** -- it tells Qdrant the
field identifies tenants, so a tenant's vectors are stored together and a tenant-filtered
search is served by sequential reads rather than degrading toward a scan at the 10k-tenant x
10-document target. Don't drop the flag while keeping the index and assume it is equivalent.
`metadata.chunk_type` is deliberately *not* indexed (no production caller passes `chunk_types`).
Details in `.claude/skills/VENDORED.md`.

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

Five suites hit a real Postgres or Redis and *skip* when unreachable -- auth-touch, rate-limit,
worker/registry, key-management and the `create_tenant` CLI -- so a green local run may have
tested far less than it looks (59 tests' worth). CI provides both services and asserts none of
the five skipped. It asserted three for a while, which let the two newer ones skip in CI silently.

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
- **`create_all` creates missing *tables*, never missing *columns*.** Adding a field to an
  existing model changes nothing on a database that already has the table -- `init_db`
  reports success and the next query fails with `column ... does not exist`. There is no
  Alembic, so a new column means dropping the table (fine while it holds nothing worth
  keeping) or writing the `ALTER TABLE` by hand. `ApiKey.expires_at` was added this way,
  against an empty table.
- **An empty `ApiKey.scopes` list means EVERY scope, not none.** Same rule as `expires_at
  IS NULL` meaning never: absent data must mean the pre-existing behaviour, or adding a
  column becomes an outage for every key minted before it. `auth/scopes.py::granted` is the
  one place that reading lives -- resist "fixing" a bare `if not key.scopes`. The consequence
  is that an *omitted* scope list on `POST /v1/keys` is a privilege escalation the `exceeds`
  guard cannot see (it is vacuously satisfied by an empty request), which is why
  `auth/management.py` materialises it into the caller's own scopes before storing.
- **Tests authenticate by overriding `deps.current_principal`, never `current_tenant`.**
  `require_scopes` and `rate_limited` both depend on the principal, so overriding the
  narrower dependency leaves them resolving a real key and every authenticated test gets a
  401 -- which reads as a broken route rather than a broken fixture.
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
- **A figure's caption is its only searchable text**, so an unusable caption is worse than
  no figure. Docling reports every embedded image region as a `PictureItem` -- contact icons,
  logos, horizontal rules -- indistinguishable from a chart. A one-page CV produced five
  "figures", all ~20x20px icons; the vision model answered each with "I'm not able to see the
  image you're referring to", and those refusals became chunks that then won reranking and
  became what an answer was grounded in. `figure_extractor` therefore drops images below
  `figure_min_dimension_px` *before* the vision call and captions matching
  `_UNUSABLE_CAPTION_MARKERS` (or shorter than `figure_min_caption_chars`) after it. Both drops
  must preserve the `enumerate` index -- see the "never renumber" rule above.
- **A successful parse does not mean an ingestible document.** A scanned, image-only PDF
  parses fine and yields no text: a real 2MB flyer extracted 30 characters with `do_ocr=False`
  versus 395 with it on. Recording that as `ingested` with `chunk_count=0` is a lie the user
  can only discover by asking a question and getting someone else's document back, so
  `ingest_document` raises `EmptyDocumentError` instead.
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
- **Every credential in `Settings` is a `SecretStr`**, and `.get_secret_value()` marks each
  point where one escapes (six: four in `config.py`, one each in `db.py` and `worker/app.py` --
  this said eight, and `config.py`'s own copy of the count was wrong too). One object
  holds the Anthropic, Voyage and LangSmith keys plus the Postgres password, so anything that
  renders it renders all four -- and this repository is public. `database_url` is a `SecretStr`
  too: it embeds the password, so masking the password alone was theatre.
  **A `SecretStr` is truthy by length**, so a credential check must read
  `.get_secret_value().strip()` -- a bare `if not value` accepts three spaces as a key and then
  fails every request at the provider, which reads as a revoked key rather than an unset one.
  `tests/unit/test_secrets.py` sweeps every field whose name ends in `_key`/`_password`/
  `_secret`/`_token`, so a new credential added as a plain `str` fails the suite.
- **`requires-python` is `>=3.13`**, while Docker and CI run 3.14 -- deliberately. The
  floor is what the code requires; nothing requires 3.14 since `app/ids.py` took over
  `uuid7` with an RFC 9562 fallback. **Never call `uuid.uuid7()` directly** -- it raises
  `AttributeError` on 3.13 and the floor permits 3.13. Use `app.ids.new_id()`.
  This matters locally: on a 3.14 *pre-release* pydantic fails to build models
  (`_eval_type() got an unexpected keyword argument 'prefer_fwd_module'`), so a 3.14-floored
  project could not run its own suite. **`.python-version` pins local dev at 3.13** so
  `uv venv` lands there without a flag; keep it, and keep it out of the image
  (`.dockerignore`), because `python:3.14-slim` has no 3.13 and `UV_PYTHON_DOWNLOADS=0`
  forbids fetching one. CI overrides the pin per matrix leg and then asserts the interpreter
  it actually got -- a pin that silently won would make the 3.14 leg a second 3.13 run.

## The tenant boundary

`tenant_id` is the *only* thing scoping retrieval, and a wrong filter returns results
rather than raising -- it fails silently, as cross-tenant data access.

- It must come from `api/deps.py::current_tenant` (a verified API key) and nowhere else.
  Never from a request body, query string, or form field. `AskRequest` sets
  `extra="forbid"` so a client trying to smuggle one gets a 422 instead of being ignored.
- `streamlit_app/Home.py` calls the pipeline **in process**, so the FastAPI dependency
  never runs for it. It authenticates via `auth.service.resolve_tenant` instead -- one
  auth implementation, not two. It must never mint its own tenant id.
- **There is no shared tenant, and do not reintroduce one.** A `GLOBAL_TENANT = "global"` used
  to tag a curated corpus readable by everyone, which meant `_build_filter` matched
  `MatchAny([global, caller])` and the honest description of isolation was "your documents *plus
  global*". Removed 2026-08-03. The filter now matches **one** tenant via `MatchValue`, and it is
  deliberately not a single-element list: a list invites a second element, which is exactly the
  leak this boundary exists to stop.
- **`tenant_id` is required everywhere it appears, with no default.** `_build_filter` raises on an
  empty one, and `Chunk`, `chunk_document`, `ingest_document`, `Retriever.retrieve` and
  `AnswerService.answer` all take it positionally-or-by-keyword with no fallback. The old default
  was `GLOBAL_TENANT`; with the corpus gone, any default at all would silently file one tenant's
  data under another name, and retrieval would return it rather than error.
- `tests/unit/test_tenant_scoping.py` asserts on the built filter directly, which is why
  it catches leaks without a live Qdrant. It asserts the permitted set **exactly** -- the weaker
  `a in / b not in` form passed for months while the filter also admitted `global`.

## Rate limiting

- **`limits` does the counting; `app/rate_limit.py` is the policy.** The library is battle-tested
  at the part that was never the problem here -- atomic counting in Redis. Which subject, which
  bucket, what happens when Redis dies, and what the client is told are all ours, because
  `limits` has no opinion about any of them and each one has cost a bug before. Was hand-rolled
  Lua until 2026-08-03; `docs/TECHNICAL_DECISIONS.md` has the full comparison and the numbers.
- **Import from `limits.aio`, never `limits.storage`/`limits.strategies`.** The synchronous
  modules are what `slowapi` imports (`extension.py:514` is a bare `self.limiter.hit(...)`), so
  every check there blocks the event loop -- 65.5 ms versus 18.5 ms at 200 concurrent checks.
  Use `implementation="redispy"` so it runs on the `redis[hiredis]>=8` already here: the
  `redis>3,<8.0.0` pin belongs to the *synchronous* `limits[redis]` extra only, and
  `limits[async-redis]` would add coredis for nothing.
- **`limits` fails CLOSED; `check` must keep failing open.** An unreachable Redis raises
  `redis.exceptions.ConnectionError` straight out of `hit()`. Both `hit` and `get_window_stats`
  sit inside one `try` -- narrowing it to just `hit` would 500 a caller whose budget was already
  spent. Two tests pin this, including the failure *between* the calls.
- **`remaining` is a second observation, not part of the decision** -- `hit()` returns a bool and
  the numbers come from `get_window_stats()` afterwards. Under concurrency it can disagree with
  what the next request is granted. That precision was real and is gone; it is the price of the
  swap, not an oversight, and the concurrency test says so where it used to assert distinct
  `remaining` values.
- **`MovingWindowRateLimiter`, never `SlidingWindowCounterRateLimiter`.** The counter shipped for
  one day and its failure is subtle enough to re-choose by accident: it **does not honour its own
  `Retry-After`**. On a 10-request/2-second budget it advertises `reset in 2.00s`, identical to the
  exact strategy, then grants **2 of 10** to a caller that waited 2.2 s, with the full budget back
  only at 4.2 s. It weights the previous window's count instead of expiring individual requests, so
  obeying the header is not enough and the natural client reaction is a tight retry loop. It also
  reports `X-RateLimit-Reset: 0` on the first request of a fresh window (`120 % 60 == 0` against a
  2x-window TTL), which needed a clamp that the exact strategy makes unnecessary. Two tests hold
  the line, both red in 5 of 5 mutation runs: the full-budget-returns test and the 1x-vs-2x TTL
  bound in the expiry test. It costs 1464 bytes per key against the counter's 120 -- ~29 MB at
  10k tenants x 2 scopes, which is nothing on 16 GB. `FixedWindowRateLimiter` is cheaper again and
  wrong: a caller straddles the boundary and spends two budgets back to back.
- **Pass `max_connections`.** `limits` defaults it to 100 and its pool raises
  `MaxConnectionsError` rather than queueing, so the default turns burst load into 500s.
- **`X-RateLimit-*` goes on successes too, not just 429s**, or the budget is only discoverable
  by exceeding it. Set via the injected `response: Response` in `rate_limited`. When Redis is
  unreachable `check` returns None and **no headers are emitted** -- a fabricated full budget
  would report the guardrail as intact while it is absent.
- **Fails open**: unreachable Redis allows the request and logs a warning. A guardrail's
  outage must not become the API's outage. `docker-compose.yml` therefore has `api` wait on
  redis being healthy, so the gap isn't silently open at startup.
- The Redis client is cached **per event loop**, not per process -- a `redis.asyncio` client
  binds its pool to the creating loop, so a process-wide singleton breaks under repeated
  `asyncio.run()` (Streamlit, CLIs, per-test loops).
- `api/main.py`'s error handler must forward `exc.headers`; it overrides FastAPI's default,
  so dropping them silently strips `Retry-After` from every 429.
