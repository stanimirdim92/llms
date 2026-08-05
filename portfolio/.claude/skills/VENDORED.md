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
  becomes the bottleneck **and** cross-tenant search is rare. **Corrected 2026-08-05:** this
  entry used to say neither half held, on the grounds that every query read the shared corpus
  alongside the tenant's own documents. The corpus was removed the same day these skills found
  the index gap, so that sentence was stale within hours — every query is single-tenant now and
  `_build_filter` cannot match two tenants, which makes cross-tenant search impossible rather
  than rare. The half that still fails is the first: **nothing measures Qdrant's indexing
  throughput**, so there is no evidence it is the bottleneck. `docs/IDEAS.md` holds the live
  version of this condition.
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

---

# Vendored: `timescale/pg-aiguide`

**One skill of the ten**, copied verbatim.

| | |
|---|---|
| Source | https://github.com/timescale/pg-aiguide |
| Commit | `b4f11a45907af3abda0f79e784aff9a6d5eef468` (upstream dated 2026-06-26) |
| Vendored | 2026-08-05 |
| License | Apache 2.0 — `PG_AIGUIDE_LICENSE`, **plus `PG_AIGUIDE_NOTICE`** |
| Taken | `postgres-database-migration` only — `SKILL.md` (486 lines) + 3 `references/` (292) |

**Two licence files here where qdrant has one, and that is not tidiness.** This repo ships a
`NOTICE` ("Copyright 2025 Timescale, Inc., d/b/a Tiger Data") and Apache 2.0 §4(d) requires a
redistribution to carry the attribution notices from it. qdrant/skills has `LICENSE` and no
`NOTICE` — checked, not assumed — so that vendoring stays complete with one file.

Refresh:

    git clone --depth 1 https://github.com/timescale/pg-aiguide /tmp/pg-aiguide
    rm -rf portfolio/.claude/skills/postgres-database-migration
    cp -r /tmp/pg-aiguide/skills/postgres-database-migration portfolio/.claude/skills/
    cp /tmp/pg-aiguide/LICENSE portfolio/.claude/skills/PG_AIGUIDE_LICENSE
    cp /tmp/pg-aiguide/NOTICE   portfolio/.claude/skills/PG_AIGUIDE_NOTICE
    # then update the commit/date above, and re-check the exclusions below still hold

## Why this one, and why it is not premature

It lands on a gap this project has already written down twice. `app/db.py::init_db`'s docstring
says there is no Alembic and that a schema change currently means dropping the volume; `CLAUDE.md`
carries the contract that **`create_all` creates missing *tables*, never missing *columns***, so
adding a field to an existing model changes nothing, `init_db` reports success, and the next query
fails with `column ... does not exist`. `ApiKey.expires_at` was added by hand under exactly that
rule — against an empty table, which is why it cost nothing. The next one will not be: at the
10k-tenant × 10-document target, `documentrecord` holds 100k rows.

So the division of labour is: **rule 8 governs what a new column must *mean*** (absent data reads
as the pre-existing behaviour, then check the inverse); this skill governs **how to add it without
locking the table**. Neither substitutes for the other.

The five things in it that are worth having in the room rather than re-derived:

- `ADD COLUMN` nullable is metadata-only; with a **non-volatile** default it is still
  metadata-only on PG 11+; with a **volatile** one (`now()`, `gen_random_uuid()`) it is a full
  table rewrite. Three outcomes that look like one statement.
- `ADD CONSTRAINT ... NOT VALID` then `VALIDATE CONSTRAINT` — the second half scans under
  `ShareUpdateExclusiveLock`, so reads and writes continue.
- A unique constraint the non-blocking way: `CREATE UNIQUE INDEX CONCURRENTLY`, then
  `ADD CONSTRAINT ... UNIQUE USING INDEX`.
- `lock_timeout` on every production DDL, and *why*: a fast `ALTER TABLE` queued behind one long
  `SELECT` blocks every query that arrives after it. The failure is an application-wide stall
  caused by a statement that would have taken a millisecond.
- After any failed `CREATE INDEX CONCURRENTLY`, check `pg_index.indisvalid` — a crashed build
  leaves an invalid index behind that costs writes and serves nothing.

**One project-specific interaction it does not know about.** `CREATE INDEX CONCURRENTLY` cannot
run inside a transaction, and `init_db` does all its DDL inside one (`get_engine().begin()`, so
that `pg_advisory_xact_lock` releases on exit). A concurrent index therefore cannot be added from
`init_db` — it needs its own autocommit connection or a psql session, outside the boot path.

## Three vendor links in it, deliberately not edited out

