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

  **It already found something.** The skill says to create a keyword payload index on the
  tenant field with `is_tenant=true` (v1.11+), which co-locates each tenant's vectors so they
  are served by sequential reads. We create **no payload index at all** — `_build_filter`
  keys on `metadata.tenant_id` and `metadata.chunk_type` on every query, and
  `delete_document` on `metadata.doc_id`, all unindexed. `qdrant-scaling`'s tenant-scaling
  page lists skipping `is_tenant=true` under things not to do. Not fixed yet: it is a
  one-time `create_payload_index` call at collection setup, invisible at 6 documents and
  **required** at the stated 10k-tenants/10-documents-each target (order 1M points).
  Tracked here rather than silently added, since it is outside the change that vendored
  these.
- **`qdrant-search-quality`** — golden sets, recall@k, hybrid search, when reranking helps.
  This is Epic 2's subject matter; consult it when building the eval framework rather than
  inventing a methodology.
- **`qdrant-performance-optimization`** and **`qdrant-monitoring`** — relevant to Epic 4
  Phase 4, and to the fact that nothing currently measures Qdrant at all.
- **`qdrant-scaling`** — for the stated 10k-tenants/10-documents-each target.

Less relevant here: `qdrant-edge`, `qdrant-deployment-options` (settled: self-hosted via
compose), `qdrant-version-upgrade`, `qdrant-model-migration` (would matter if the Voyage model
changed), `qdrant-clients-sdk` (we go through `langchain-qdrant`).
