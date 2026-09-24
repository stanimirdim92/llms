RAG over scientific documents, plus an LLM eval framework and an agentic
human-in-the-loop curation layer.

Built: Epic 1 (retrieve -> rerank -> generate, multi-format uploads, Docker stack), Epic 4
Phases 1-3 (API-key auth with scopes, expiry, and CRUD; tenant scoping; per-key rate
limiting; docs), and Phase 5.1 (ingestion behind a Postgres-backed job queue) -- see
`docs/EPIC_4_PLAN.md` for the rest. Not built: Epic 3, designed in
`docs/IMPLEMENTATION_PLAN.md` only -- no agent. Don't assume code for it. Epic 2 (the eval
framework) has its golden set (`data/eval/qa_dataset.jsonl`, 67 pairs over a pinned, seeded
corpus) and scoring/gate code (`app/eval/`, `scripts/run_eval.py`) that has **never been run**: no baseline, no CI gate, so nothing measures
whether an answer is good -- **plus two pieces pulled forward because each fixed an observed
defect rather than moved a metric:**

- `app/retrieval/document_scope.py` -- naming a filename or `doc_id` in an `/ask` question
  scopes retrieval to that document.
- `app/generation/intent_router.py` (Phase 2.0) -- classifies every question into
  `metadata`/`factual`/`aggregate`/`out_of_scope` before `/ask` decides whether to retrieve at
  all. See "Intent routing" below.

## Producer/consumer split

`POST /v1/documents` returns **202** and enqueues; the `worker` service ingests. Two rules
hold this together, and both fail quietly if broken:

- **The api must not import the ingestion stack.** `app/worker/app.py` carries no
  `import_paths` and defers by task *name* so it never imports `tasks.py` (which pulls
  Docling). Adding a convenient `from app.ingestion...` to a router or to `formats.py` costs
  ~2s of startup and ~157MB per api process and breaks nothing visibly.
  `tests/unit/test_upload_formats.py` pins it. `app/ingestion/formats.py` therefore keeps a
  *pinned* extension list, drift-checked against Docling in that same test.
- **The worker CLI points at `app.worker.tasks.app`, not `app.worker.app.app`.** Importing
  `tasks.py` is what registers the task. Point it at `app.py` and the worker connects fine,
  then rejects every job as unknown -- which reads as a queueing bug.

Status lives on `DocumentRecord.status` (`pending`/`processing`/`ingested`/`failed`). The task
owns `processing`/`failed`; `ingest_document` owns the terminal `ingested` write, because
Streamlit calls it directly and bypasses the queue entirely.

## Intent routing (Epic 2 Phase 2.0)

`/ask` classifies every question into `metadata`/`factual`/`aggregate`/`out_of_scope`
(`app/generation/intent_router.py`, Haiku via structured output) before deciding whether to
retrieve at all -- see `docs/EPIC_2_PLAN.md` Phase 2.0 for the production defect this fixes
(a metadata question answered from whatever chunk happened to be nearest in embedding space).
Two things not to undo:

- **Only `factual` may reach `AnswerService`.** `metadata` answers from the document registry,
  and `out_of_scope`/the not-yet-built `aggregate` refuse -- all three exist specifically so a
  question that isn't answerable from document *content* never gets an answer grounded in
  retrieval anyway. Routing a new intent, or a misclassified edge case, through the factual
  pipeline "to be safe" silently reintroduces the defect Phase 2.0 exists to fix.
- **A test that reaches `ask()`'s handler body must stub `classify_intent`.** Left unstubbed it
  calls the real Anthropic API, which this sandbox and CI have no key for, so a test written
  before this landed fails with an authentication error that has nothing to do with what it
  actually checks -- this broke five existing tests in `test_api_contract.py` the day this
  shipped. `_factual_intent` there is the stub to reuse; `tests/unit/test_intent_routing.py` is
  where the classifier's own routing is tested.

## Docs, and which one to write in

**Read `docs/MEMORY.md` first in a new session.** It holds what this file deliberately does not:
where the work actually is, the user's standing directives, open questions, measurements
already taken, and a session log. Nothing else carries that across sessions. **Update it at
the end of any session that changed something** -- the protocol is at the top of the file.

- `README.md` -- the system as it is.
- `CHANGELOG.md` -- what a *user* would notice changed, and what breaks on upgrade. Keep it to
  observable behaviour: routes, response fields, env vars, defaults, removals. The reasoning
  belongs in `docs/MEMORY.md`; if an entry needs a paragraph of "because", it is in the wrong
  file. `.claude/skills/changelog` has the conventions.
- `docs/PATTERNS.md` -- the recurring shapes and the failure each one prevents. Also lists what is
  deliberately *absent*, so a reviewer doesn't "fix" it.
