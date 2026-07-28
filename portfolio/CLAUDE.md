# portfolio

RAG over scientific documents, plus an LLM eval framework and an agentic
human-in-the-loop curation layer.

Built: Epic 1 (retrieve -> rerank -> generate, multi-format uploads, Docker stack) and
Epic 4 Phase 1 (API-key auth, tenant scoping) -- see `EPIC_4_PLAN.md` for the remaining
phases. Not built: Epics 2 and 3, designed in `README.md` only -- no eval framework, no
agent, no rate limiting. Don't assume code for them.

## Verification gate

All four before pushing. `ty.toml` sets `error-on-warning`, so a warning fails:

    uv run ruff check . && uv run ruff format --check .
    uv run ty check
    uv run pytest tests/unit
    cd .docker && docker compose config    # after any compose/Dockerfile edit

A live Qdrant/Postgres round-trip is NOT covered by any of these. The auth tests do hit
a real Postgres when one is reachable and skip otherwise, but nothing exercises Qdrant,
so bugs in the store layer only surface on a real ingest. Say that plainly rather than
implying green tests mean the pipeline works.

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
- `uv.lock` is gitignored here (unusual for a uv project). Don't add it.

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
- **`SQLModel` datetime fields need an explicit `sa_column`** in any module using
  `from __future__ import annotations` with `datetime` imported under `TYPE_CHECKING`.
  Without it SQLModel infers the column type from an annotation that is a string it can't
  resolve, failing at *import* time with `issubclass() arg 1 must be a class` -- which
  reads like a library bug rather than a missing argument. Use
  `Column(DateTime(timezone=True))`, which also keeps values aware -- see the next entry.
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

## Config invariants

- **`PORT` is the single source of truth** for the api port: gunicorn's `--bind`,
  the compose port mapping, and nginx's upstream (baked in at nginx build time by
  `sed` on the `__API_PORT__` placeholder). Deliberately not nginx's `envsubst`
  templates -- those substitute every `$`-token and would wipe nginx's own
  `$scheme`/`$remote_addr` too.
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
