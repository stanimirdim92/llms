# Epic 3 — Curation agent with human-in-the-loop: implementation plan

The design is in `docs/IMPLEMENTATION_PLAN.md` (orchestrator + Curator + Evaluator subagents,
MCP tool scoping, episodic memory, `interrupt()` on low confidence) and the topology diagram
is in `docs/ARCHITECTURE.md` § 2. Both still hold — this file records what has changed underneath
that design since it was written, so the plan is buildable against the code that now exists
rather than the code that was imagined.

Nothing here is built.

## What changed under the original plan

| Original plan says | Now | Why |
|---|---|---|
| `worker/arq_worker.py`, Redis-backed | **procrastinate**, Postgres-backed — reuse `app/worker/` | Already built for Phase 5.1. The row and its job commit in one transaction; a Redis broker leaves a window where the row exists and the job does not. See `docs/TECHNICAL_DECISIONS.md` § "Job queue". |
| `agent/cache.py` — hash-keyed skip of re-fetch/re-embed | Same idea, but the **model-call cache** is the version worth building | Parse caching already exists (`processed_dir`). What is missing is caching *model* calls — the pattern taken from graphrag's LLM cache. Key on `sha256(payload + prompt_version + model_id)`; without `prompt_version` a prompt edit silently serves stale output forever. |
| `sqlmodel` episodic decision log | Unchanged, but note the datetime contract | `SQLModel` datetime fields need an explicit `sa_column` **and** a runtime `datetime` import — see `CLAUDE.md`'s failure contracts. This bit `save_document_record` and cost weeks. |
| `PostgresSaver` checkpointer | Unchanged, and `langgraph-checkpoint-postgres` is already a declared dependency | The SQLite checkpointer is **not** an option: one database engine, per `docs/TECHNICAL_DECISIONS.md`. |
| Scrape → parse → embed as one job | Same shape, but it must go through `ingest_document` | That function owns the terminal `ingested` write and the `EmptyDocumentError` guard. A second ingestion path would diverge on what a finished row looks like. |
| `injection_guard.py` heuristic + Claude classification | Unchanged, and now has a sibling | Phase 2.0's intent classifier is the same shape of call. Build them against one structured-output helper rather than two. |
| Scraped documents join **a shared corpus**, with `_build_filter` drawing the boundary between it and per-session tenant uploads (`docs/IMPLEMENTATION_PLAN.md`'s own wording, Critical Files § `qdrant_store.py`) | **There is no shared tenant.** `GLOBAL_TENANT` was removed 2026-08-03 — `_build_filter` now raises on an empty `tenant_id` and matches exactly **one** tenant, with no default (`CLAUDE.md` § The tenant boundary) | The removal closed a real leak (`MatchAny([global, caller])` meant "your documents *plus* everyone's"), but it leaves this epic's scraper with **no tenant to write under** — the original plan's assumption is gone, not merely renamed. See Open design questions below; don't build the scraper against the old assumption. |

## Scale consequences

The target is now 10k tenants × 10 documents (`docs/TECHNICAL_DECISIONS.md` § "Scale target").
Two items in this epic are affected:

- **The incoming queue is a Postgres table** and is written by scrapers, not users. It needs
  its own retention policy; the document registry's growth is bounded by uploads, this table's
  is not.
- **Episodic memory is consulted per curation decision.** At scale that read must be indexed
  and bounded (top-k similar past decisions), not a full scan of the decision log. Design it
  as a retrieval problem from the start rather than a `SELECT *` that works at 50 rows.

## Ordering note

The original build sequence puts the agent before Epic 4's Phases 5–6. That ordering is
unchanged, but one dependency is now explicit: **`eval/agent_trace_assertions.py` needs both
this epic's agent and Epic 2's harness**, so escalation-behaviour regression tests cannot be
written until Epic 2 exists. Build the agent's acceptance checks (a)–(f) from the original
plan as ordinary integration tests first; promote them into the eval harness afterwards.

## Open design questions

Neither of these is resolved by anything already written — they need an answer before build,
not during it.

- **Who owns the curated corpus, now that there's no shared tenant?** The scraper's whole point
  is a corpus every tenant can draw on, but the tenant boundary (`CLAUDE.md` § The tenant
  boundary) requires a real, non-default `tenant_id` on every write and every query. Three
  live options, not yet chosen between: (a) a dedicated operator/house `tenant_id` that curated
  documents are written under, readable by any tenant that opts in — an explicit grant, not a
  filter bypass; (b) per-tenant curation, where the scraper's output is filed under the
  requesting tenant like any upload — defeats the point of a shared KB, but needs no new
  mechanism; (c) revisit whether a shared corpus belongs in this system at all, given the
  standing directive not to reintroduce one. Whichever is picked has to be argued in
  `docs/TECHNICAL_DECISIONS.md`, not assumed from the pre-removal design.
- **Should episodic memory learn from anything beyond the HITL verdict itself?** Today the
  design is a log of past *curation* approve/reject decisions, consulted by the Curator. A
  downstream signal — whether an answer grounded in a curated document later got a thumbs-down,
  or was cited at all — is a different, currently-uncaptured kind of feedback that could bear on
  whether a past curation call should be trusted the same way twice. Worth deciding once Epic 2's
  eval harness exists to generate that signal, not before; recorded here so it isn't rediscovered
  from scratch when Epic 2 lands.

## Acceptance checks

Unchanged from `docs/IMPLEMENTATION_PLAN.md` — (a) contradictory paper escalates,
(b) injected instructions are caught, (c) mid-run kill does not duplicate or lose work,
(d) Curator/Evaluator disagreement escalates despite high confidence, (e) episodic memory
demonstrably reduces re-escalation, (f) a subagent calling `commit` is rejected at the MCP
scope level rather than merely discouraged by prompt text.

(f) is the one worth stating twice: prompt instructions are not an authorization boundary.
