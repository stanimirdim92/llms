# Changelog

What someone using this system would notice changed, and what would break on upgrade.

Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). **Nothing has been released
yet** — `pyproject.toml` says `0.0.1`, there are no tags, and no artefact is published — so
everything lives under `[Unreleased]`, grouped by date. When a version is cut, the relevant
dated block becomes `## [0.1.0] - <date>`.

Reasoning, measurements and what we got wrong are deliberately *not* here; they are in
`docs/MEMORY.md`'s session log and `docs/TECHNICAL_DECISIONS.md`. See
`.claude/skills/changelog/SKILL.md` for where the line falls.

## [Unreleased]

### 2026-08-07

#### Added

- **Two new indexes speed up the per-tenant document list and the `/ask` retrieval-scope
  lookup for tenants with many documents.** No effect on behavior or response shape — same
  results, faster once a tenant's document count grows past the low tens. Measured on a 20,000-
  document tenant: the document list is ~11–15× faster, the `/ask`-path lookup ~1.5–2.8×
  (bounded lower because that query returns every active document regardless of indexing — see
  `docs/TECHNICAL_DECISIONS.md` § Database for why). No change for typical, small tenants.

  *Upgrading:* nothing to do — the migration runs automatically at boot, same as every other
  schema change. It briefly blocks writes to the document-registry table while it builds
  (`CREATE INDEX`, not the non-blocking `CONCURRENTLY` form — see the same section for why); on
  an empty or lightly-loaded table this is not noticeable, but a deployment with real write
  traffic should account for a brief pause during the upgrade.

- **Row-level security on document rows, enforced by Postgres itself.** A new database role
  (`APP_DB_USER`/`APP_DB_PASSWORD`, default `portfolio_app`) now handles every request-time query;
  `POSTGRES_USER` is reserved for schema migrations. This is a second, independent layer on top of
  the existing per-request tenant filter — not a replacement for it — so a query that somehow
  missed its own tenant check still cannot return another tenant's document.

  *Upgrading:* nothing to do for a fresh install — `.env.example` already has working defaults for
  the new variables, and the migration that creates the role runs automatically at boot, same as
  every other schema change. An **existing** deployment that customizes `.env` should add
  `APP_DB_USER`/`APP_DB_PASSWORD` explicitly rather than relying on the default password. The api
  and worker containers need no other changes; `docker-compose.yml`'s `env_file:` already forwards
  every `.env` variable to them.

#### Changed

- **`GET /health/ready`'s Postgres check now runs as the same role real traffic uses**
  (`APP_DB_USER`), not the migration role. A connection failure specific to that role — a wrong
  password, a revoked grant — now shows up in readiness instead of only surfacing on the first real
  request.

### 2026-08-06

#### Changed

- **`GUNICORN_TIMEOUT`'s default is now 120s** (2 minutes), to give large PDF ingestion more
  headroom before gunicorn SIGKILLs the worker mid-parse. It moved twice the same day — 600s to
  100s and then to 120s — and nginx's `proxy_read_timeout`/`client_body_timeout` move with it, as
  always.

  *Upgrading:* if you set `GUNICORN_TIMEOUT` explicitly in `.env`, this doesn't affect you. If you
  were relying on the previous 600s default, set it explicitly.

- **A new `GUNICORN_GRACEFUL_TIMEOUT` env var** (default 630s) bounds how long a worker gets to
  finish in-flight requests after a restart/reload signal before gunicorn force-kills it — a
  different budget from `GUNICORN_TIMEOUT`, which bounds one request. Not yet exposed in
  `.env.example`; see `docs/TECHNICAL_DECISIONS.md` § Deployment for what its default does and
  does not have behind it.

#### Fixed

- **Uploading through the Streamlit UI failed on every document.** The upload wrote its chunks to
  Qdrant and then aborted with `DocumentNotFoundError: no document row for ...`, leaving the document
  absent from `My documents` and its points unreachable. The row the UI staged was never committed,
  so the step that publishes it had nothing to update. Uploads through `POST /v1/documents` were
  never affected.

  *Upgrading:* re-upload anything that failed this way. Points from a failed attempt are invisible to
  search (they belong to a generation that was never published) but still occupy Qdrant; the
  quickest way to reclaim them on a small install is to drop the Qdrant collection and re-upload.

