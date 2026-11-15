# Epic 5 — Newsletter digest agent: implementation plan

**Goal:** a daily agent that turns the programming newsletters in a tenant's Gmail into a ranked,
cited digest of article summaries, which a person approves before it is sent.

**Nothing here is built.** This file is the plan only (written 2026-11-15). The epic as first
stated is kept at the bottom, verbatim, as the original requirement. Everything above it records
where that requirement meets the code that actually exists, and which parts of it would have been
built wrong if taken literally.

**Depends on:** Epic 1 (ingestion, retrieval: built), Epic 2 (eval harness: built, `app/eval/`),
Epic 3 (agentic patterns: **not built**, see § Ordering).

## Decisions taken (user, 2026-11-15)

| Decision | Choice | Why |
|---|---|---|
| Scope of this session | Plan only | Same start as Epics 2-4. The epic depends on an agent layer that doesn't exist yet. |
| Who owns newsletter data | **A Gmail connector belongs to a tenant.** Its messages, articles, chunks and digests are filed under that tenant's `tenant_id`, like an upload | There is no shared tenant and there won't be one (`CLAUDE.md` § The tenant boundary). That also settles Epic 3's open question for this epic only: per-tenant, option (b). |
| Gmail auth | **OAuth refresh token, per connector** | A cron run has no browser. A service account with domain-wide delegation only works for Workspace domains, not a personal `@gmail.com`. |

Two consequences of "connector per tenant" that the original epic didn't expect:

- **The refresh token is per-tenant data, not configuration.** It can't go in `.env` or
  `Settings`, the way `ANTHROPIC_API_KEY` does. It is a row in Postgres, encrypted at rest, under
  row-level security. See Phase 5.0.
- **The label list, the interest profile and the delivery address are per connector too.** "Config
  driven" (5.1) means a column on the connector row, not an env var.

## Ordering: build this before Epic 3, not after

The epic lists Epic 3 as a dependency. The parts it actually needs from Epic 3 are a LangGraph
graph, `PostgresSaver`, and an `interrupt` that a human resumes. None of them exist
(`docs/EPIC_3_PLAN.md`: "Nothing here is built"). This epic's graph is linear, with one
interrupt and no subagents, which makes it the simpler place to build that groundwork. Epic 3's
orchestrator, MCP scoping and episodic memory are harder, and none of them is needed here.

**Recommendation: build Epic 5 first and let Epic 3 reuse what it lands.** That covers the
checkpointer bootstrap, typed resume, the per-write idempotency keys and the structured-output
helper (below). Epic 3's own plan already asks for these four. The user has to agree to this,
since it reverses the epic's stated dependency. If they don't, everything from Phase 5.4 on waits
for Epic 3.

Epic 3's first step applies here too. Re-vendor `langgraph-fundamentals`, `langgraph-persistence`
and `langgraph-human-in-the-loop` from `langchain-ai/langchain-skills` before the graph is
written (`.claude/skills/VENDORED.md`).

## What the original epic gets wrong, or leaves out

Each of these was checked against the code or the dependency (root rule 13). None comes from
memory.

