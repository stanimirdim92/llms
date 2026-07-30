---
name: run-stack
description: Bring up the portfolio Docker stack (api, worker, streamlit, qdrant, postgres, redis, nginx), mint an API key, and ingest the document corpus. Use when asked to run, start, boot, restart, or verify the portfolio app end to end, when a service is crash-looping or a port is already allocated, when an upload is stuck pending, or when ingestion needs to run against a live Qdrant/Postgres.
---

# Running the portfolio stack

Two modes. Full stack for verifying real behavior, data-services-only for
iterating on app code without rebuilding images.

## Prerequisites

`portfolio/.env` must exist (copy from `.env.example`) with at minimum:

- `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` -- required, nothing works without them.
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` -- required uncommented; the
  postgres image refuses to start without a password, and compose no longer supplies
  a fallback.

Everything else (`PORT`, pool sizes, CORS, logging) has a working default.

## Full stack

    cd portfolio
    docker compose -f .docker/docker-compose.yml --env-file .env up --build

**`--env-file` is required, not optional.** Compose resolves `${VAR}` substitutions
from the shell or from a `.env` in the *project directory* -- which is `.docker/`, not
`portfolio/` and not the cwd. Measured both invocation styles with a value set only in
`portfolio/.env`: both silently used the fallback defaults. A service's
`env_file: ../.env` is a different mechanism (it populates a container's environment)
and does not help here.

Nothing errors when the flag is missing, because the two halves disagree rather than
fail: `PORT=9000` in `.env` alone gives gunicorn bound to 9000 inside the container, a
published mapping of `8000:8000`, and an nginx upstream pointing at `api:8000`.
`GUNICORN_TIMEOUT` and `MAX_UPLOAD_SIZE_MB` behave the same way -- nginx receives them
as build args, so without the flag nginx can silently be the stricter half.

From `.docker/` the equivalent is `docker compose --env-file ../.env up --build`.
Relative `context`/`env_file`/volume paths do resolve identically either way (compose
resolves them against the compose file's own location), and the project name is pinned
to `portfolio`, so container names are stable regardless of cwd.

Seven services come up: `api`, **`worker`** (background ingestion), `streamlit`,
`qdrant`, `postgres`, `redis`, `nginx`. Once healthy:

- API docs: `http://localhost:8000/docs` (or via nginx at `http://localhost/v1/...`)
- Streamlit demo: `http://localhost:8501`
- Qdrant dashboard: `http://localhost:6333/dashboard`

## Mint an API key first

Every `/v1` route requires one -- there is deliberately no master key in the
environment, since a key in env can be neither revoked nor rotated. `scripts/` is not
copied into the image, so this runs on the host against the published port 5432:

    uv sync --extra dev                                  # once
    uv run python scripts/create_tenant.py "My Org"      # prints the key ONCE

`--list` shows tenants and keys, `--revoke <key_id>` revokes one.

## Uploading a document (asynchronous)

`POST /v1/documents` returns **202** and queues the work; the `worker` service does the
parse/chunk/embed, which takes 10s-2min. The response carries no `chunk_count` --
nothing has been parsed yet when it is written.

    curl -X POST http://localhost:8000/v1/documents \
      -H "x-api-key: pf_live_..." -F "file=@paper.pdf"

    # poll until status is "ingested" (or "failed", which carries the reason)
    curl http://localhost:8000/v1/documents/<doc_id> -H "x-api-key: pf_live_..."

Statuses: `pending` (queued) -> `processing` (a worker has it) -> `ingested` or
`failed`. A retry moves `failed` back to `processing`, so status describes the latest
attempt rather than the worst one.

## Ingesting the corpus

This path **bypasses the queue entirely** -- `scripts/ingest.py` calls `ingest_document`
directly, so it works whether or not the worker is running and writes its registry rows
as `ingested` in one step.

    uv run python scripts/fetch_corpus.py    # download the pinned arXiv papers
    uv run python scripts/ingest.py          # parse, chunk, embed, store

This works against the containerized services because compose publishes their ports
(6333, 5432) to the host. Confirm the shell's config points at `localhost` rather than
the compose hostnames.

