# Vendored skills

Everything under `qdrant-*/` in this directory is **third-party, copied verbatim** from
Qdrant's own skills repository. `run-stack/` is ours; nothing else here is.

| | |
|---|---|
| Source | https://github.com/qdrant/skills |
| Commit | `aa2355fcf06b805110fb8cecbd1aa4d64c15eb73` |
| Vendored | 2026-07-30 |
| License | Apache 2.0 — see `QDRANT_LICENSE` (same license as this project) |
| Skills | 10 top-level, 30 markdown files, ~324KB |

## Why vendored rather than installed as a plugin

Upstream ships this as a Claude Code plugin marketplace (`.claude-plugin/marketplace.json`),
so the alternative is `/plugin marketplace add qdrant/skills`. That would auto-update and add
nothing to the repo — but it is *per-user machine config*, so it only helps whoever ran it. In
the repo, the guidance is available to every session and every contributor, and is pinned to a
known commit rather than shifting under us.

The cost is the usual vendoring cost: these go stale silently. Refresh deliberately:

    git clone --depth 1 https://github.com/qdrant/skills.git /tmp/qdrant-skills
    rm -rf portfolio/.claude/skills/qdrant-*
    cp -r /tmp/qdrant-skills/skills/qdrant-* portfolio/.claude/skills/
    cp /tmp/qdrant-skills/LICENSE portfolio/.claude/skills/QDRANT_LICENSE
    # then update the commit/date above

## Scope

These live under `portfolio/` rather than the repo root deliberately. Skills in a
subdirectory only apply when working on files beneath it, and `portfolio/` is the only one of
this monorepo's four projects that uses Qdrant — at the root they would load into every
`fastai-dl/` and `transformers-course/` session for nothing.

Only the 10 top-level `SKILL.md` descriptions enter session context. The nested ones
(`qdrant-scaling/scaling-data-volume/tenant-scaling/SKILL.md` and friends) are
progressive-disclosure references their parent pulls in on demand.

## The ones that actually bear on this project

Recorded so a future session knows which to reach for rather than re-deriving it:

- **`qdrant-multitenancy`** — we run one collection with a `tenant_id` payload filter
  (`vectorstore/qdrant_store.py::_build_filter`), which is exactly what this skill covers.
  Read it before changing the tenant boundary.

  **It found something, and it is now fixed (2026-08-03).** The skill says to create a
  keyword payload index on the tenant field with `is_tenant=true` (v1.11+), which co-locates
  each tenant's vectors so they are served by sequential reads; `qdrant-scaling` lists
  skipping it under things not to do. We had **no payload index at all**.
  `qdrant_store._ensure_payload_indexes`, called from `QdrantStore.__init__` after the
  collection is created, now indexes `metadata.tenant_id` with `is_tenant=True` and
  `metadata.doc_id` as a plain keyword.

  Note the filter it protects changed shape on the same day: `_build_filter` matches **one**
  tenant with `MatchValue`, since the shared `global` corpus was removed. The skill's
  payload-tenancy advice is unaffected -- one collection, one tenant field, a `must` filter on it
  -- and the tenant field is if anything more clearly a tenant field now.

  Two things worth knowing before touching it. **`metadata.chunk_type` is deliberately not
  indexed** — `_build_filter` accepts `chunk_types` but no production caller passes it, so an
  index would cost write amplification on every upsert to serve nothing. And **the effect is
  not testable in-memory**: `qdrant_client`'s local mode warns "Payload indexes have no effect
  in the local Qdrant" and reports an empty `payload_schema`, so the unit tests assert the
  calls and their parameters, while the effect was verified once against a real
  `qdrant/qdrant:v1.18.3` container (`data_type=keyword, is_tenant=True`).

  Still not done, from `qdrant-scaling`: the `m=0` + `payload_m` trade that builds per-tenant
  HNSW graphs only. That one is explicitly conditional — take it *if* indexing throughput
  becomes the bottleneck and cross-tenant search is rare. Neither holds here: nothing measures
  Qdrant yet, and every query reads the shared corpus alongside the tenant's own documents, so
  cross-tenant reads are the norm rather than the exception.
- **`qdrant-search-quality`** — golden sets, recall@k, hybrid search, when reranking helps.
  This is Epic 2's subject matter; consult it when building the eval framework rather than
  inventing a methodology.
- **`qdrant-performance-optimization`** and **`qdrant-monitoring`** — relevant to Epic 4
  Phase 4, and to the fact that nothing currently measures Qdrant at all.
- **`qdrant-scaling`** — for the stated 10k-tenants/10-documents-each target.

Less relevant here: `qdrant-edge`, `qdrant-deployment-options` (settled: self-hosted via
compose), `qdrant-version-upgrade`, `qdrant-model-migration` (would matter if the Voyage model
changed), `qdrant-clients-sdk` (we go through `langchain-qdrant`).