| Original epic says | Problem | Plan |
|---|---|---|
| "PostgresSaver: track processed message/link IDs (idempotent daily runs)" | A checkpointer records *execution*: which node ran and what state it left. It is not a dedupe store. A new run is a new thread with an empty checkpoint, so yesterday's links are invisible to it. Same point as `EPIC_3_PLAN.md`: "Checkpoints recover *execution*; they don't make side effects idempotent." | Dedupe goes in our own tables with unique constraints: `(tenant_id, gmail_message_id)` and `(tenant_id, canonical_url)`. The checkpointer only lets a run resume after a crash or an interrupt. |
| "fetch last-24h threads" | A run that fails or is skipped for a day loses that day's mail for good. A fixed window also overlaps or gaps whenever cron drifts. | A **watermark** on the connector: the highest Gmail `internalDate` that was fully processed. Each run takes `after:watermark`, and the message-id unique constraint absorbs the overlap. The watermark moves forward only after a successful run. |
| "Dedupe links (normalize URLs, strip UTM)" | Most newsletter links are **click-tracking redirects** (`links.<newsletter>.com/CL0/...`). Two newsletters that link the same article hand you two different tracker URLs. Normalizing the tracker URL dedupes nothing. | Follow redirects first, then normalize the **final** URL: strip `utm_*`/`ref`/`mc_*`, lowercase the host, drop the fragment and trailing slash. Following a tracker counts as a "click" on the newsletter's side. That is accepted, and recorded here so it isn't a surprise. |
| "Async fetch with asyncio.gather" of article URLs | **SSRF.** The URLs come from email bodies, which anyone can send to the inbox. The worker container can reach `postgres`, `redis` and `qdrant` on the compose network, plus anything on the host network. A link to `http://qdrant:6333/collections` or `169.254.169.254` would be fetched and could then be summarized into the digest. | The fetcher resolves DNS itself, refuses private, loopback, link-local and compose-service addresses, and **checks again after every redirect hop**, because a public URL can redirect to a private one. It allows only `http`/`https` with a capped response size, capped hop count, `text/html` only, and a total timeout. Bounded concurrency (a semaphore), not an unbounded `gather`. This is the one new failure contract this epic certainly needs. It goes in a new `.claude/rules/` file once the fetcher exists. |
| "Readability-style content extraction" | Docling's HTML backend (the path `ingest_document` uses) converts the **whole page**, including nav, cookie banners and "related posts". It does no main-content extraction. | `trafilatura` extracts the main text before ingestion (new dependency, absent from `uv.lock` today). The extracted text is written as a `.md` file and ingested through `ingest_document`. Don't build a second ingestion path (`EPIC_3_PLAN.md`: that function owns the terminal `ingested` write and the `EmptyDocumentError` guard). |
| "skip paywalled/failed pages gracefully" | "Gracefully" could mean summarizing the newsletter's own one-line blurb as if it were the article. That is root rule 11: an answer from the wrong material, indistinguishable at the point of use. | A failed or paywalled fetch is stored with `status=failed` and a reason. It appears in the digest under **"Couldn't fetch"** with the newsletter's blurb quoted and labelled as the blurb. It is never passed to the summarizer. This also meets the DoD line "failed fetches logged, not dropped silently". |
| "Chunk + embed into existing vector store" | **The scale target.** It is 10k tenants × 10 documents (`docs/TECHNICAL_DECISIONS.md` § Scale target). At ~30 articles a day, one connector adds ~11,000 documents a year, three orders of magnitude over the per-tenant budget. Article rows would also flood the metadata intent ("list my documents"). | **Open question 1** below. The plan assumes a retention window (default 30 days) and a `source` column so `/ask`'s document listing can tell articles from uploads. |
| "Relevance ranking against a user interest profile" | Doesn't say how. An LLM ranking call per run is a judgment-shaped answer to a deterministic question (root rule 5). | Rank by cosine similarity between the article embedding and the embedding of the connector's interest-profile text. Both come from the Voyage embeddings already being written, so ranking costs no model call. The top 3 are flagged. Topic classification *is* a judgment call and stays a model call. |
| "interrupt before publish" + "runs daily unattended" | The two conflict. An unattended run that stops for approval stays stopped until a person shows up. | "Unattended" means: triggered on schedule, and runs through `rank` with no intervention. `review` waits. **Open question 2** decides what happens if nobody approves by the next run. |
| "Eval set from Gmail labels as ground truth for topic classification" | A label sits on a **newsletter**, not on an article. One issue of an AI newsletter links infra, frontend and funding news, so "label = topic of every linked article" makes a noisy ground truth. ≥90% accuracy against noisy labels mostly measures how noisy the labels are. Also, the repo is public, and the set comes from the user's own mailbox. | Use labels to *seed* candidates, then hand-correct a fixed set of 100-200 articles once. The committed set holds `canonical_url`, title and corrected topic only: no email content, no article text, no sender addresses. The ≥90% target applies to the corrected set. |
| "Summary faithfulness check (LLM-as-judge vs. fetched content)" in the Epic 2 harness | The CI gate replays recorded provider calls, and a cassette quotes its input. Article text is third-party copyright. This is the same problem as `MEMORY.md` open question 11, which was settled for the paper corpus by swapping to CC BY papers. Newsletter articles can't be swapped. | Faithfulness runs **live, outside CI**, as a LangSmith experiment (the existing evals decision, `docs/TECHNICAL_DECISIONS.md` § Evals). CI gates only topic classification, whose inputs (title plus the first N characters) are short. Even those are quoted text, so **open question 4**. |
| (not mentioned) Gmail OAuth app status | **Verified 2026-11-15 against Google's OAuth docs:** a project whose consent screen is in "Testing" gets "a refresh token expiring in 7 days". A daily unattended run built on a Testing-mode app dies within a week, every week. `gmail.readonly` is a **restricted** scope: making the app public brings Google verification plus a yearly CASA security assessment, because mail passes through our server. A password change also revokes a token that holds Gmail scopes. | **Open question 3.** It decides whether "connector per tenant" means *the owner's own mailbox* (an unverified production-status app, capped at 100 users, which the owner clicks through once) or *any customer's mailbox* (verification plus CASA, a real cost and lead time). It also needs a `connector.status = needs_reauth` path, so an expired token stops the run loudly instead of producing an empty digest. |