Then verify a real answer, which is the only thing that exercises the store layer (the
unit tests don't touch Qdrant):

    curl -X POST http://localhost:8000/v1/ask \
      -H "x-api-key: pf_live_..." -H "Content-Type: application/json" \
      -d '{"question": "What cathode materials show the highest cycling stability?"}'

The key is required -- without it this is a 401 -- and retrieval scope is derived from
it, so there is no request field to pass instead.

## Data services only (faster app-code iteration)

    cd portfolio
    docker compose -f .docker/docker-compose.yml --env-file .env up qdrant postgres redis -d
    uv sync --extra dev
    uv run uvicorn app.api.main:app --reload --port 8000
    uv run procrastinate --app=app.worker.tasks.app worker --queues ingest   # separate terminal
    uv run streamlit run streamlit_app/Home.py                               # separate terminal

`redis` is needed now (rate limiting), though its absence fails *open* rather than
loudly. The worker must run locally too, or uploads through the API stay `pending`
forever -- Streamlit is the exception, since it ingests in process.

The `--app` path is `app.worker.tasks.app`, **not** `app.worker.app.app`. Importing
`tasks` is what registers the task; `app/worker/app.py` deliberately holds no
`import_paths` so the api can enqueue without importing Docling. Point the worker at
`app.py` and it connects fine, then rejects every job as an unknown task.

Bare mode uses `app/config.py`'s local defaults (`db_host=localhost`,
`qdrant_url=http://localhost:6333`, `redis_host=localhost`) with no overrides needed --
compose only overrides those to service names for the containerized services.

## Troubleshooting

**Upload stuck at `pending` forever** -- the queue holds the job and nothing is
consuming it. In order:

    docker compose -f .docker/docker-compose.yml --env-file .env logs worker | tail -40
    docker compose -f .docker/docker-compose.yml --env-file .env exec postgres \
      psql -U portfolio -c "select id, task_name, status, attempts from procrastinate_jobs order by id desc limit 10;"

`status='todo'` with no matching worker log line means the worker isn't running or
isn't listening on the `ingest` queue. `task_name='ingest_document'` with the worker up
but rejecting it means `--app` points at `app.worker.app.app` (see above). No row at
all means the enqueue rolled back together with the document row -- look at the api
logs, not the worker's.

**Upload `failed`** -- the reason is in the response and in the row:

    select doc_id, status, error_message from documentrecord order by updated_at desc limit 5;

**`processing` with an old `updated_at`** -- a worker died mid-job. Nothing sweeps
these yet (a known gap); restart the worker and re-upload.

**Documents in Qdrant but no rows in `documentrecord`** -- this was a real bug, fixed in
Phase 5.1: `model_dump()` raised because `datetime` was a TYPE_CHECKING-only import in
`registry/models.py`, so every registry write failed *after* the Qdrant upsert had
committed. If it reappears, the symptom looks like a database problem and isn't.

**`port is already allocated`** -- a container from an earlier run is still holding it.
Find and clear it:

    docker ps -a --filter "publish=8000"
    lsof -i :8000                # or: ss -ltnp | grep :8000

To run two stacks side by side instead, set a different `PORT` in `.env`; it threads
through gunicorn, the compose mapping, and nginx's upstream automatically **provided
`--env-file` is passed** -- without it only the container's gunicorn moves.

**nginx crash-looping on `chown(...) failed`** -- its `cap_add` is missing `CHOWN`. See
`CLAUDE.md`'s failure contracts; the same applies to postgres with a different
capability set.

**postgres refusing to start with "there appears to be PostgreSQL data in:
/var/lib/postgresql/data (unused mount/volume)"** -- the mount path is wrong for the image
version, not the data. From postgres 18 the official images keep data in a
major-version-specific subdirectory, so the volume must be mounted at
`/var/lib/postgresql`, not `/var/lib/postgresql/data`. Fixed in `docker-compose.yml`; if it
reappears after an image bump, that's the first thing to check.

A pre-18 volume cannot be read by 18 without `pg_upgrade` (which needs both versions
installed), so the compose file uses a separate `postgres_data_v18` volume. The old one is
left on disk deliberately -- inspect it with a 17 image, or remove it with
`docker volume rm portfolio_postgres_data`. What's lost by starting fresh is the `tenants`
and `api_keys` rows, so re-mint a key. Note Qdrant points from earlier *uploads* are tagged
with the old tenant id and become unreachable to the new tenant; corpus documents are tagged
`global` and stay queryable.

**Credential changes to `POSTGRES_*` appear to do nothing** -- `initdb` only runs on an
empty volume. `docker compose down -v` first; note this now destroys the job queue as
well as the registry, since both live in Postgres.

**Permission errors writing `data/uploads` or `data/raw_pdfs`** -- the images run as
non-root `appuser` and a bind mount inherits host ownership. Either
`chmod -R o+rwX data` once on the host, or switch the volume to a named volume. The
`worker` mounts the same `../data`, so a file the api wrote has to be readable there
too.

**Streamlit logs flooded with `[transformers] Accessing __path__ ...`** -- harmless
deprecation noise from a transitive dependency of Docling's table model. It is not an
error, but it does bury real failures; scroll past it or grep the logs.