- **A Postgres volume with no application database no longer reports the stack as ready.** The
  `postgres` healthcheck used `pg_isready`, which answers for the server and ignores the database
  name it is given — so compose called Postgres healthy, started `api` and `worker` on that signal,
  and both crash-looped with `FATAL: database "portfolio" does not exist`, which reads as an
  application bug. The container now reports **unhealthy** and its health log carries the actual
  `FATAL`, so dependent services never start.

  *Upgrading:* nothing to do. If Postgres now reports unhealthy where it previously reported
  healthy, the database really was missing — the volume's `initdb` ran before `POSTGRES_DB` had its
  current value, or the database was dropped by hand. Neither is recoverable by restarting, because
  the entrypoint initialises only an empty data directory: `docker compose down -v` and start again,
  which recreates the database and re-runs the migrations. Note this destroys tenants, API keys and
  the job queue, so re-mint a key afterwards.

- **A re-ingest that fails partway no longer empties a working document.** Re-uploading a document
  used to delete its existing chunks before writing the new ones, so a failure in between left the
  document reporting `ingested` with nothing to search: a question scoped to it returned an answer
  grounded in nothing, and an unscoped question was answered from your *other* documents with no
  indication. Each ingest now writes a new generation alongside the existing one and becomes visible
  only when it completes; until then the previous version keeps answering. A failed re-ingest is
  visible as `failed` on `GET /v1/documents/{doc_id}` while the document stays searchable.
- **A figure could be shown with the wrong caption after a re-ingest.** Figure images were stored at
  a path derived from the figure's position in the document, so a re-ingest that changed the figure
  order overwrote the image while the previous version's caption still pointed at it. The Streamlit
  answer view then rendered the new picture under the old caption. Image files now carry a digest of
  their own pixels.

  *Upgrading:* no action, and no data is lost. Images written before this change are simply no longer
  referenced; a re-upload writes the new-style filenames. Disk under `data/processed/<doc_id>/figures`
  is not reclaimed automatically — deleting that directory is safe and costs one re-parse.

### 2026-08-05

#### Security

- **A document that failed to ingest can no longer influence an answer.** Chunks reach Qdrant just
  before the registry row is written, so a crash between the two left a document searchable while
  `GET /v1/documents/{doc_id}` reported `processing` or `failed`. `POST /v1/ask` now searches only
  documents the registry says are `ingested`. Two visible consequences: a tenant whose documents are
  all still ingesting gets an answer grounded in nothing rather than a partial one, and naming a
  document that has since failed answers from nothing rather than silently falling back to your
  other documents.
- **Two documents with the same filename could overwrite each other's content.** Uploading
  `report.pdf`, then a *different* `report.pdf` before the first finished ingesting, could file the
  second document's content under the first one's `doc_id` — so a question about the first document
  was answered from the second, with citations pointing at the first. Nothing reported an error, and
  the stored content hash was rewritten to match the wrong content, so the swap left no trace.
  Uploads are now stored under an immutable per-document path and the worker refuses to ingest bytes
  whose digest does not match what was accepted.

  *Upgrading:* nothing to do, and no data is lost — jobs already queued carry their original path
  and still complete. Files uploaded before this change stay where they were and are simply no
  longer read; re-upload anything whose content you doubt. **If you have ever uploaded two different
  documents with the same filename, check them**: `GET /v1/documents` shows each `doc_id` with its
  filename, and asking a question scoped to one is the quickest way to see whose content it holds.

#### Changed

- **Schema changes no longer require dropping the database.** Tables are managed by Alembic
  migrations, applied automatically when the api or worker starts, instead of a create-if-missing
  step that could add a table but never a column. Nothing to do on upgrade: an existing database is
  detected and adopted at the initial revision, and **your tenants, API keys and document records are
  left untouched**. Previously the documented way to change the schema was to delete the volume,
  which destroyed all three.

#### Added