## Phases

Each phase lists its **done** check (root rule 4). Phases 5.0-5.3 have no LangGraph in them: they are
plain async functions with unit tests. The graph in 5.4 wires them together. That keeps the
deterministic parts testable without a checkpointer.

### 5.0 Connector and storage (prerequisite)

- `GmailConnector` table: `tenant_id`, `email_address`, `labels` (list), `interest_profile`
  (text), `deliver_to` (defaults to `email_address`), encrypted `refresh_token`, `watermark`
  (Gmail `internalDate` ms, nullable), `status` (`active`/`needs_reauth`/`disabled`), datetimes
  per `.claude/rules/database.md` (explicit `sa_column`, runtime `datetime` import).
  - Rule 8: `watermark NULL` means "first run". It takes the last 24h, not all of history: a
    first run over a 10-year mailbox is thousands of fetches.
  - Rule 8, the other direction: an empty `labels` list must **not** mean "all mail". For an
    inbox reader, "unrestricted" is the privilege escalation. An empty list is refused at
    write time and at run time.
- `NewsletterMessage(tenant_id, gmail_message_id, connector_id, internal_date, processed_at)`
  with unique `(tenant_id, gmail_message_id)`.
- `NewsletterArticle(tenant_id, canonical_url, title, status, failure_reason, doc_id, topic,
  summary, score, first_seen_message_id, ...)` with unique `(tenant_id, canonical_url)`.
  `doc_id` points into the existing `DocumentRecord`.
- `DigestRun(tenant_id, run_date, thread_id, status, ...)` with unique `(tenant_id, run_date)`.
  An approval API looks up a run by `(tenant_id, thread_id)` **in the query** (root rule 10),
  never by `thread_id` with a check afterwards.
- `DocumentRecord.source` (nullable). `NULL` reads as `upload` for every existing row (rule 8);
  `newsletter` is new.
- **Encryption:** `cryptography`'s Fernet (absent from `uv.lock` today, so `uv lock` and commit),
  with the key in `Settings` as a `SecretStr`. Missing key while any connector exists fails at
  boot (root rule 9: configuration fails fast).
- **RLS** on all four new tables, the same `app.tenant_id` policy as `documentrecord`, queried
  through `get_session()` as `app_db_user` (`.claude/rules/database.md` § Row-level security).
- One Alembic revision. **`migrations/env.py`'s `include_object` must also exclude the
  checkpointer's tables** (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
  `checkpoint_migrations`, checked in `langgraph-checkpoint-postgres` 3.1.1's `base.py`).
  Otherwise autogenerate emits `drop_table` for them, the same way it did for procrastinate's.