§ *Fork-Based Migration Testing* recommends [Neon](https://neon.tech) and
[Ghost](https://ghost.build) for fast forking, and PgDog for replaying production traffic at a
fork. **This project has no fork facility** — Postgres runs as a compose service on a named
volume. The applicable path is the skill's own *Without Forking* block: `pg_dump -Fc` +
`pg_restore` into a scratch database, or `createdb -T`.

Left verbatim so the refresh above stays a copy rather than a merge. Recorded here so a session
reading § Fork-Based Migration Testing does not treat "sign up for a forking provider" as this
project's next step.

## The other nine, and two outside candidates

Same test as the langchain set: a skill nobody triggers is not free, because descriptions are
always in context.

- **`postgres`** (the hub) — **excluded, and this is the important one.** It triggers on "any
  PostgreSQL database work" and routes to **`pgvector-semantic-search`**, whose own triggers
  include "Implement RAG (Retrieval Augmented Generation) with PostgreSQL". That is the
  `langchain-rag` failure mode again, against a different decision: this project's vector store
  is Qdrant, chosen and recorded in `docs/TECHNICAL_DECISIONS.md`. Taking the hub means a
  retrieval question here can surface advice to build the retrieval layer in Postgres instead.
  The narrow trigger list on `postgres-database-migration` is precisely why *it* is safe to take.
- **`ghost-database`** — a commercial upsell for Ghost's hosted forking. No.
- **`setup-timescaledb-hypertables`, `find-hypertable-candidates`,
  `migrate-postgres-tables-to-hypertables`, `design-postgis-tables`** — TimescaleDB and PostGIS;
  neither extension is installed or planned.
- **`design-postgres-tables`, `postgres-hybrid-text-search`** — the first overlaps `add-endpoint`
  and the model modules' own documented constraints; the second is Postgres full-text search,
  which retrieval here does not use.

Two candidates from elsewhere, checked on the same bar and rejected:

- **`duthaho-postgresql`** (skillsdirectory.com) — **rejected on provenance first.** The listing
  page 403s through the proxy and no canonical repository was found, so there is no licence file
  and no commit to pin; nothing could be entered in a table above honestly. On content it would
  have failed anyway: no raw SQL exists in `app/` beyond the health probe's `SELECT 1`, no
  `Relationship` field exists for its N+1 pitfall to apply to, and one of its two migration
  examples — `ALTER TABLE users ADD CONSTRAINT unique_email UNIQUE (email)` — is presented as
  routine while being the form that builds the index under `AccessExclusiveLock`, blocking reads
  and writes for the whole scan. The skill taken above covers that exact case correctly.
- **`Jeffallan/claude-skills`'s `postgres-pro`** — MIT and honestly licensed, rejected on fit:
  2071 lines of which ~446 are streaming replication (one instance here), ~321 JSONB (no JSONB
  column), and ~404 extension management (none installed). It also writes in a "Senior PostgreSQL
  expert" persona voice that reads as a different document pasted into this set.

---

# Evaluated as a whole repo and not vendored: `alirezarezvani/claude-skills`

Scanned 2026-08-05 at `aa8d778811a557a2c28ccadda4cf3d0bd028a4cc`. **MIT**, clean, no commercial
restriction in the licence (the repo *sells* bundles via `STORE.md`, but the content itself is MIT).
798 `SKILL.md` files, of which 436 are a flat `.gemini/skills` mirror — roughly **440 unique
skills**, ~137 of them engineering.

**Nothing was taken.** Recorded at this length only because scanning 440 skills is expensive and
nobody should pay for it twice. The one entry worth revisiting, `slo-architect`, is parked in
`docs/IDEAS.md` with its precondition.

Roughly 300 skills are business content — `c-level` (68), `marketing` (48), `ra-qm` (19),
`product`, `finance`, `business-*`, `commercial` — irrelevant to a Python retrieval API and not
examined past the index. Of the engineering ones, these are the calls that took real reading:

| Skill | Verdict |
|---|---|
| `rag-architect` | **No — and it is the instructive one.** Its `retrieval_evaluator.py` evaluates a **TF-IDF retriever it implements itself** (`class TFIDFRetriever`, 577 lines, stdlib-only), not your pipeline. Run it here and you get precision@k/recall@k/NDCG numbers that look like Epic 2 metrics and describe a system this project does not have — no Qdrant, no Voyage embeddings, no reranker. Rule 11 as a tool: a fluent, confident answer from the wrong material. Its `chunking_optimizer.py` has the same shape, and would recommend a chunking strategy without knowing Docling's structure-aware chunking exists. Its *hard rules* are good ("never present model names or vendor prices as current facts") and are already rules 13 and 14 here. |
| `senior-prompt-engineer` | **No, but its input contract is worth copying.** Unlike the above, its `rag_evaluator.py` takes **your** retrieved contexts and **your** answers as JSON and grades those — the right shape. Two reasons it stays out: faithfulness is scored by token overlap and ROUGE-L, a lexical proxy that punishes a faithful paraphrase and rewards a copied-but-wrong answer, while `docs/EPIC_2_PLAN.md` chose RAGAS with an LLM judge; and it would be a **third** voice on eval methodology after that plan and `qdrant-search-quality`. Two documents on one topic disagree within a month; three is worse. |
| `karpathy-coder` | **No — it is the repo root's `CLAUDE.md` rules 1–4, already.** Same source, same four principles. What it adds is enforcement, and the enforcement is `complexity_checker.py` thresholding on max file lines, max imports, max nesting, max function lines, average cyclomatic complexity. The root `CLAUDE.md` says outright that the community extensions "built on arbitrary thresholds" were dropped deliberately. Taking this would reinstate them under the name of the rules that replaced them. |
| `llm-cost-optimizer` | **No, on trigger breadth.** "Use proactively whenever LLM API costs come up — *or should* … 'build me an AI endpoint' … apply immediately when max_tokens is not set." It would fire on nearly every task here, and its named triggers are already handled: `max_tokens` *is* set, and `truncated` on the `/ask` response exists precisely so a clipped answer is detectable. |
| `env-secrets-manager` | **No, redundant.** `.env` is untracked, secret scanning runs in CI, and `tests/unit/test_secrets.py` sweeps every `_key`/`_password`/`_secret`/`_token` field so a credential added as a plain `str` fails the suite. The skill's leak-detection story is weaker than what is already wired. |
| `security-guidance` | **No.** It is a PreToolUse *hook*, and its pattern list is Node/React-centric (`child_process.exec`, `innerHTML`, `dangerouslySetInnerHTML`). The Python-relevant ones — `eval(`, `pickle`, `yaml.load`, `shell=True`, `os.system` — are all ruff `S`-rule territory. |
| `adversarial-reviewer` | **No, and the reason is a rule violation.** "Each persona MUST find at least one issue — no 'LGTM' escapes." A reviewer required to produce a finding produces one whether or not it exists, which is manufacturing false positives to defeat rubber-stamping. Rules 7 and 11 both point the other way; `/code-review` and `/security-review` are already available. |
| `slo-architect` | **Not now, and the only near miss.** Genuinely well made — SRE Workbook discipline, honest "when NOT to use" section. Parked in `docs/IDEAS.md` because SLIs, error budgets and burn-rate alerts need production traffic and an on-call rotation to mean anything, unlike the LangGraph skills, which needed only code to exist. |
| `ai-security` | **No as a skill — but it produced the one real finding of the scan.** Its scanner is regex signature matching over *prompts*, which is not this system's exposure. Its § *Indirect Injection via External Content* is, and it named a gap: retrieved chunk text goes verbatim into Anthropic `document` blocks and the word "injection" appears nowhere in `app/` or in any doc here. Now recorded, with its mitigating conditions, in `docs/IDEAS.md` under Auth. **A skill that produces one finding and then costs context forever is a finding, not a skill** — take the finding. |
| `migration-architect`, `database-designer`, `database-schema-designer`, `sql-database-assistant` | **No, superseded.** Four overlapping takes on schema and migration work, against `postgres-database-migration` which was just vendored for exactly this and is Postgres-specific rather than SQL-generic. |
| `senior-backend`, `senior-fullstack`, `senior-architect`, `senior-ml-engineer`, `senior-data-*`, `senior-qa`, `senior-frontend` | **No.** Persona skills with broad triggers — the `postgres-pro` failure mode. `senior-qa` and `senior-frontend` are React/Jest specifically; Phase 6's UI does not exist. |
| `agenthub` + `spawn`/`eval`/`merge`/`board`/`status`, `autoresearch-agent` + `loop`/`run`/`resume`, `workflow-builder`, `agent-designer` | **No.** Multi-agent orchestration machinery, unrequested, and Claude Code ships its own. |
| `docker-development`, `dependency-auditor`, `ci-cd-pipeline-builder`, `performance-profiler`, `observability-designer`, `chaos-engineering`, `incident-*`, `runbook-generator`, `red-team`, `threat-detection`, `cloud-security`, `terraform-patterns`, `helm-chart-builder`, `kubernetes-operator`, `aws`/`azure`/`gcp` architects | **No.** Either already covered by this project's own documented Docker and CI knowledge (`cap_drop` capabilities, the postgres-18 volume path, pip-audit, Dependabot, CodeQL), or aimed at infrastructure that does not exist — one compose stack, no Kubernetes, no cloud account, no on-call. |

One quality signal noted while scanning, in fairness both ways: the repo's own
`.gemini/skills-index.json` records a literal `">-"` as the description for ~12 skills, so its
generator mishandles folded YAML frontmatter. The `SKILL.md` files themselves are fine — several
of the ones read above are better written than their index entries suggest.