- **A second rate limit, at nginx, keyed on your IP address rather than your API key.** It sheds
  volume before a request reaches the app, so an unauthenticated flood no longer costs a worker and
  a database lookup per request. It answers **`429`**, the same status as the app's own limiter, and
  the budgets are set an order of magnitude above the per-key ones — roughly 1200 requests/minute
  from one address, and 30 uploads/minute — so ordinary use from behind a shared address is
  unaffected. **`GET /health/live` and `GET /health/ready` are exempt.**

  Two things to know if you hit it. This limiter sends **no `X-RateLimit-*` headers and no
  `Retry-After`** — those come from the app, and a request shed at the edge never reaches it, so a
  `429` with no headers means the edge and a `429` with headers means your key's budget. And the
  four settings (`EDGE_RATE_GENERAL`, `EDGE_BURST_GENERAL`, `EDGE_RATE_UPLOAD`, `EDGE_BURST_UPLOAD`)
  are **build arguments baked into the nginx image**, not runtime environment variables, so changing
  one needs `docker compose build nginx` rather than a restart.

  *Deploying behind a load balancer or CDN:* every request would share one bucket, because nginx
  sees only the immediate peer. `.docker/nginx/nginx.conf` carries a commented `set_real_ip_from`
  block and the warning that comes with it — a too-broad trust range lets a client spoof
  `X-Forwarded-For` and evade the limit entirely.

### 2026-08-04

#### Removed

- **Breaking: the shared `global` corpus is gone.** Every document now belongs to the tenant
  that uploaded it, so a fresh install has **nothing to search** until something is uploaded —
  `POST /v1/ask` on an empty tenant answers from nothing rather than from six curated papers.
  *Upgrading:* Qdrant points tagged `global` are orphaned — they match no live tenant filter
  and have no registry row, so nothing will read or delete them. Drop the Qdrant volume and
  re-upload.
- **Breaking: `scripts/fetch_corpus.py` and `scripts/ingest.py` are deleted**, along with
  `data/manifest.json`. There is no seed-data path; use `POST /v1/documents`.
- **Breaking: `MANIFEST_PATH` and `RAW_PDF_DIR` are no longer settings.** Nothing reads them.
  Remove them from `.env` — they are ignored rather than rejected, since `Settings` is
  configured `extra="ignore"`.

#### Changed

- **`POST /v1/ask` searches only your own documents.** Previously it searched your uploads
  *plus* the shared corpus. The OpenAPI summary and description now say so.
- **`GET /v1/documents` is unchanged in shape** but its description no longer mentions
  excluding a shared corpus, because there is nothing to exclude.
- **`scoped_to` on an `/ask` response** means "every document this tenant has uploaded was
  searched" when empty, rather than "the whole corpus plus your uploads".
- **A tenant-filtered search is served by sequential reads** at scale: Qdrant now carries a
  keyword payload index on the tenant field with `is_tenant=true`, plus one on `doc_id`. Both
  are created automatically on first connection; no action needed on an existing collection.

### 2026-08-03

#### Fixed

- **`Retry-After` on a 429 is now safe to obey literally.** Waiting the advertised number of
  seconds returns your full budget. Briefly — within this day's commits — a sliding-window
  *counter* advertised the same value while granting only a fraction of the budget to a client
  that had waited exactly that long.
- **`X-RateLimit-Reset` is never `0` while a request is counted against the window.** The first
  request against a fresh window previously reported `0` ("retry now") while holding a spent
  budget, which pushes a well-behaved client into a tight retry loop.
- **The Docker stack starts reliably on a fresh volume.** Concurrent container creation raced
  the model-cache volume initialisation and failed the whole stack with
  `failed to mkdir .../_data/torch: file exists`.

#### Changed

