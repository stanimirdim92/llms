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
