---
name: run-stack
description: Bring up the portfolio Docker stack (api, streamlit, qdrant, postgres, redis, nginx) and ingest the document corpus. Use when asked to run, start, boot, restart, or verify the portfolio app end to end, when a service is crash-looping or a port is already allocated, or when ingestion needs to run against a live Qdrant/Postgres.
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
    docker compose -f .docker/docker-compose.yml up --build

Equivalently `cd .docker && docker compose up --build` -- compose resolves relative
paths against the compose file's own location, so both behave identically. The
project name is pinned to `portfolio` in the compose file, so container names are
stable regardless of which directory you invoke from.

Once healthy:

- API docs: `http://localhost:8000/docs` (or via nginx at `http://localhost/v1/...`)
- Streamlit demo: `http://localhost:8501`
- Qdrant dashboard: `http://localhost:6333/dashboard`

## Data services only (faster app-code iteration)

    cd portfolio
    docker compose -f .docker/docker-compose.yml up qdrant postgres -d
    uv sync --extra dev
    uv run uvicorn app.api.main:app --reload --port 8000
    uv run streamlit run streamlit_app/Home.py     # separate terminal

Bare mode uses `app/config.py`'s local defaults (`db_host=localhost`,
`qdrant_url=http://localhost:6333`) with no overrides needed -- compose only
overrides `DB_HOST` to the service name for the containerized services.

## Ingesting the corpus

`scripts/` is deliberately NOT copied into the image, so run these from the host,
not `docker compose exec`:

    uv run python scripts/fetch_corpus.py    # download the pinned arXiv papers
    uv run python scripts/ingest.py          # parse, chunk, embed, store

This works against the containerized services because compose publishes their
ports (6333, 5432) to the host. Confirm the shell's config points at `localhost`
rather than the compose hostnames.

Then verify a real answer, which is the only thing that exercises the store layer
(the unit tests don't):

    curl -X POST http://localhost:8000/v1/ask -H "Content-Type: application/json" \
      -d '{"question": "What cathode materials show the highest cycling stability?"}'

## Troubleshooting

**`port is already allocated`** -- a container from an earlier run is still holding
it. Find and clear it:

    docker ps -a --filter "publish=8000"
    lsof -i :8000                # or: ss -ltnp | grep :8000

To run two stacks side by side instead, set a different `PORT` in `.env`; it
threads through gunicorn, the compose mapping, and nginx's upstream automatically.

**nginx crash-looping on `chown(...) failed`** -- its `cap_add` is missing `CHOWN`.
See `CLAUDE.md`'s failure contracts; the same applies to postgres with a different
capability set.

**Credential changes to `POSTGRES_*` appear to do nothing** -- `initdb` only runs on
an empty volume. `docker compose down -v` first (this destroys the registry data).

**Permission errors writing `data/uploads` or `data/raw_pdfs`** -- the images run as
non-root `appuser` and a bind mount inherits host ownership. Either
`chmod -R o+rwX data` once on the host, or switch the volume to a named volume.

**Streamlit logs flooded with `[transformers] Accessing __path__ ...`** -- harmless
deprecation noise from a transitive dependency of Docling's table model. It is not
an error, but it does bury real failures; scroll past it or grep the logs.
