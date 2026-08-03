# portfolio

Retrieval-augmented question answering over scientific documents — PDFs and Office
formats in, cited answers out — with per-tenant isolation, API-key auth, and rate
limiting, running as a Docker stack.

The distinguishing pieces are in how documents are handled, not in the RAG loop itself:
tables are chunked whole so they never split mid-row, figures become their own chunk type
with a vision-model caption as their embedded text, and prose keeps its section path.
Retrieval reranks before generating, and answers are produced through Anthropic's
Citations API, so every claim carries the chunk and page it came from rather than a
model-authored footnote.

Of four planned epics, Epic 1 is built, as are Epic 4's phases 1–3 and the async-ingestion
half of phase 5; the eval framework (Epic 2) and the agentic curation layer (Epic 3) are
designs with no code behind them. [Status](#status) is precise about the boundary, including
the gaps in what *is* built.

## Quickstart

Requires Docker and an [Anthropic](https://console.anthropic.com/) plus
[Voyage AI](https://voyageai.com/) API key.

```bash
cd portfolio
cp .env.example .env      # then fill in ANTHROPIC_API_KEY and VOYAGE_API_KEY
docker compose -f .docker/docker-compose.yml --env-file .env up --build
```

`--env-file` is required, not stylistic. Compose resolves `${VAR}` from a `.env` in the
*project* directory (`.docker/`), so without it `PORT`, `GUNICORN_TIMEOUT`, and
`MAX_UPLOAD_SIZE_MB` from your `.env` reach the app container but **not** the port mappings
or the nginx build — and the mismatch doesn't raise anything.

That brings up seven services: `api` (gunicorn + uvicorn workers), `worker` (background
ingestion), `streamlit`, `qdrant`, `postgres`, `redis`, and `nginx` in front of the api. The
API is on `http://localhost:8000` directly or `http://localhost/` through nginx; Streamlit is
on `http://localhost:8501`, not proxied.

Every request needs an API key. There is no master key in the environment on purpose — a
key in env couldn't be revoked or rotated — so mint one:

```bash
uv sync --extra dev                                  # once; scripts/ isn't in the image
uv run python scripts/create_tenant.py "My Org"      # prints the key once
```

`scripts/` is deliberately not copied into the container, so this runs on the host and
talks to the compose Postgres over its published `5432`. `--list` shows tenants and keys with
their state, `--tenant <id> --revoke <key_id>` revokes one, and `--expires-in` takes
`30`/`60`/`90`/`365`/`never`, defaulting to **30 days**. A forever-key is a legitimate choice
but not one to make by omission, so it has to be asked for by name. Revocation needs both
identifiers: key ids are opaque and adjacent in a listing, and revoking the wrong one locks
out a tenant irreversibly, so two identifiers that must agree turn a mistyped id into an
error rather than an outage.

Keys minted this way are **unrestricted** — every scope. That is right for the bootstrap key
and wrong for everything after it; narrower keys come from the API below.

Then upload a document and ask about it:

```bash
# Returns 202 immediately -- ingestion runs in the worker (10s-2min depending on the document)
curl -X POST http://localhost:8000/v1/documents \
  -H "x-api-key: pf_live_..." -F "file=@paper.pdf"

# Poll until status is "ingested" (or "failed", with error_message saying why)
curl http://localhost:8000/v1/documents/<doc_id> -H "x-api-key: pf_live_..."

# Everything this tenant owns, newest first. Ask /ask "what documents do I have?" and you get
# an answer grounded in whatever text is nearest in embedding space -- this is the real answer.
curl http://localhost:8000/v1/documents -H "x-api-key: pf_live_..."

curl -X POST http://localhost:8000/v1/ask \
  -H "x-api-key: pf_live_..." -H "content-type: application/json" \
  -d '{"question": "What electrolyte did they use?"}'

# Naming a document you own restricts the search to it. No extra parameter: the identifier
# in the question text is what does it, and `scoped_to` in the response says which documents
# it narrowed to. An unowned name is a 404, not a silent search of everything.
curl -X POST http://localhost:8000/v1/ask \
  -H "x-api-key: pf_live_..." -H "content-type: application/json" \
  -d '{"question": "summarise paper.pdf"}'

# ...or by doc_id, bare or behind a `doc_id=` marker. The marker is the only form that works
# for the shared corpus, whose ids are bare arXiv numbers a regex cannot tell from a decimal.
curl -X POST http://localhost:8000/v1/ask \
  -H "x-api-key: pf_live_..." -H "content-type: application/json" \
  -d '{"question": "extract the contact details from doc_id=019fb3eb...-64a6d182..."}'
```

Keys manage themselves from there, so rotating a credential doesn't need a shell on the
database host:

```bash
# Mint a narrower key. Expires in 30 days unless you say otherwise (30/60/90/365, or null
# for never), and you can only grant scopes your own key already holds -- more is a 403.
curl -X POST http://localhost:8000/v1/keys \
  -H "x-api-key: pf_live_..." -H "content-type: application/json" \
  -d '{"name": "ci", "scopes": ["documents:write"], "expires_in_days": 90}'

# Omitting `scopes`, sending `[]`, and sending `null` all mean "the same scopes I hold" --
# generated clients serialise unset optionals as null, so all three have to agree.

curl http://localhost:8000/v1/keys -H "x-api-key: pf_live_..."          # metadata, never keys
curl -X DELETE http://localhost:8000/v1/keys/<key_id> -H "x-api-key: pf_live_..."
```

Every rate-limited response carries `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and
`X-RateLimit-Reset` — on success as well as on a 429, so a client learns its budget without
having to exhaust it. **`X-RateLimit-Reset` is seconds-until-reset, not an epoch timestamp**
(GitHub's is epoch; a delta needs no agreement between your clock and ours). A 429 adds
`Retry-After`. Buckets are per key, so the numbers describe the key you authenticated with. If
Redis is down the headers are **absent** rather than optimistic — the limit is not being
enforced at all at that point, and saying `remaining: 60` would claim otherwise.

The scopes are `ask`, `documents:read`, `documents:write`, `keys:read`, `keys:write`. A key
with an empty stored list holds **all** of them — that is what keys minted before scopes
existed have, and reading it as "no permissions" would have revoked every one of them.
Missing a scope is a **403** naming what is missing; touching another tenant's key is a 404,
because "not yours" and "doesn't exist" must not be distinguishable.

The answer comes back with `citations` (quoted text plus `chunk_id`/`doc_id`/`page_no`)
and every chunk that survived reranking, so a wrong answer can be traced to whether
retrieval or generation caused it.

It also carries **`truncated`**. True means the model hit its token ceiling rather than
finishing: the text stops mid-sentence and `citations` is short, because citation blocks arrive
as the text is generated. A client must not present that as a complete answer — ask something
narrower rather than retrying the same question. Every answer logs `stop_reason` and its token
counts, so the truncation *rate* is visible in the logs rather than only per request.

`/docs` has the full OpenAPI schema. The Streamlit app at `:8501` does the same two
operations through a UI, authenticating with the same key.

To load the curated corpus (6 arXiv materials-science papers, pinned in
`data/manifest.json`) instead of your own uploads — also from the host, against the
compose Qdrant and Postgres on their published ports:

```bash
uv run python scripts/fetch_corpus.py    # downloads the pinned PDFs
uv run python scripts/ingest.py          # parse -> chunk -> embed -> Qdrant + Postgres
```

Corpus documents are tagged `tenant_id="global"` and are readable by every tenant;
uploads are readable only by the tenant whose key uploaded them.

### Running without Docker

Needs a reachable Qdrant, Postgres, and Redis (`QDRANT_URL`, `DB_HOST`/`DB_PORT`,
`REDIS_HOST`/`REDIS_PORT` in `.env` — the defaults assume all three on localhost).
Python 3.13 is the floor, though Docker and CI run 3.14. Nothing requires 3.14 since
`app/ids.py` took over `uuid7` with an RFC 9562 fallback. `.python-version` pins the local
venv at 3.13, because pydantic fails to build models on a 3.14 *pre-release*.

```bash
uv sync --extra dev
uv run uvicorn app.api.main:app --reload
uv run streamlit run streamlit_app/Home.py
```

## Architecture

```
POST /v1/documents ──> write file + row + job  ──> 202 Accepted
   (api)                (ONE transaction)              │
                                                       │  Postgres queue
   (worker) ─────────────────────────────────────────> ▼
            parse ──> figures ──> chunk ──> embed ──> Qdrant (vectors + payload)
            Docling   Claude      3 kinds   Voyage └─> Postgres (status: ingested)
                      vision

ask ──> embed ──> Qdrant search ──> rerank ──> generate ──> cited answer
        Voyage    (tenant-filtered)  Voyage     Claude +
                                     or local   Citations API
```

Ingestion takes 10s–2min, so it runs in a **worker** rather than in the request.
`POST /v1/documents` returns 202 and `GET /v1/documents/{doc_id}` reports
`pending`/`processing`/`ingested`/`failed` — a failure carries the reason, so a client can
tell a broken document from one that was never uploaded. `GET /v1/documents` lists the
tenant's own documents; a document that produced no searchable text is `failed` there rather
than reported as a zero-chunk success.

The queue is Postgres (`procrastinate`), not Redis, for one specific reason: the document row
and its job commit in **one transaction**. With a separate broker there's a window where the
row exists and the job doesn't — a document stuck in `pending` forever, indistinguishable from
one still legitimately queued — and nothing raises when it happens.

Inside the worker, the offloading still matters: Docling's parse and Qdrant's sync `upsert` go
through `asyncio.to_thread` because both would otherwise stall the event loop, and figure
captions go out as one batched vision call set with bounded concurrency. The api, meanwhile,
deliberately never imports Docling at all — it only enqueues.

The answer path is deliberately **not** agentic — it is a fixed retrieve → rerank →
generate sequence with no branching. Adaptive judgment is Epic 3's job; adding it here
would buy nondeterminism for nothing.

**Tenant isolation** is the one property worth stating precisely: `tenant_id` is the only
thing scoping retrieval, and a wrong filter returns results rather than raising — it fails
silently, as cross-tenant data access. It is derived solely from the verified API key
(`app/api/deps.py::current_tenant`), never from a request body, query string, or form
field; `AskRequest` sets `extra="forbid"` so a client trying to smuggle one gets a 422
rather than being quietly ignored. An earlier version accepted a client-supplied
`session_id`, which let any caller read another tenant's documents by passing their id.

| Layer | Choice |
|---|---|
| Extraction | Docling, used directly (not via `DoclingLoader`) — needs per-table/per-figure objects |
| Chunking | Docling `HybridChunker` for prose; tables serialized whole; figures as captioned chunks |
| Embeddings | Voyage `voyage-4` |
| Vector store | Qdrant (real server, `langchain_qdrant.QdrantVectorStore`) |
| Reranker | Voyage `rerank-2.5`, with a local `bge-reranker-v2-m3` cross-encoder as a no-API-key fallback |
| Generation | `ChatAnthropic` (Claude Sonnet 5) + Anthropic's native Citations API |
| Document registry | Postgres + SQLModel, one row per document, with ingestion status |
| Job queue | `procrastinate` on the same Postgres — transactional enqueue |
| Auth | `x-api-key` → `tenant`/`apikey` tables, SHA-512 hashed, individually revocable, 30-day default expiry, per-key scopes; declared as an OpenAPI security scheme |
| Rate limiting | Per-**key** sliding window, one Lua script on `redis.asyncio`, `X-RateLimit-*` on every response |
| Serving | gunicorn + `UvicornWorker`, `--preload`, behind nginx |
| Health | `/health/live` static; `/health/ready` probes Postgres/Qdrant/Redis, 503 on a required outage |
| Tracing | LangSmith (zero-code — every call is already a LangChain object) |
| Lint/type/test | ruff, `ty`, pytest; CI on every PR touching `portfolio/**` |

Every row above has a reason, several of them counterintuitive (why Qdrant point IDs
can't be chunk ids, why re-ingestion deletes before inserting, why a plain digest rather than
argon2, why the limiter fails open). Those are in
[`docs/TECHNICAL_DECISIONS.md`](docs/TECHNICAL_DECISIONS.md), with the alternatives that were
rejected and what it would take to revisit each one.
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) covers the agentic-architecture survey behind
Epic 3's design.

## Status

**Built:**

- **Epic 1 — RAG foundation.** Multi-format ingestion (PDF, DOCX, PPTX, HTML, MD, XLSX,
  CSV, images), structure-aware chunking, Voyage embeddings + reranking, cited answers,
  `POST /v1/documents` and `POST /v1/ask`, a Streamlit UI, the Postgres document
  registry, and the full Docker stack.
- **Epic 4 Phase 1 — API-key auth and tenant scoping.** Database-backed keys modelled on
  the Anthropic Console: shown once, hashed at rest, revocable individually. Tenant
  identity derived from the key.
- **Epic 4 Phase 2 — Per-tenant rate limiting.** Sliding window in Redis, atomic via Lua,
  separate budgets per scope so exhausting uploads doesn't block questions, failing open
  when Redis is down.
- **Epic 4 Phase 5.1 — Async ingestion.** `POST /v1/documents` returns 202 and a
  `procrastinate` worker does the work, with the document row and its job committed in one
  transaction. Status polling via `GET /v1/documents/{doc_id}`, including a reason on
  failure.
- **Explicit document scoping on `/ask`** (pulled forward out of Epic 2, because it fixed an
  observed defect rather than moving a metric). Naming a document you own in the question — by
  filename or by `doc_id` — narrows retrieval to it via a `doc_id` filter resolved from your
  registry rows; naming one you don't own is a 404. No model call — see
  `app/retrieval/document_scope.py` for why, and `docs/EPIC_2_PLAN.md` for what is deliberately
  left out (semantic reference: "the flyer").

**Not built.** These exist as designs only — there is no code for any of them, so don't
infer any from a plan's directory layout. The buildable plans are
[`docs/EPIC_2_PLAN.md`](docs/EPIC_2_PLAN.md) and [`docs/EPIC_3_PLAN.md`](docs/EPIC_3_PLAN.md);
[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) holds the original design and
is deliberately not kept current:

- **Epic 2 — Eval framework.** RAGAS metrics as LangSmith custom evaluators over a
  versioned dataset, with a CI threshold gate and a deliberate pre-reranker baseline to
  compare against. Explicit document scoping is the one piece already shipped (above); the
  intent router, golden set, and gate are not.
- **Epic 3 — Knowledge-curation agent with HITL.** Playwright scraping, an
  orchestrator plus Curator/Evaluator subagents over the same Qdrant collection,
  prompt-injection defense on scraped content, and LangGraph `interrupt()` for human
  review.
- **Epic 4 Phase 4** — observability: the latency SLO check is buildable, faithfulness
  alerting needs Epic 2's scores.
- **Epic 4 Phase 5** — the application backend. **5.1 (ingestion behind a job queue) is
  built**; still to come: user accounts, conversations with persisted citations, document
  list/delete, semantic search, streaming `/ask`, and shareable conversation snapshots.
- **Epic 4 Phase 6** — a React + TypeScript UI on top of Phase 5, with a typed client
  generated from the OpenAPI schema. Streamlit retires when this ships.

Phase-by-phase detail, including the rejected alternatives for the queue and the
identity decision, is in [`docs/EPIC_4_PLAN.md`](docs/EPIC_4_PLAN.md).

**Known gaps in what *is* built**, stated rather than left to be discovered:

- The corpus is 6 papers, not the ~45 the plan called for, and Epic 1's final
  15-question prose/table/figure spot-check has not been run.
- **Qdrant's real network path is untested.** Its *filtering* now is — tenant isolation and
  the delete-then-insert contract run through `qdrant_client`'s in-memory engine in CI — but
  the live client over the wire isn't, and that's where the point-ID constraint escaped to
  production. It's also how a registry-write bug survived until phase 5.1 added the first test
  over that path: every ingest wrote to Qdrant and then crashed before the Postgres row, and
  the symptom read as a database problem.
- The nginx config's *syntax* is unvalidated (no nginx binary in the development sandbox) —
  only its build-time placeholder substitution is checked, by the build failing on any
  unsubstituted `__PLACEHOLDER__`.
- Uploads are read fully into memory before the size check, so `MAX_UPLOAD_SIZE_MB`
  bounds what is *stored*, not what is buffered. Streaming to disk is tracked as
  `docs/EPIC_4_PLAN.md` 1.6.
- **A stuck job is detectable but not handled.** `updated_at` makes a worker that died
  mid-`processing` visible, and nothing yet sweeps or re-enqueues those.
- nginx is HTTP-only. There is no domain yet to provision certificates against; the TLS
  scaffolding is in place and `conf.d/default.conf` documents the remaining steps.

## Layout

```
portfolio/
├── app/
│   ├── config.py, logs.py, exceptions.py, db.py, rate_limit.py
│   ├── ingestion/     parser, figure_extractor, chunker, pipeline, formats, uploads
│   ├── embeddings/    voyage
│   ├── vectorstore/   qdrant_store       # owns _build_filter -- the tenant boundary
│   ├── registry/      models, db         # DocumentRecord + its ingestion status
│   ├── worker/        app, tasks         # procrastinate app; api defers by NAME, never imports tasks
│   ├── retrieval/     retriever, reranker
│   ├── generation/    prompts, answer_service
│   ├── auth/          models, keys, service
│   └── api/           main, deps, schemas, routers/{ask, documents}
├── streamlit_app/Home.py                 # calls the pipeline in process, not over HTTP
├── scripts/           fetch_corpus, ingest, create_tenant
├── tests/unit/                           # Postgres/Redis-backed suites skip if unreachable — read the skip count
├── data/manifest.json                    # the pinned corpus
├── .docker/           Dockerfile, docker-compose.yml, nginx/
├── redis/             Dockerfile, redis.conf
├── docs/EPIC_2_PLAN.md, docs/EPIC_3_PLAN.md        # buildable plans for the unbuilt epics
└── docs/IMPLEMENTATION_PLAN.md           # the original plan, kept as history
```

The importable package is `app/` at the `portfolio/` root, matching
`[tool.uv.build-backend]` in `pyproject.toml`. CI lives at the **repo root**
(`.github/workflows/portfolio-ci.yml`) because GitHub Actions only discovers workflows
there; it is scoped to `portfolio/**` so sibling projects in this monorepo don't trigger
it.

Highest-leverage files to read first: `app/vectorstore/qdrant_store.py` (the tenant filter
and the delete-then-insert contract), `app/ingestion/chunker.py` (the three chunk kinds),
`app/generation/answer_service.py` (retrieve → rerank → cite), and `app/config.py` (every
setting, each with the reasoning inline).

## Development

The verification gate — all four, before pushing. `ty.toml` sets `error-on-warning`, so a
warning fails:

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run pytest tests/unit
cd .docker && docker compose config      # after any compose/Dockerfile edit
```

After editing `pyproject.toml`, run `uv lock` and commit the result — `uv.lock` is committed and
CI installs with `--locked`, which fails if the two have drifted.

Both service-backed suites *skip* when their service is unreachable, so a green local run
may have tested less than it looks. CI provides Postgres and Redis and then asserts
neither suite skipped, because a broken service wiring would otherwise be
indistinguishable from a pass.

[`CLAUDE.md`](CLAUDE.md) carries the failure contracts — the things that look correct and
aren't. Read it before changing the store layer, the compose file, or anything touching
`tenant_id`.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
