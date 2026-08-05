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
