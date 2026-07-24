# portfolio

RAG over scientific documents, plus an LLM eval framework and an agentic
human-in-the-loop curation layer. Epic 1 (the retrieve -> rerank -> generate
pipeline, multi-format session-scoped uploads, Docker stack) is built and
verified. Epics 2-4 are designed in `README.md` but **not implemented** -- no eval
framework, no agent, no API auth exists yet. Don't assume code for them.

## Verification gate

All four before pushing. `ty.toml` sets `error-on-warning`, so a warning fails:

    uv run ruff check . && uv run ruff format --check .
    uv run ty check
    uv run pytest tests/unit
    cd .docker && docker compose config    # after any compose/Dockerfile edit

A live Qdrant/Postgres round-trip is NOT covered by any of these -- the unit
tests are pure. Bugs in the store layer only surface on a real ingest, so say so
plainly rather than implying green tests mean the pipeline works.

## Never

- **Never commit `.env`.** It holds a real LangSmith API key. `.env.example` stays a
  template with placeholders only -- no real secrets, ever.
- **Never regenerate `_POINT_ID_NAMESPACE`** in `app/vectorstore/qdrant_store.py`.
  Point IDs are `uuid5(namespace, chunk_id)`; a new namespace changes every ID, so
  re-ingesting unchanged documents silently duplicates instead of upserting.
- `uv.lock` is gitignored here (unusual for a uv project). Don't add it.

## Failure contracts

Things that look correct and aren't:

- **Qdrant point IDs must be an unsigned integer or a UUID.** Chroma accepted
  arbitrary strings; Qdrant rejects a `chunk_id` with a 400. Hence the uuid5
  derivation above. `chunk_id` itself stays in the payload metadata -- citations
  read it from there, never from the point ID.
- **Qdrant filters must be real `qdrant_client.models.Filter` objects.** The
  Mongo-style dict shorthand (`$in`/`$and`) only ever existed on the deprecated
  `Qdrant` class. Getting this wrong doesn't error -- it silently breaks session
  scoping, leaking one session's uploads into another's results.
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

## Config invariants

- **`PORT` is the single source of truth** for the api port: gunicorn's `--bind`,
  the compose port mapping, and nginx's upstream (baked in at nginx build time by
  `sed` on the `__API_PORT__` placeholder). Deliberately not nginx's `envsubst`
  templates -- those substitute every `$`-token and would wipe nginx's own
  `$scheme`/`$remote_addr` too.
- **`POSTGRES_USER`/`PASSWORD`/`DB` is one set serving two consumers**: the postgres
  image, and `app/config.py`'s `Settings`, which assembles `DATABASE_URL` from them.
  Don't reintroduce a parallel `DB_USER`/`DB_PASSWORD`/`DB_NAME`.
- **`requires-python` says `>=3.12` deliberately**, even though `ruff.toml`/`ty.toml`
  target py314 and the Dockerfile pins `python:3.14-slim`. Tightening it to `>=3.14`
  makes uv resolve against a 3.14 RC that breaks pydantic's typing internals. Leave it.