- `docs/TECHNICAL_DECISIONS.md` -- why each choice, and what was rejected. Update this when a
  decision changes, **not** the plan.
- `docs/EPIC_*_PLAN.md` -- what is planned, in order.
- `docs/IDEAS.md` -- the parking lot: anything that might be worth doing but isn't scheduled,
  plus a *considered and rejected* table so dead ideas don't come back. Add freely; an idea
  that graduates moves into an epic plan and is deleted from there.
- `docs/IMPLEMENTATION_PLAN.md` -- the original plan, kept as history and outdated on purpose.
- `docs/upload-path.html` -- the upload path traced file by file, in *execution order*, with the
  process each step runs in and the failure each guard exists for. Open it in a browser; GitHub
  will not render it. It exists because the ordering and the process boundaries are the part nobody
  can reconstruct from `README.md` (which describes the system as a shape) or `PATTERNS.md` (which
  describes recurring shapes, not one sequence). **It is a snapshot, dated in its own header, and it
  is the file most likely to rot** -- so when the write path changes, either update it in the same
  commit or delete it. A stale execution trace is worse than none, because it reads as authoritative.

A durable imperative rule goes *here*. Current state goes in `docs/MEMORY.md`. Mixing them buries
the rules in changelog.

**The repo root `../CLAUDE.md` holds the general rules** -- the 15 numbered coding rules, the
document-set split above, the working agreements on secrets, lockfiles, and the gate, and the
delegation rule for subagents. It is loaded alongside this file, so don't restate it here. What
belongs *here* is anything true of only this project: the failure contracts below and in
`.claude/rules/` are the point, because each names a specific file and a specific way that file
fails.

**A new failure contract goes in the `.claude/rules/` file whose `paths:` cover where the
violation would be written** (not merely where the guarded code lives). Only a contract that
can be broken from anywhere -- a secret, an id helper, the tenant source -- belongs in this
file.

## Subagents and skills

Six read-only subagents in `.claude/agents/`, named by task: sweeps (`doc-consistency`,
`route-audit`, `candidate-triage`) and per-change checks (`contract-review`, `test-gaps`,
`design-review`). **No coder agent, deliberately.** The four that have `Bash` run it through
`.claude/hooks/readonly-bash.py`, an allowlist that blocks writes, the suite, lint and services --
keep that hook on any agent given `Bash`, or "read-only" is only an instruction. Our skills:
`verify` (the gate), `add-endpoint`, `run-stack`, `changelog`; the rest are vendored at pinned
commits (`.claude/skills/VENDORED.md`) or come from plugins toggled in `.claude/settings.json`
(qdrant on; `llm-application-dev` off, because its hubs and all-tools agents contradict the above).
Why each exists, what each vendored skill is for, and the hub-exclusion rule are in
`.claude/references/agents-and-skills.md` -- read it before adding, removing or reaching past one.

## Verification gate

Install the hooks once so this isn't memory-dependent:

    cd portfolio && uv run pre-commit install -c .pre-commit-config.yaml