**Done:** migration applies on an empty database and on the current one, `alembic check` is
clean, and an RLS test (real Postgres, as `app_db_user`) shows tenant B reads zero connectors,
articles and runs belonging to tenant A.

### 5.1 Email ingestion

- Gmail REST over `httpx` (already declared). `users.messages.list?q=label:X after:<watermark>`
  per label, then `messages.get?format=full`. `google-api-python-client` is **not** needed for
  three endpoints, and it is absent from the lock today. The one-time consent flow needs only
  the token endpoint. Decide by resolving, not assuming, if the token handling turns out bigger
  than expected.
- Token refresh on every run. `invalid_grant` sets `status=needs_reauth`, logs loudly, ends the
  run and skips the digest. It must not produce an empty "nothing today" digest (rule 11).
- HTML → links with `beautifulsoup4` (in the lock already, 4.15.0). Filters for
  sponsor/unsubscribe/social links are a deterministic rule list (host and anchor-text patterns
  such as `unsubscribe`, `view in browser`, `twitter.com/intent`, `sponsor`), not a model call
  (rule 5). Keep the anchor text: it becomes the "Couldn't fetch" blurb and a fallback title.
- Resolve redirects, then canonicalize, then dedupe against `NewsletterArticle`.

**Done:** unit tests on recorded HTML from 3+ real newsletter formats, with expected link sets
checked by hand. Tracker URLs that redirect to the same article dedupe to one row.

### 5.2 Article fetch and processing

- The SSRF-safe fetcher above, with `tenacity` retries (in the lock, 9.1.4) on connect errors,
  timeouts and 5xx only. A 4xx and a non-HTML response are final, not retried.