---

# Vendored: `langchain-ai/langchain-skills`

Four skills copied verbatim, on the same terms as the qdrant set above.

| | |
|---|---|
| Source | https://github.com/langchain-ai/langchain-skills |
| Commit | `f3ea282efb82c84f1093ae58006841e66ca28a94` |
| Dated | 2026-07-30 |
| License | **MIT**, declared in the upstream `.claude-plugin/plugin.json` — copied here as `LANGCHAIN_SKILLS_LICENSE.json` |
| Taken | `langchain-dependencies`, `langgraph-fundamentals`, `langgraph-persistence`, `langgraph-human-in-the-loop` |

**Weaker provenance than the qdrant set, and worth knowing.** There is no `LICENSE` file in that
repository; the MIT declaration exists only in the plugin manifest, which is why the manifest
itself is vendored as the licence evidence rather than a licence file. The repo also describes
itself as "in early development; APIs and content may change" — pinning the commit matters more
here than it did for qdrant.

Refresh the same way:

    git clone --depth 1 https://github.com/langchain-ai/langchain-skills /tmp/lc-skills
    cp -r /tmp/lc-skills/config/skills/<name> portfolio/.claude/skills/
    cp /tmp/lc-skills/.claude-plugin/plugin.json portfolio/.claude/skills/LANGCHAIN_SKILLS_LICENSE.json
    # then update the commit/date above, and re-check the exclusions below still hold

## Why these four and not the other eighteen

Skill *descriptions* are always in context, so a skill nobody triggers is not free — it dilutes
triggering for the ones that matter, including `verify`, `add-endpoint` and `changelog`, which are
the three that actually stop bugs here. The set was cut on that basis.

- **`langchain-dependencies`** — pays off immediately. This project pins ~10 `langchain-*`
  packages, went through the 1.0 split (`langchain-classic`, `CrossEncoderReranker` changing
  package), and takes a Dependabot PR every few days. A version reference for the ecosystem is
  the one thing here that is useful today rather than at some future epic.
- **`langgraph-fundamentals`, `langgraph-persistence`, `langgraph-human-in-the-loop`** — Epic 3
  is a LangGraph agent with human-in-the-loop curation, `langgraph-checkpoint-postgres` is
  already a declared dependency, and `CLAUDE.md` carries a standing directive that its
  checkpointer must be Postgres and never SQLite. `langgraph-persistence` covers exactly
  checkpointers, `thread_id` and `Store`; the HITL one covers `interrupt()` and
  `Command(resume=...)`. These are installed ahead of use because the epic is designed and the
  dependency is already pinned — reach for them the moment `app/agent/` exists.

## Deliberately excluded

### `langchain-rag` — **do not vendor this one**

Its description is "INVOKE THIS SKILL when building ANY retrieval-augmented generation (RAG)
system. Covers document loaders, RecursiveCharacterTextSplitter, embeddings (OpenAI), and vector
stores (Chroma, FAISS, Pinecone)."

Every element of that is something this project rejected on purpose and recorded rejecting in
`docs/TECHNICAL_DECISIONS.md`: `RecursiveCharacterTextSplitter` instead of Docling's structure-aware
chunking (a table split mid-row yields chunks that are individually meaningless and collectively
misleading), OpenAI embeddings instead of Voyage, and **Chroma**, which this project migrated
*off* deliberately. Combined with triggering as aggressive as "ANY RAG system", it would fire on
retrieval work here and recommend the stack we removed — a future session would then be choosing
between a skill and a decision record that contradict each other. That is rule 6 turned into a
live hazard, so the exclusion is the point rather than an oversight.

### The rest

- **Six quickstarts** (`langchain-python`/`typescript`, `langgraph-python`/`typescript`,
  `deepagents-python`/`typescript`) — this project is well past a weather or math example.
- **Five Deep Agents skills** plus `managed-deep-agents` — Deep Agents is not used and not
  planned; Epic 3 is LangGraph.
- **`ecosystem-primer`** — framework *selection* guidance. Already selected.
- **`langchain-fundamentals`, `langchain-middleware`** — real overlap with the LangGraph three,
  and `langchain-middleware`'s HITL material duplicates `langgraph-human-in-the-loop`. Take one
  of a pair, not both; revisit if Epic 3 ends up using `create_agent` rather than a `StateGraph`.
- **`eval-engineering`, `langsmith-online-eval-engineering`** — the closest call. Epic 2 *is* an
  eval framework, but these target Harbor tasks and LangSmith online evaluators, while
  `docs/EPIC_2_PLAN.md` specifies a golden set with recall@k over parquet + DuckDB. Installing
  them would quietly argue for a different tool than the plan chose. Read them when Epic 2
  starts and decide deliberately; do not let a skill make that call by triggering first.
- **`langgraph-cli`, `swarm`** — no current use.