The `-c` is required (monorepo: git's hooks are at the root, the config lives here). Hooks are
`repo: local` calling `uv run`, so tool versions come from `uv.lock` rather than pre-commit's own
pins -- don't switch them to `astral-sh/ruff-pre-commit`, which reintroduces exactly that drift.
Python hooks are scoped `^portfolio/`; unscoped, pre-commit hands ruff the sibling projects' files.


All four before pushing. `ty.toml` sets `error-on-warning`, so a warning fails:

    uv run ruff check . && uv run ruff format --check .
    uv run ty check
    uv run pytest tests/unit
    cd .docker && docker compose config    # after any compose/Dockerfile edit

**Qdrant's filtering is covered; its network path is not.**
`tests/unit/test_qdrant_filtering.py` runs `_build_filter` through `qdrant_client`'s in-memory
engine with fake embeddings, so tenant isolation, the version filter and the prune selector are
proved by execution, in CI, with no server and no API keys. What remains untested is the real client
over the wire -- which is where the point-ID constraint escaped to production -- so don't say
"Qdrant is tested" without that qualifier.

Six suites hit a real Postgres or Redis and *skip* when unreachable -- auth-touch, rate-limit,
worker/registry, key-management, migrations and the `create_tenant` CLI -- so a green local run may
have tested far less than it looks (70 tests' worth, counted 2026-08-06). CI provides both services
and asserts none of the six skipped. It asserted three for a while, which let two of them skip in CI
silently.

## Never

- **Never commit `.env`.** It holds a real LangSmith API key. `.env.example` stays a
  template with placeholders only -- no real secrets, ever.
- **`uv.lock` is committed, and `--locked` is used everywhere** (Dockerfile, CI). It was
  gitignored, which this file previously recorded as deliberate; that was reversed because it
  made builds non-reproducible -- the image re-resolved at build time, so CI could test a
  dependency set nobody deployed, and a stale local venv had nothing to sync against. After
  editing `pyproject.toml`, run `uv lock` and commit the result.
  **`--locked`, not `--frozen`** -- verified, because the names suggest the opposite of what they
  do: `--frozen` uses the lock without checking it, so a dependency added and not re-locked is
  silently omitted and fails at runtime as an ImportError. Only `--locked` errors with "the
  lockfile needs to be updated".

## Failure contracts

Things that look correct and aren't:

- **Postgres is the only database engine.** No SQLite anywhere -- not for tests, not for
  Epic 3's checkpointer or incoming queue. `test_stored_timestamps_come_back_timezone_aware`
  pins the reason (a Postgres-only datetime guarantee `auth/service.py` relies on); the full
  story, plus the FK-enforcement bug a SQLite fixture also hid, is in
  `docs/TECHNICAL_DECISIONS.md` § Database.

## Config invariants

- **`requires-python` is `>=3.13`**, while Docker and CI run 3.14 -- deliberately. The
  floor is what the code requires; nothing requires 3.14 since `app/ids.py` took over
  `uuid7` with an RFC 9562 fallback. **Never call `uuid.uuid7()` directly** -- it raises
  `AttributeError` on 3.13 and the floor permits 3.13. Use `app.ids.new_id()`.
  This matters locally: on a 3.14 *pre-release* pydantic fails to build models
  (`_eval_type() got an unexpected keyword argument 'prefer_fwd_module'`), so a 3.14-floored
  project could not run its own suite. **`.python-version` pins local dev at 3.13** so
  `uv venv` lands there without a flag; keep it, and keep it out of the image
  (`.dockerignore`), because `python:3.14-slim` has no 3.13 and `UV_PYTHON_DOWNLOADS=0`
  forbids fetching one. CI overrides the pin per matrix leg and then asserts the interpreter
  it actually got -- a pin that silently won would make the 3.14 leg a second 3.13 run.

## The tenant boundary

`tenant_id` is the *only* thing scoping retrieval, and a wrong filter returns results
rather than raising -- it fails silently, as cross-tenant data access.

- It must come from `api/deps.py::current_tenant` (a verified API key) and nowhere else.
  Never from a request body, query string, or form field. `AskRequest` sets
  `extra="forbid"` so a client trying to smuggle one gets a 422 instead of being ignored.
- `streamlit_app/Home.py` calls the pipeline **in process**, so the FastAPI dependency
  never runs for it. It authenticates via `auth.service.resolve_tenant` instead -- one
  auth implementation, not two. It must never mint its own tenant id.
- **There is no shared tenant, and do not reintroduce one.** A `GLOBAL_TENANT = "global"` used
  to tag a curated corpus readable by everyone, which meant `_build_filter` matched
  `MatchAny([global, caller])` and the honest description of isolation was "your documents *plus
  global*". Removed 2026-08-03. The filter now matches **one** tenant via `MatchValue`, and it is
  deliberately not a single-element list: a list invites a second element, which is exactly the
  leak this boundary exists to stop.
- **`tenant_id` is required everywhere it appears, with no default.** `_build_filter` raises on an
  empty one, and `Chunk`, `chunk_document`, `ingest_document`, `Retriever.retrieve` and
  `AnswerService.answer` all take it positionally-or-by-keyword with no fallback. The old default
  was `GLOBAL_TENANT`; with the corpus gone, any default at all would silently file one tenant's
  data under another name, and retrieval would return it rather than error.
- `tests/unit/test_tenant_scoping.py` asserts on the built filter directly, which is why
  it catches leaks without a live Qdrant. It asserts the permitted set **exactly** -- the weaker
  `a in / b not in` form passed for months while the filter also admitted `global`.

## Path-scoped contracts

Most failure contracts live in `.claude/rules/`, each loaded only when a file it guards is read.
They are as binding as this file. Don't rely on a subagent loading them; point any review brief at
them explicitly.

- `ingestion-and-retrieval.md` -- Postgres decides what is searchable, `upsert` never deletes,
  `stage_`/`save_document_record`, upload paths, figure ids and captions, Qdrant ids/filters/async,
  chunk order, Docling, payload indexes.
- `database.md` -- SQLModel datetimes, Alembic, `migrations/env.py`, the advisory lock,
  procrastinate's schema, test fixtures, row-level security.
- `docker.md` -- compose env resolution, capabilities, postgres init/healthcheck/volume, `PORT`,
  timeouts.
- `config.md` -- CORS, the `POSTGRES_*` set, `SecretStr`.
- `health.md` -- liveness vs readiness, provider-credential checks.
- `rate-limiting.md` -- `limits` policy, fail-open, the edge limiter.
- `auth.md` -- empty scopes mean every scope; tests override `current_principal`.
