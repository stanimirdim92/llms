# Subagents and skills

Not auto-loaded -- read it when choosing or changing an agent
or skill. Each definition's own frontmatter is what Claude Code actually loads.

## Subagents

Six in `.claude/agents/`, **all read-only**, none permitted to report that it ran anything.
`../CLAUDE.md` holds the rule about what is never delegated -- the gate, a failure-contract edit,
and the final verdict on a finding. They are named by *task*, not by job title: a role name
("senior engineer", "QA") invites persona drift and has no fixed question, which is the property
that makes delegation work here.

Sweeps -- wide, shallow, one fixed question:

- **`doc-consistency`** — sweeps the document set for claims the code no longer supports or that
  contradict another document. It exists because a sentence that was true when written, in a file
  nobody re-reads, is this repo's most common defect: three files claimed the `m=0`/`payload_m`
  Qdrant trade was blocked by a shared corpus that had been removed hours earlier, and it was
  found by accident months later. Run it after any removal or rename.
- **`route-audit`** — every route in `app/api/routers/` against the `add-endpoint` checklist. The
  boundary is re-established per route *and* per query, so exhaustive beats spot-checking; the
  definition carries the known false positives (health routes have no auth or rate limit on
  purpose) so they stop being re-reported.
- **`candidate-triage`** — licence and provenance first, then fit against the recorded decisions,
  for anything third-party. Encodes the traps that have actually sunk candidates here: hub skills
  that route to a rejected stack, shipped "evaluators" that measure their own toy retriever, and
  descriptions broad enough to fire on every task.

Per-change checks -- run against a diff or a proposal:

- **`contract-review`** — a diff against § Never, § Failure contracts, § Config invariants and
  `PATTERNS.md`. Deliberately **not** a general code review: `/code-review`, `/security-review` and
  `/simplify` already do that and cannot know that dropping one `delete` from `QdrantStore.upsert`
  leaves retrievable stale points with the suite green. It is told to report nothing a competent
  outside reviewer would also find.
- **`test-gaps`** — what the change leaves untested, and which tests would still pass with the guard
  deleted (rule 15). It **must not run the suite**; a pass reported by an agent is a claim, which is
  rule 12 one level removed. Carries the three shapes that have fooled this suite before: a boundary
  test with a limit of one, a membership assertion where an exact-set assertion is possible, and an
  in-process test of a cross-process race.
- **`design-review`** — a proposal against `TECHNICAL_DECISIONS.md`, `IDEAS.md`'s rejected table and
  the epic plans, *before* it is built. Its one required distinction is **revisit** (the reasoning
  still holds and must be overturned) versus **stale conflict** (the reason expired, as the graphrag
  Python-floor argument did) — those need opposite responses.

**No coder agent, deliberately.** Every route here touches the tenant boundary, so a writing agent
hits a failure contract almost immediately, and the surveys run on 2026-08-05 produced good breadth
*plus* several confident findings that were wrong on inspection — a cost that is one verification pass
for a read-only sweep and committed code from a coder. When work genuinely is file-disjoint (a rename
across N call sites, a mechanical migration), spawn worktree-isolated subagents per slice or use
`/batch`, and integrate and run the gate here. That needs a precise brief, not a role.

**Definitions are picked up at session start only**, and discovery walks **up** from the working
directory rather than down as skills do. Both measured; the probe detail and the open question about
whether a repo-root session resolves these are in `docs/MEMORY.md`.

## Skills

Ours, in `.claude/skills/`:

- **`verify`** — the gate, and the two ways it lies (silently skipped service-backed suites; the
  pre-release-interpreter workaround that also rewrites `uv.lock`). Use it instead of running the
  commands from memory.
- **`add-endpoint`** — the per-route checklist. Authorization here is per-route *and* per-query,
  so a forgotten `CurrentTenant` or a `doc_id` lookup without `tenant_id` in the WHERE clause is
  a silent leak rather than an error.
- **`run-stack`** — bringing the stack up, minting a key, and tracing one document across
  api → job → worker → Qdrant → registry when it misbehaves.
- **`changelog`** — what belongs in `CHANGELOG.md` versus `docs/MEMORY.md`'s session log, and why
  most commits produce no entry at all.

From plugins, enabled in the committed `.claude/settings.json`:

- **`qdrant-skills`** (`qdrant:qdrant-*`, 11 skills). Reach for `qdrant:qdrant-multitenancy` before
  touching the tenant filter and `qdrant:qdrant-search-quality` for Epic 2's eval work, rather than
  re-deriving either. Unpinned -- it follows upstream.
- **`llm-application-dev` is disabled here** on purpose: its RAG/LangChain hub skills argue with the
  decision record, and its `ai-engineer`/`vector-database-engineer` agents are all-tools coder agents.

Vendored verbatim, at pinned commits, with provenance and refresh steps in
`.claude/skills/VENDORED.md`:

- **`langchain-dependencies`** from github.com/langchain-ai/langchain-skills. (The three
  `langgraph-*` taken alongside it were removed 2026-09-24; re-vendor them, not the all-or-nothing
  upstream plugin, when Epic 3 starts.)
- **Three `langsmith-*`** (`evaluator`, `dataset`, `trace`) from
  github.com/langchain-ai/langsmith-skills. LangSmith is already wired here, so these describe a
  service in use rather than a candidate. **They do not settle the eval architecture:**
  `docs/EPIC_2_PLAN.md` decided against LangSmith-only because the regression gate must work offline
  and in version control, and hosting the app does not change what CI needs. They cover the judged
  metrics and interactive exploration; `recall@k`, routing accuracy, the parquet run rows and the
  committed baseline are still local.
- **`postgres-database-migration`** from github.com/timescale/pg-aiguide — one skill of that
  repo's ten. Read it before authoring a revision that touches a populated table -- columns are
  added by an Alembic revision and never by hand, because a hand-written `ALTER` leaves
  `alembic_version` claiming a schema the database no longer has. It carries the lock level of
  every common DDL operation, which is the thing that
  decides whether a one-millisecond statement stalls the whole API. Note that **`CREATE INDEX
  CONCURRENTLY` cannot run inside a transaction** and `init_db` does all its DDL inside one, so a
  concurrent index needs its own autocommit connection — the skill can't know that.

**Take narrow leaves from these repos, never the hubs.** A hub claims a whole topic, and the topics
here are decided, so a hub argues back at the decision record — which is worse than no skill.
`langchain-rag` and `pg-aiguide`'s `postgres` are both excluded on that ground and must stay
excluded; `VENDORED.md` has the per-skill reasoning and should not be restated here.
