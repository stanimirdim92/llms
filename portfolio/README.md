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

Of four planned epics, Epic 1 and three of Epic 4's five phases are built; the eval
framework (Epic 2) and the agentic curation layer (Epic 3) are designs with no code behind
them. [Status](#status) is precise about the boundary, including the gaps in what *is*
built.

## Quickstart

Requires Docker and an [Anthropic](https://console.anthropic.com/) plus
[Voyage AI](https://voyageai.com/) API key.

```bash
cd portfolio
cp .env.example .env      # then fill in ANTHROPIC_API_KEY and VOYAGE_API_KEY
cd .docker && docker compose up --build
```

That brings up six services: `api` (gunicorn + uvicorn workers), `streamlit`, `qdrant`,
`postgres`, `redis`, and `nginx` in front of the api. The API is on
`http://localhost:8000` directly or `http://localhost/` through nginx; Streamlit is on
`http://localhost:8501`, not proxied.

Every request needs an API key. There is no master key in the environment on purpose — a
key in env couldn't be revoked or rotated — so mint one:

```bash
uv sync --extra dev                                  # once; scripts/ isn't in the image
uv run python scripts/create_tenant.py "My Org"      # prints the key once
```

`scripts/` is deliberately not copied into the container, so this runs on the host and
talks to the compose Postgres over its published `5432`. `--list` shows tenants and keys,
`--revoke <key_id>` revokes one.

Then upload a document and ask about it:

```bash
curl -X POST http://localhost:8000/v1/documents \
  -H "x-api-key: pf_live_..." -F "file=@paper.pdf"

curl -X POST http://localhost:8000/v1/ask \
  -H "x-api-key: pf_live_..." -H "content-type: application/json" \
  -d '{"question": "What electrolyte did they use?"}'
```

The answer comes back with `citations` (quoted text plus `chunk_id`/`doc_id`/`page_no`)
and every chunk that survived reranking, so a wrong answer can be traced to whether
retrieval or generation caused it.

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
Python 3.14 is a hard floor; `uuid.uuid7()` is 3.14 stdlib.

```bash
uv sync --extra dev
uv run uvicorn app.api.main:app --reload
uv run streamlit run streamlit_app/Home.py
```

## Architecture

```
upload ──> parse ──> figures ──> chunk ──> embed ──> Qdrant (vectors + payload)
           Docling   Claude      3 kinds   Voyage └─> Postgres (one row per document)
                     vision

ask ──> embed ──> Qdrant search ──> rerank ──> generate ──> cited answer
        Voyage    (tenant-filtered)  Voyage     Claude +
                                     or local   Citations API
```

Ingestion is `async def` but the work that matters is offloaded: Docling's parse and the
Qdrant client's sync `upsert` go through `asyncio.to_thread`, because both are CPU-bound
or blocking and would otherwise stall every other request sharing the worker's event
loop. Figure captions go out as one batched vision call set with bounded concurrency.

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
| Document registry | Postgres + SQLModel, one row per ingested document |
| Auth | `x-api-key` → `tenants`/`api_keys` tables, SHA-256 hashed, individually revocable |
| Rate limiting | Per-tenant sliding window, one Lua script on `redis.asyncio` |
| Serving | gunicorn + `UvicornWorker`, `--preload`, behind nginx |
| Tracing | LangSmith (zero-code — every call is already a LangChain object) |
| Lint/type/test | ruff, `ty`, pytest; CI on every PR touching `portfolio/**` |

Every row above has a reason, several of them counterintuitive (why Qdrant point IDs
can't be chunk ids, why re-ingestion deletes before inserting, why SHA-256 rather than
argon2, why the limiter fails open). Those are in
[`TECHNICAL_DECISIONS.md`](TECHNICAL_DECISIONS.md), with the alternatives that were
rejected and what it would take to revisit each one.
[`ARCHITECTURE.md`](ARCHITECTURE.md) covers the agentic-architecture survey behind
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

**Not built.** These exist as designs in
[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) and nowhere else — there is
no code for any of them, so don't infer any from the plan's directory layout:

- **Epic 2 — Eval framework.** RAGAS metrics as LangSmith custom evaluators over a
  versioned dataset, with a CI threshold gate and a deliberate pre-reranker baseline to
  compare against.
- **Epic 3 — Knowledge-curation agent with HITL.** Playwright scraping, an
  orchestrator plus Curator/Evaluator subagents over the same Qdrant collection,
  prompt-injection defense on scraped content, and LangGraph `interrupt()` for human
  review.
- **Epic 4 Phases 3-5.** Documentation (this rewrite), observability/SLO alerting, and a
  user-facing signup flow. Phase-by-phase detail in
  [`EPIC_4_PLAN.md`](EPIC_4_PLAN.md).

**Known gaps in what *is* built**, stated rather than left to be discovered:

- The corpus is 6 papers, not the ~45 the plan called for, and Epic 1's final
  15-question prose/table/figure spot-check has not been run.
- **No test exercises Qdrant.** The auth tests hit a real Postgres and the rate-limit
  tests a real Redis, but nothing covers the store layer — bugs there surface only on a
  real ingest. This is how the point-ID constraint was found: in production, not in CI.
- Uploads are read fully into memory before the size check, so `MAX_UPLOAD_SIZE_MB`
  bounds what is *stored*, not what is buffered. Streaming to disk is tracked as
  `EPIC_4_PLAN.md` 1.6.
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
│   ├── registry/      models, db         # DocumentRecord, one row per ingested doc
│   ├── retrieval/     retriever, reranker
│   ├── generation/    prompts, answer_service
│   ├── auth/          models, keys, service
│   └── api/           main, deps, schemas, routers/{ask, documents}
├── streamlit_app/Home.py                 # calls the pipeline in process, not over HTTP
├── scripts/           fetch_corpus, ingest, create_tenant
├── tests/unit/                           # 8 files; Postgres/Redis-backed ones skip if unreachable
├── data/manifest.json                    # the pinned corpus
├── .docker/           Dockerfile, docker-compose.yml, nginx/
├── redis/             Dockerfile, redis.conf
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

Both service-backed suites *skip* when their service is unreachable, so a green local run
may have tested less than it looks. CI provides Postgres and Redis and then asserts
neither suite skipped, because a broken service wiring would otherwise be
indistinguishable from a pass.

[`CLAUDE.md`](CLAUDE.md) carries the failure contracts — the things that look correct and
aren't. Read it before changing the store layer, the compose file, or anything touching
`tenant_id`.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
