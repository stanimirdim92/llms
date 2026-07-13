# AI Engineer Portfolio — Iris.ai Track (Implementation Plan)

## Context

The source `PLAN.md` (uploaded separately) lays out a 4-epic portfolio project — RAG over scientific/technical documents → LLM eval framework → LangGraph agent with human-in-the-loop on the *same* vector store → production hardening — designed to mirror Iris.ai's actual stack for a job application. The repo `stanimirdim92/llms` is currently almost empty: just `.idea/` and one sibling folder, `LLM Engineers Handbook/` (a barely-started FastAPI + LangChain/LangGraph scaffold — uv/pyproject, Dockerfile, docker-compose with nginx+redis, one bare `GET /` route, no RAG/agent/eval code, empty README). There is no root README and no CI anywhere in the repo. This is a loose monorepo of sibling top-level project folders, so the new project gets its own self-contained sibling folder rather than living inside the handbook project.

The source `PLAN.md` leaves several implementation choices open (dataset, extraction library, vector DB, embedding/reranker provider, eval framework, CI, Epic 3's "second data source" and HITL mechanism, observability approach). This plan resolves every one of those concretely so the epics are directly buildable, without changing scope.

## Tech Stack (resolved decisions)

| Layer | Choice | Why |
|---|---|---|
| Dataset | ~45 curated arXiv papers, materials-science / battery domain (`cond-mat.mtrl-sci`) | Mirrors Iris.ai's actual R&D customer domains; has real tables and figures, not just prose |
| Corpus sourcing | `arxiv` Python client, pinned manifest (`data/manifest.json`, checked in) | Deterministic/reproducible demo, no live-scrape flakiness |
| PDF/table/figure extraction | **Docling** (IBM, OSS) + **PyMuPDF** for figure crops | Structured doc with layout-aware text, native table objects, figure bboxes — exactly what "tables intact / figures retrievable" requires |
| Figure captioning | Claude vision call on each cropped figure → caption becomes the figure's embedded chunk text | Keeps figures in the same single embedding space without a separate multimodal pipeline |
| Chunking | Docling `HybridChunker` for prose (section-path metadata); tables serialized whole to Markdown as atomic chunks; figures as their own chunk type | Preserves section context, guarantees tables never split mid-row |
| Vector DB | **Chroma** (embedded/persistent, local) | Free, zero infra — matters for a portfolio project others will try to run |
| Embeddings | **Voyage AI `voyage-3.5`** | Anthropic's recommended embedding partner (Anthropic ships none itself) |
| Reranker | **Cohere Rerank v3.5**, with local `bge-reranker-v2-m3` cross-encoder as an env-selectable fallback | Best quality via API, but proves the system isn't hard-locked to a paid API |
| Answering LLM | **Claude Sonnet 5**, using the native **Citations API** (`citations: {enabled: true}` on `document` blocks) + citation-forced system prompt | Structural per-claim grounding instead of relying on prose-only citation instructions |
| Eval framework | **RAGAS** (faithfulness, answer_relevancy, context_precision, context_recall, context_entity_recall) | Purpose-built for RAG; maps directly onto "hallucination rate + retrieval precision" |
| CI | **GitHub Actions** — first workflow in this repo | Repo is on GitHub, nothing to conflict with |
| Epic 3 second data source | arXiv "new submissions" listing (same category), polled into a local SQLite `incoming_queue` | Real, live data, zero extra infra |
| Epic 3 HITL mechanism | **LangGraph `interrupt()`** + `SqliteSaver` checkpointer, resumed via `Command(resume=...)`, surfaced in a Streamlit review page | Native LangGraph primitive, not a bolted-on queue |
| Observability | `structlog` JSON lines (latency/confidence/chunk-ids/tokens) as the base layer; **Arize Phoenix** (self-hosted, OpenInference auto-instrumentation) as the Epic 4 enhancement | Lightweight base + near-zero-code tracing enhancement, both self-hostable |
| Deployment | `docker-compose up` locally is the primary target (mirrors sibling project's nginx pattern); optional free-tier cloud deploy is a bonus, not required | Reviewers need one command to run it |

## Directory Layout

New sibling folder `AI Engineer Portfolio/` at repo root (not inside `LLM Engineers Handbook/`), self-contained with its own `pyproject.toml`/`uv.lock`/`Dockerfile`, Python 3.13 + uv + ruff to match the sibling project's conventions.

```
AI Engineer Portfolio/
├── README.md / ARCHITECTURE.md / TECHNICAL_DECISIONS.md / EVAL_METHODOLOGY.md
├── pyproject.toml, uv.lock, Dockerfile, docker-compose.yml, Makefile, .env.example
├── .github/workflows/{ci.yml, eval.yml}
├── data/{manifest.json, raw_pdfs/, processed/, chroma/, eval/{qa_dataset.jsonl, results/}, incoming_queue.db}
├── scripts/{fetch_corpus.py, ingest.py, build_eval_dataset.py, run_eval.py, poll_arxiv_feed.py}
├── src/portfolio_rag/
│   ├── config.py
│   ├── ingestion/{parser.py, figure_extractor.py, chunker.py, pipeline.py}
│   ├── embeddings/voyage.py
│   ├── vectorstore/chroma_store.py
│   ├── retrieval/{retriever.py, reranker.py}
│   ├── generation/{prompts.py, answer_service.py}
│   ├── observability/logging.py
│   ├── agent/{state.py, graph.py, nodes.py, cache.py, incoming_feed.py}   # Epic 3 — imports vectorstore/ingestion from above, no new store
│   └── eval/{ragas_runner.py, thresholds.py}
├── api/{main.py, routers/{ask.py, review.py, admin.py}, schemas.py}
├── streamlit_app/{Home.py, pages/{1_Review_Queue.py, 2_Reasoning_Trace.py, 3_Observability.py}}
└── tests/{unit/, integration/, eval/test_ragas_thresholds.py}
```

## Build Sequence

**Epic 1 — RAG Foundation** (in order): scaffold project → `fetch_corpus.py` builds the pinned manifest and downloads PDFs → `ingestion/parser.py` (Docling parse) → `ingestion/figure_extractor.py` (crop + Claude-vision caption) → `ingestion/chunker.py` (structure-aware, atomic tables, figure chunks) → `embeddings/voyage.py` + `vectorstore/chroma_store.py` + `ingestion/pipeline.py`/`scripts/ingest.py` to populate Chroma → `retrieval/retriever.py` + `retrieval/reranker.py` → `generation/prompts.py` + `generation/answer_service.py` (Citations API) → `api/routers/ask.py` (`POST /ask`) → `streamlit_app/Home.py` demo UI → manual spot-check: ~15 prose/table/figure questions, confirm every answer traces to a chunk/page.

**Epic 2 — Eval Framework** (only after `/ask` returns cited answers): author 50+ grounded Q&A pairs in `data/eval/qa_dataset.jsonl` → `eval/ragas_runner.py` → capture a deliberate "before" baseline (naive fixed-size chunking, no reranker) → `eval/thresholds.py` + `tests/eval/test_ragas_thresholds.py` as the CI gate → `.github/workflows/ci.yml` (lint+tests) and `.github/workflows/eval.yml` (RAGAS canary subset on PR, full suite on demand/nightly, blocks merge on regression) → capture "after" numbers with the real pipeline → write `EVAL_METHODOLOGY.md`.

**Epic 3 — Knowledge Curation Agent, HITL** (built on Epic 1's same Chroma collection — `agent/graph.py` imports `vectorstore/chroma_store.py` directly, never constructs a second store): `agent/state.py`/`graph.py` skeleton → `scripts/poll_arxiv_feed.py` + `agent/incoming_feed.py` (SQLite `incoming_queue`) → `agent/cache.py` (hash-keyed, skip re-fetch/re-embed) → `agent/nodes.py` (`fetch_incoming` → `parse_and_chunk` reusing Epic 1's pipeline → `classify_confidence` → `route`) → `interrupt()` + `SqliteSaver` checkpointer on the low-confidence branch → `api/routers/review.py` + `streamlit_app/pages/1_Review_Queue.py` (approve/reject resumes via `Command(resume=...)`) → `streamlit_app/pages/2_Reasoning_Trace.py` → acceptance check: feed a deliberately contradictory paper, confirm it's escalated not auto-committed, trace is inspectable.

**Epic 4 — Production Rigor** (last): multi-stage `Dockerfile` (api + streamlit targets) + `docker-compose.yml` (api + streamlit + phoenix, optional nginx) → `observability/logging.py` wired into `answer_service.py` and `agent/nodes.py` → `streamlit_app/pages/3_Observability.py` → add Phoenix service + OpenInference auto-instrumentation → `TECHNICAL_DECISIONS.md` (consolidating chunking/reranker/embedding/vector-db/eval-threshold rationale) → README rewrite, Iris.ai-docs style, architecture diagram + quickstart → optional free-tier cloud deploy → final check: `docker-compose up` works end-to-end locally.

## Critical Files

- `AI Engineer Portfolio/src/portfolio_rag/ingestion/chunker.py` — structure-aware chunking core (atomic tables/figures)
- `AI Engineer Portfolio/src/portfolio_rag/generation/answer_service.py` — retrieve→rerank→cite→answer orchestration, and the observability hook point
- `AI Engineer Portfolio/src/portfolio_rag/agent/graph.py` — LangGraph HITL agent; must import Epic 1's `vectorstore/chroma_store.py` rather than build a new store
- `AI Engineer Portfolio/src/portfolio_rag/eval/ragas_runner.py` — RAGAS metric computation, feeds the CI gate
- `AI Engineer Portfolio/docker-compose.yml` and `.github/workflows/{ci,eval}.yml`

## Verification

- Epic 1: run `scripts/ingest.py` against the pinned corpus, then manually query `/ask` (or the Streamlit UI) with ~15 prose/table/figure-referencing questions; confirm every answer cites a specific chunk/page and that table/figure content is retrievable (not flattened into prose).
- Epic 2: run `scripts/run_eval.py` before and after the real pipeline is in place; confirm `pytest tests/eval/test_ragas_thresholds.py` passes, and that a deliberately regressed config fails the CI gate in `eval.yml`.
- Epic 3: enqueue a deliberately contradictory/ambiguous arXiv paper via `poll_arxiv_feed.py`, run the agent, and confirm it triggers `interrupt()` (visible in the Streamlit Review Queue) rather than silently committing; verify the second run of the same paper hits the cache instead of re-embedding.
- Epic 4: `docker-compose up` from a clean checkout brings up api + streamlit + phoenix; confirm logs/traces appear in Phoenix and the observability Streamlit page, and that the README's quickstart steps work verbatim.