- **Rate limiting is backed by [`limits`](https://limits.readthedocs.io/)** rather than a
  hand-rolled Lua script. Behaviour a caller can observe is unchanged, with one exception worth
  knowing: **`X-RateLimit-Remaining` is now a close estimate rather than a reservation.** It is
  read just after your request is counted, so under concurrent traffic on the same key it can
  differ by a request or two from what the next call is granted. `X-RateLimit-Limit` stays
  exact, and `Retry-After` still errs long.
- **New setting `REDIS_MAX_CONNECTIONS`** (default `512`), per process. The library's own
  default of 100 raises `MaxConnectionsError` rather than queueing, which surfaces as 500s
  under burst load.

### 2026-08-02

#### Added

- **`truncated` on the `/ask` response.** `true` when the answer hit the generation token
  ceiling, so a clipped answer is detectable instead of silently looking complete. The
  Streamlit page shows a warning when it is set.
- **`X-RateLimit-Limit`, `-Remaining` and `-Reset` on every response**, not just on 429s, so a
  budget is discoverable without exhausting it. `X-RateLimit-Reset` is **seconds remaining**,
  not an epoch timestamp. When Redis is unreachable the headers are **absent** rather than
  optimistic — the limit is not being enforced at that moment, and reporting a full budget
  would claim otherwise.
- **Document scoping on `/ask` from the question text.** Naming one of your own documents — by
  filename with its extension, or by `doc_id` bare or behind a `doc_id=` marker — restricts the
  search to it, and `scoped_to` in the response says which. No new request parameter.

#### Changed

- **Naming a document you do not own returns `404`**, rather than silently searching
  everything. Naming one of yours that is still ingesting, or that failed, returns `409` —
  answering from a document with no chunks yet would be a confident claim about something
  nothing searched.
- **Rate-limit buckets are per API key**, not per tenant, so one key cannot exhaust another's
  budget. A tenant holding N keys therefore has N times the budget: this is a fairness device
  between clients, not a cost ceiling.
- **`GET /v1/documents` and `GET /v1/documents/{doc_id}` carry their own rate-limit budget**
  (`RATE_LIMIT_DOCUMENTS`, default 120/min) instead of sharing the `/ask` budget. Polling a
  status route while a document ingests no longer spends question budget.

#### Security

- **A document belonging to another tenant returns `404`, never `403`.** Distinguishing "not
  yours" from "does not exist" would confirm that a given file had been uploaded by somebody.
- **`POST /v1/ask` rejects an unexpected `session_id` (or any extra field) with `422`.** An
  earlier version accepted a client-supplied scope, which let any caller read another tenant's
  documents by passing their id. A stale client is now told plainly rather than silently
  receiving results scoped to somebody else.

### Earlier — 2026-07-13 to 2026-08-01

The system was built in this window; a per-change record before the first review would be
reconstruction rather than history. What a user can rely on as of the dates above:

#### Added

- **`POST /v1/ask`** — retrieve, rerank, and generate an answer whose citations are extracted
  spans of the source rather than model-written quotes, so a citation cannot be fabricated.
- **`POST /v1/documents`** — multi-format upload (PDF, DOCX, PPTX, XLSX, HTML, MD, CSV, images
  and more), returning **`202`** with a `doc_id`; a worker ingests off the request path.
  `GET /v1/documents` and `GET /v1/documents/{doc_id}` report `pending` → `processing` →
  `ingested` / `failed`, with `chunk_count` and `error_message`.
- **API-key authentication** via the `x-api-key` header, declared as an OpenAPI security
  scheme. Keys are hashed at rest, shown once, individually revocable, carry per-key scopes
  (`ask`, `documents:read`, `documents:write`, `keys:read`, `keys:write`) and default to a
  30-day expiry. Full CRUD at `/v1/keys`, plus a Streamlit page.
- **`GET /health/live` and `GET /health/ready`** — liveness is static; readiness probes
  Postgres, Qdrant and Redis and returns `503` when a required one is down. Redis is reported
  but not required, because rate limiting fails open.
- **A Docker Compose stack** — api, worker, Streamlit, Qdrant, Postgres, Redis, nginx.

#### Changed

- **Qdrant replaced Chroma** as the vector store, as a real service rather than an embedded
  library.
- **Ingestion moved behind a Postgres-backed job queue.** `POST /v1/documents` returns `202`
  where it previously blocked for the length of the parse.

#### Security

- **Retrieval scope is derived entirely from the authenticated key.** There is no request field
  that can influence which tenant's documents are searched.