- `trafilatura` main-content extraction. Below a minimum length (paywall teaser, JS-only page)
  the article becomes `status=failed`, `reason=too_short`, and is not ingested
  (`EmptyDocumentError`'s reasoning).
- Write `.md`, create the `DocumentRecord` (`source=newsletter`) and ingest via
  `ingest_document`. Defer through procrastinate per article, so one slow page doesn't hold the
  run. The existing `defer_document_ingest` already commits the row and its job together.
- **Prompt injection:** article text will reach the summarizer. Its output is a fixed schema (5.3),
  which caps the damage at "a misleading summary in your own digest". The digest renderer
  escapes every model-produced string, so an article can't inject HTML into the email.

**Done:** fetcher tests prove a redirect from a public host to `127.0.0.1`, `10.0.0.0/8`,
`169.254.169.254` and a compose service name is refused at the hop, not after the body is read.
Each guard is mutation-checked: delete it and a test fails (rule 15).

### 5.3 Summarize and rank

- One structured-output call per article: `title`, `topic` (`AI/LLMs`, `Architecture`,
  `Backend`, `Frontend`, `Infra`, `Other`), a 1-2 sentence `summary`. **The `url` is not a model
  output.** It is copied from the row, so a summary can't cite the wrong source. "Every summary
  links to its source" then holds by construction, not by prompt.
- Build this on one structured-output helper shared with `intent_router.py`. `EPIC_3_PLAN.md`
  asks for the same thing for its injection guard. Haiku (`intent_router_model`'s reasoning: a
  cheap, bounded judgment).
- Model-call cache keyed on `sha256(content + prompt_version + model_id)`. Without
  `prompt_version`, a prompt edit serves stale summaries forever (`EPIC_3_PLAN.md`). The same
  article arriving from two newsletters is already deduped. The cache covers a re-run after a
  crash.
- Rank: cosine(article embedding, profile embedding). Top 3 flagged. Ties broken by first-seen
  time, so the order is reproducible.

**Done:** a schema-violating model response is a recorded failure for that article, not a crash
of the run and not a blank summary. Ranking is a pure function with unit tests.

### 5.4 The agent graph

- Nodes: `fetch_emails → extract_links → fetch_articles → summarize → rank → review → publish`.
  Each node calls the 5.1-5.3 functions. State holds **ids**, not article bodies, so a
  checkpoint doesn't store copyrighted page text on every step.
- `AsyncPostgresSaver`, thread id `digest:{tenant_id}:{run_date}`, plus the `DigestRun` row
  that actually authorizes access to it.
  - **`setup()` can't run inside `init_db`'s transaction.** Checked in 3.1.1: its migrations
    include `CREATE INDEX CONCURRENTLY`, which Postgres refuses inside a transaction block, and
    `init_db` holds a *transaction*-scoped advisory lock (`pg_advisory_xact_lock`). It needs its
    own autocommit connection, under a separate lock, so concurrent boots don't race its own
    check-then-create on `checkpoint_migrations`. This is the same race
    `.claude/rules/database.md` records for procrastinate.
- `review` calls `interrupt()` with the ranked list. The human resumes with approve /
  drop-items / edit-summary. **Typed resume needs LangGraph ≥ 1.2.12.** Confirmed 2026-11-15:
  the locked 1.2.10's signature is `interrupt(value: Any)`, with no `response_schema`. The
  latest is 1.2.22. Bump, re-lock, and pass a Pydantic model (not a JSON-schema dict, which
  `EPIC_3_PLAN.md` found is passed through unvalidated).
- `publish` is the only external side effect. Its idempotency key is
  `(tenant_id, run_date, "publish")`, stored in Postgres *before* the send call and marked sent
  after. A replay after a crash between send and checkpoint then doesn't email twice. Gmail
  has no idempotency header, so this table is the only guard.
- **Schedule: a procrastinate periodic task**, not system cron or a new scheduler.
  `@app.periodic(cron=...)` exists in the locked 3.9.0, and its
  `procrastinate_periodic_defers` table has a unique `(task_name, periodic_id,
  defer_timestamp)`. Several worker processes therefore defer one job per tick, not one each.
  The periodic task fans out one job per active connector, keyed by `(tenant_id, run_date)`, so
  a second delivery of the same job finds the `DigestRun` row and resumes rather than starting
  over. The task name must not cause the api to import the graph (`CLAUDE.md` §
  Producer/consumer split).

**Done:** the `EPIC_3_PLAN.md` acceptance cases that apply: worker killed mid-node; killed
between the send and its checkpoint; the same job delivered twice; an invalid approval and then a
valid one. Each ends with exactly one digest sent and no duplicate article rows, counted from
the database, not inferred from logs.

### 5.5 Delivery

- Render Markdown, and HTML from it, with Jinja2 (in the lock, 3.1.6, `autoescape=True`).
  Sections: Top 3, by topic, Couldn't fetch. Each item: title, summary, source link, and which
  newsletter(s) carried it.
- Send through Gmail `users.messages.send` to `deliver_to`. This needs the `gmail.send` scope
  in addition to `gmail.readonly`. Both are requested at consent; adding one later forces
  every connector to re-consent.
- Substack/blog draft: **parked in `docs/IDEAS.md`**, not planned. Substack has no public
  posting API, and "optional" work in a plan gets built half-way.

**Done:** a golden rendered digest from fixture data, with escaping tested by an article title
that contains `<script>`.

### 5.6 Evaluation and observability

- LangSmith tracing is already wired (`config.py` bridges the env). Tag runs with `tenant_id`
  and `run_date`, and record per-stage counts (messages, links, fetched, failed, summarized) on
  the `DigestRun` row as well. A trace has retention limits, and the row is what a "why was
  yesterday empty?" question gets answered from.
- Topic classification: the hand-corrected set (above), a LangSmith dataset, and a committed
  baseline in the Epic 2 gate's style (`app/eval/gate.py`). Target ≥90%.
- Faithfulness: an LLM judge on `eval_judge_model`, not the summarizer's model (`judges.py`'s
  reason), run live against fetched content. Not in CI (see the table above).

**Done:** the accuracy number is measured once and recorded in `docs/MEMORY.md` § Measurements
taken, with the label noise rate found during correction recorded next to it.

## Open questions (need the user's call before the phase that names them)

1. **Retention and the scale budget (blocks 5.2).** Newsletter articles arrive ~1,000× faster
   than the per-tenant document budget allows. Options: (a) keep 30 days in Qdrant and prune
   older generations, keeping the `NewsletterArticle` row (title, summary, url) forever; (b)
   don't embed at all, rank on an embedding computed and thrown away; (c) embed, and revise the
   scale target. (a) is the recommendation. (b) loses "ask about last week's articles". (c)
   needs a measurement this project doesn't have yet (MEMORY open question 4: no
   tenant-filtered query has been measured at 1M points).
2. **No approval by the next run (blocks 5.4).** Options: expire the pending run unsent (its
   articles roll into the next digest), auto-publish after N hours, or send it marked
   "unreviewed". Expiry is the recommendation. Auto-publish turns the approval step into
   decoration.
3. **Whose mailbox (blocks 5.0).** The owner's own mailbox only: an unverified app in
   *production* status, ≤100 users, the owner accepts Google's warning once, and the refresh
   token stops expiring weekly. That route is **unverified** and has to be confirmed against
   Google's current policy before it's relied on. Or any customer's: Google verification plus
   CASA, with yearly renewal. The monetization directive leans toward the second, and the cost
   and lead time say do the first now.
4. **Can a classification eval cassette be committed (blocks 5.6's CI half)?** It quotes
   article titles and leading text, so it's smaller than the paper case but the same question.
   Options: title-only inputs (less accurate classification, fully committable), or no CI gate
   for this epic and a live LangSmith experiment only.

## Not doing

- **A second ingestion path** for articles. They go through `ingest_document`.
- **A shared newsletter corpus across tenants**, even when two tenants subscribe to the same
  newsletter. It would be the shared tenant this project removed on purpose.
- **The Gmail MCP connector as the runtime.** It belongs to an interactive Claude session, not
  to an unattended worker.
- **A model call for link filtering, URL canonicalization or ranking** (rule 5).

---

## The epic as first stated (2026-11-15, verbatim)

**Goal:** Daily agent that turns programming newsletters in Gmail into a ranked, cited digest of
article summaries.
**Depends on:** Epic 1 (ingestion, retrieval), Epic 2 (eval harness), Epic 3 (agentic patterns)

### 5.1 Email ingestion
- Gmail API connector: fetch last-24h threads by label list (config-driven)
- HTML → article link extraction; filter sponsor/unsubscribe/social links
- Dedupe links across newsletters (normalize URLs, strip UTM)

### 5.2 Article fetch & processing
- Async fetch with `asyncio.gather` + timeouts; tenacity retries
- Readability-style content extraction; skip paywalled/failed pages gracefully
- Chunk + embed into existing vector store (new `source=newsletter` metadata)

### 5.3 Summarize & rank
- Structured output per article: title, topic, 1–2 sentence summary, URL
- Topic classification (AI/LLMs, Architecture, Backend, Frontend, Infra, Other)
- Relevance ranking against a user interest profile; top 3 flagged

### 5.4 Agent graph (LangGraph)
- Nodes: fetch_emails → extract_links → fetch_articles → summarize → rank → review → publish
- PostgresSaver: track processed message/link IDs (idempotent daily runs)
- `interrupt` before publish: human approves/edits top items
- Scheduled trigger (cron) for daily run

### 5.5 Delivery
- Render digest as Markdown/HTML email; send to self
- Optional: publish to Substack/blog draft

### 5.6 Evaluation & observability
- LangSmith tracing per run (cost, latency, failures per stage)
- Eval set from Gmail labels as ground truth for topic classification
- Summary faithfulness check (LLM-as-judge vs. fetched content)
- Regression suite added to Epic 2 harness

### Definition of Done
- Runs daily unattended, no duplicate items across runs
- ≥90% topic-classification accuracy on label-derived eval set
- Every summary links to its source; failed fetches logged, not dropped silently
- README section with architecture diagram + sample digest
