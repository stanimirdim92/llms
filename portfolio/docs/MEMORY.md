# Memory

State that does not survive a new session otherwise. Read this first; update it last.

**What belongs here vs. the other docs** — the split is what keeps any of them worth reading:

| File | Holds | Changes when |
|---|---|---|
| `CLAUDE.md` | Rules and invariants. Imperative, timeless. | A new way to break the system is found. |
| `docs/PATTERNS.md` | Recurring shapes and the failures they prevent. | The architecture changes. |
| `docs/TECHNICAL_DECISIONS.md` | Why each technology, and what was rejected. | A decision is revisited. |
| `docs/EPIC_*_PLAN.md` | What is planned and in what order. | Scope or sequencing moves. |
| `docs/IDEAS.md` | The parking lot — unscheduled ideas, and rejected ones with their reason. | Any time something occurs to you. |
| **`docs/MEMORY.md`** (this file) | **Where we actually are.** Standing directives, open questions, session log, measurements taken. | Every working session. |

If a fact is durable and imperative it belongs in `CLAUDE.md`, not here — this file is the
mutable part, and mixing the two means the rules get buried in changelog.

---

## Update protocol

Without this, the file rots into a stale snapshot that is worse than nothing, because it is
believed.

**At the end of a session that changed anything:**

1. Add a dated entry under **Session log** — newest first. What changed, and *why*, in a few
   lines. Link the commit.
2. Move anything resolved out of **Open questions**; add anything newly opened.
3. Update **Current state** if a phase's status moved.
4. Record any real **measurement** taken — a number measured once and written down is worth
   more than the same number re-derived approximately three times.
5. If a new invariant was discovered, put it in `CLAUDE.md` and note here that you did.

**Keep the log pruned.** Entries older than a few months whose content has been absorbed into
`CLAUDE.md` / `docs/TECHNICAL_DECISIONS.md` should be deleted, not archived — the pointer to the
durable doc is the useful residue.

**Do not** write anything into this file you have not verified. An unverified claim recorded
here is read as established fact by the next session, which is exactly the failure the "fail
loud" rule exists to prevent.

---

## Standing directives

Decisions the user has made that persist across sessions. Do not re-litigate these; if one
looks wrong, say so once and proceed.

- **Scale target: 10,000 tenants × 10 documents = 100,000 documents**, on 8 vCPU / 16 GB.
  Revised up from 1k × 2. Every capacity claim should be checked against this number.
- **Postgres is the only database engine.** No SQLite anywhere — not for tests, not for Epic
  3's checkpointer.
- **Python floor is 3.13**; Docker and CI run 3.14. The floor is what the code requires.
  `.python-version` is tracked and pins local dev at 3.13, so plain `uv venv` is correct —
  pydantic fails to build models on 3.14 pre-releases. It is excluded from the Docker build
  context, and CI overrides it per job and then *asserts* the interpreter it actually got.
  Note that `portfolio/.gitignore` no longer carries a `!.python-version` negation (the user
  removed it); the file stays committed because gitignore does not apply to tracked files, but
  it would vanish silently if it were ever untracked.
- **Never commit `.env`.** It holds a real LangSmith API key, and **this repository is
  public** — a key that reaches a commit is disclosed the moment it is pushed, whether or not
  the commit is later reverted. `.env.example` stays placeholders only.
- **Commit and push directly to `main`, and only `main`** (explicit permission; overrides the
  default branch restriction). The `claude/detailed-plan-o6lubt` working branch was retired
  2026-08-02 -- this is a WIP app and mirroring every commit to a second branch bought
  nothing. The *remote* branch could not be deleted from the container (the session's git
  proxy refuses ref deletion); it points at the same commit as main and is the user's to
  remove in the GitHub UI.
- Streamlit retires when the React UI lands (Epic 4 Phase 6). Don't invest in it beyond parity.
- Commit-signing warnings from the stop hook are expected and were accepted — signing cannot
  work in this container. Don't re-raise.

---

## Current state

**Built and verified:**

- **Epic 1** — retrieve → rerank → generate with citations, multi-format ingestion (Docling),
  structure-aware chunking, Qdrant + Postgres registry, Streamlit UI, full Docker stack.
- **Epic 4 Phase 1** — API-key auth, tenant scoping. Keys hashed at rest (SHA-512), shown
  once, base62 + CRC32 format, 30-day default expiry from a 30/60/90/365/never menu, per-key
  scopes, and full CRUD at `/v1/keys` plus a Streamlit page.
- **Epic 4 Phase 2** — rate limiting, now bucketed **per key** rather than per tenant. Redis
  sliding window via `limits` (hand-rolled Lua until 2026-08-03), fails open.
- **Epic 4 Phase 3** — docs, health checks, CI.
- **Epic 4 Phase 5.1** — ingestion behind a procrastinate job queue. `POST /v1/documents`
  returns 202; document row and job commit in one transaction.
- **Explicit document scoping on `/ask`** — pulled forward out of Epic 2 because it fixed an
  observed defect rather than moving a metric. Naming a document by **filename or `doc_id`**
  scopes retrieval to it; an unowned identifier is a 404.

**Not built** — designs only, no code. Don't infer any of it from a plan's directory layout:

- **Epic 2** — the eval framework. Golden set, recall@k, parquet + DuckDB run storage, the CI
  regression gate, intent routing. This blocks most retrieval work: query expansion,
  decomposition, and corpus-level answering all change what retrieval returns, and adopting
  any of them without recall@k is a guess with a cost attached.
- **Epic 3** — the curation agent with human-in-the-loop.
- **Epic 4 Phase 4** — observability. The latency SLO check is buildable now; faithfulness
  alerting needs Epic 2's scores.
- **Epic 4 Phases 5.2–5.9** — user accounts, conversations, document delete, streaming `/ask`.
- **Epic 4 Phase 6** — React + TypeScript UI generated from the OpenAPI schema.

**Verified on real infrastructure:** `init_db` against live Postgres including the
advisory-lock path; the queued path end to end (`POST` → job row → worker → Qdrant →
`ingested`). **Still unverified:** the Qdrant client over the wire under concurrency, and the
nginx config's syntax (no nginx binary in the sandbox).

---

## Measurements taken

Numbers that were actually measured. Re-derive rather than trust if the system has changed
underneath them.

| What | Value | When / how |
|---|---|---|
| Cost of one `/ask` answer | **$0.017024** — 3,447 in + 1,013 out on `claude-sonnet-5` | 2026-08-01, from the LangSmith trace. Matches list price to the last digit at intro rates ($2/$10 per MTok, through 2026-08-31); **$0.025536 at standard $3/$15 from 2026-09-01**. |
| Output share of that cost | **60%**, from 23% of the tokens | Output is priced 5× input. Cost control means shorter answers, not smaller prompts. |
| Voyage cost per answer | **$0.00 billed** (~$0.0004 at list) | voyage-4 $0.06/1M and rerank-2.5 $0.05/1M, **first 200M tokens free on both** — pricing page fetched 2026-08-01. Query embed was 212 tokens. |
| Answer latency | 11.2 s | Same trace. |
| `max_tokens` headroom | **11 tokens of 1024** | `stop_reason: end_turn`, so it completed — but structured-output requests sit right against the ceiling. |
| Prompt caching viability | Not viable in current shape | Stable prefix is the 693-char system prompt (~200 tokens), under Sonnet 5's 1,024-token minimum. Chunks vary per question, so there is no larger shared prefix. |

- **slowapi vs the hand-rolled limiter** (2026-08-02, localhost Redis, steady state, best of
  five). Per-check latency is a wash: 0.32 ms sync, 0.36 ms async. Under concurrency the sync
  path blocks the event loop: 100 concurrent 21.4 ms vs 11.1 ms, 200 concurrent 65.5 ms vs
  18.5 ms. slowapi 0.1.10 has no async storage path at all -- it imports `limits.storage` and
  `limits.strategies`, the sync modules. Also: `uv add slowapi` unpinned does **not** error on
  our `redis>=8.0.0`; it silently resolves `limits==1.6` / `slowapi==0.1.6`. Only
  `limits[redis]>=5` reports unsatisfiable. Full write-up in `docs/TECHNICAL_DECISIONS.md`.
- **`limits` used directly is viable and was the thing worth evaluating** (2026-08-02).
  `RedisStorage("async+redis://...", implementation="redispy")` runs fully async on **redis-py
  8** -- the `<8.0.0` pin is on the *sync* extra only, and the redispy bridge wants
  `redis>=5.2.0` with no ceiling. Performance is a dead heat with ours (0.45/1.23/5.02/11.11 ms
  at 1/10/50/100 concurrent vs 0.36/1.20/5.09/11.05), **but** it raised
  `MaxConnectionsError` at 200 concurrent where ours completed in 18.5 ms, and `hit()` +
  `get_window_stats()` is two round trips where our script returns allowed/remaining/reset from
  one. **Kept ours on 2026-08-02, then adopted `limits` on 2026-08-03** — the user's call once
  the memory numbers below were on the table. Full accounting in
  `docs/TECHNICAL_DECISIONS.md`.
- **Redis cost per rate-limit key** (2026-08-03, `MEMORY USAGE` after 60 requests on one key).
  `limits` `SlidingWindowCounter` **120 bytes** (a string); `limits` `MovingWindow` 1464 (a
  list); the old hand-rolled ZSET 3120 (32-char uuid members). At 10k tenants × 2 scopes that
  is ~2.4 MB against ~62 MB. This 26× is what decided the swap; note more than half of it was
  the uuid member rather than the algorithm.
- **`limits` defaults `max_connections` to 100** (2026-08-03) and its pool raises
  `MaxConnectionsError` rather than queueing — which is the 200-concurrent ceiling recorded
  above, now explained rather than observed. Reproduced with both the moving window and the
  counter, so it belongs to the storage bridge, not the strategy. `redis_max_connections` in
  `Settings` overrides it.
- **`limits` retains a counter for 2× the window** (2026-08-03, measured 119999 ms for a 60 s
  window). Inherent to the algorithm: the current window's count must outlive its own window to
  be weighted as the next one's "previous".
- **`fastapi-limiter` 0.2.0** is the only other live async option (delegates to
  `pyrate-limiter` 4.x, redis-8 compatible). Rejected on specifics: its 429 is a bare
  `HTTPException(429)` with no `Retry-After` or `X-RateLimit-*` and `try_acquire_async` returns
  a bool so a callback cannot compute them, and its bucket key embeds the route's **index in
  `app.routes`**, so inserting a route renames every existing bucket.

---

## Open questions

Unresolved, and blocking or shaping something. Each needs a decision or a measurement, not
more discussion.

1. **Identity for Epic 4 Phase 5.2.** User accounts sit on top of the existing API-key tenant
   model, and the relationship between "tenant" and "user" hasn't been decided. Blocks 5.2
   onward.
2. **`processed_dir` disk footprint at 100k documents.** Still unmeasured — the attempt failed
   (Docling `partial_success`, 1/16 pages, fifteen timeouts on arXiv 2008.10896). Needs
   hardware that can finish a parse. Determines whether processed artefacts can stay on local
   disk at target scale.
3. **Payload index on `metadata.tenant_id`.** The vendored `qdrant-multitenancy` skill calls
   for a keyword index with `is_tenant=true`. Harmless at 6 documents; **required** at 100k
   (order 1M points, where an unindexed tenant filter degrades toward a scan). Not built.
4. ~~**Usage is not recorded anywhere.**~~ **Resolved 2026-08-03.** Every answer now logs
   `stop_reason`, `input_tokens` and `output_tokens` structurally, and `Answer.truncated` reaches
   `AskResponse` and the Streamlit page. What is still missing is `cost_usd` — the per-model price
   table Epic 2 Phase 2.2's parquet schema wants. Kept in the list rather than deleted so the
   half that shipped is not mistaken for the whole.
5. **Whole-document extraction.** "Fill this schema from document X" is not a similarity query
   — every field must be found, so ranking chunks against the schema text is the wrong
   primitive even when correctly scoped. Works today only because the test document is one
   chunk; on a longer document `rerank_top_n=5` would drop a field-bearing chunk and the model
   would answer `"unknown"` with no error. Recorded in `docs/EPIC_2_PLAN.md`; needs the golden set.

## Deferred, not dropped

Recorded so they stay visible: backups; a stuck-job sweeper (`updated_at` makes a dead worker's
`processing` row detectable, nothing sweeps it); `DELETE /v1/documents`; metrics; correlation
ids; RapidOCR cache-location verification.

---

## Session log

Newest first.

### 2026-08-03 (later) — the rate limiter moved onto `limits`

The user asked why a battle-tested library was not being used, was given the tradeoff, and
called it: switch. Done, and the interesting part is what the switch cost, because "use the
library" undersells it.

**`limits` supplies counting and has no opinion about anything else.** Fail-open, the headers,
the per-loop client, and the settings-driven limits all stayed ours — and those are where all
four of this project's historical rate-limit bugs lived. The library replaced the ~45 lines that
had never broken.

**Two bugs were found during the swap that the old code did not have**, both from trusting
`limits`' output rather than checking it:

1. `get_window_stats` derives the reset as `current_expires_in % expiry` against a TTL of *twice*
   the window. Correct inside the window; at the instant one opens it computes `120 % 60 == 0`,
   so the **first request against a fresh key advertised `X-RateLimit-Reset: 0`** — retry now,
   with the budget already spent. For a low-traffic key that is the common request. Clamped in
   `_reset_seconds`, with a mutation-tested guard.
2. `limits` fails **closed**. An unreachable Redis raises out of `hit()`, so the `except` in
   `check` is now load-bearing in a way it was not before, and there is a second test for a
   failure *between* `hit` and `get_window_stats` — that window would otherwise 500 a caller
   whose budget was already spent.

**One test was deleted rather than weakened.** The concurrency test asserted that grants report
distinct `remaining` values counting down to zero. That held when one Lua call returned the
decision and the numbers together; it cannot now, because `remaining` is a second round trip.
The assertion is gone and the reason is written where it was. Under concurrency the advertised
`remaining` can disagree with what the next request is granted — a real regression, accepted.

**One test changed shape.** The window-boundary test injected a clock, which worked while the
trim was arithmetic we wrote. `limits` rolls on Redis key expiry, so a time-injected version
would pass with the mechanism entirely broken. It now uses a real one-second window and really
waits (~1.2 s of suite time) — one point on the line instead of the exact boundary.

**And an IDEAS entry went stale within the hour.** "Shorten the rate-limit ZSET member" was
written from the memory measurement, and the same measurement then argued for adopting `limits`,
which deleted the ZSET. Left struck through as an example rather than silently removed.

Gate: 372 passed / 0 skipped, three consecutive runs.

### 2026-08-03 — the remaining 21 review findings, and three rounds of agent review

All 51 findings from the 2026-08-02 external review are now closed. The batches, and the
verification each survived, are in the commit bodies (`35f9c3d`, `4731f2c`, `a2b91d1`, `4ed76b5`,
`360fb1f` and the follow-up). What belongs here is what the *reviews of my own fixes* found,
because the pattern repeated three times and is the transferable part:

**Every round of agent review found a defect in the previous round's fixes, including one
critical.** Not diminishing returns -- round 3 was the most valuable. In order:

1. My M8 caption cache was keyed on `figure_id` and therefore **collided** rather than missed: a
   newly-inserted figure was handed the caption written for whatever used to sit at its index. My
   docstring asserted the opposite in as many words, and the test *named* for that property
   asserted only call counts and ids, which a collision satisfies. Now content-addressed.
2. Then the content-addressed version deduplicated only against the cache on disk, not within a
   batch -- so a logo on ten pages still cost ten calls on the first ingest and got ten
   *different* captions. My test pre-warmed the cache, so it could not see it. Same construction
   flaw as (1), one commit later.
3. My table-caption dedup compared `caption in markdown`, and docling's serializer escapes `_` as
   `\_` and HTML-escapes `&`/`<`/`>` -- so three of six realistic scientific captions still
   doubled. The test counted raw occurrences, which stays 1 when the second copy is escaped.
4. `truncated` was forwarded to `AskResponse` by one line that no test covered: deleting it left
   the whole suite green while every truncated answer reported as complete.
5. Unifying the two `_state` renderers averaged a real difference (the Streamlit page has its own
   date columns) instead of surfacing it -- rule 6, in a commit whose message cited rule 6.

**The transferable lesson:** a test that asserts *cost* (call counts) or *shape* (ids, lengths)
passes under a correctness bug. Assert content, and make the fixture able to distinguish wrong
content from right -- captions derived from the input, not from batch position.

**Also learned about the tooling:** four of the ~40 numbers I wrote into comments this session
were wrong on checking (`libssl3` "a few hundred KB" -- it is already in the base image;
"six transitive packages" -- two; "32-char doc_id" -- 65; "hangs with no timeout" --
`huggingface_hub` sets a 10s ETag timeout). Rule 13 applies to prose in comments, not just to
dependency claims.

**Standing gaps this session did not close:** whether Anthropic truncates the *citation list*
along with the text under `max_tokens` is asserted in three places and unverified; and the nginx
image's `apt-get` layer cannot build behind this sandbox's proxy (the config itself is proven to
parse via `nginx -t` inside `nginx:1.29`).

**`streamlit` publishes on `0.0.0.0` on purpose** -- `api` and the three data services were moved
to `127.0.0.1`, and an earlier version of this entry listed `streamlit` with them as an open gap.
It is not one: nginx proxies only `portfolio_api`, so loopback-binding 8501 would make the UI
SSH-tunnel-only, and the page renders nothing before a key is pasted. The reasoning now lives on
the `ports:` block itself. What *is* still open is fronting it with nginx, so it inherits the
timeouts, body-size cap and security headers the api gets only by sitting behind the proxy.

**The smoke job had never actually run its assertions, and hid a real stack bug.** Worth reading as
one story, because the first cause masked the second:

1. Two runs died at `Bring the stack up` in ~5 seconds on
   `Post "https://auth.docker.io/token": read: connection reset by peer` -- an anonymous Docker Hub
   token flake pulling `python:3.14-slim`, not our code. It reds the one job that builds the images
   and skips every assertion below it, so the step is now retried three times, then `::error::`.
   Verified against a stub `docker`: 1 invocation on success, 3 then exit 0 when the first two
   fail, 3 then exit 1 when all three do.
2. With that noise gone the run got 7m41s in and failed for real:
   `failed to mkdir /var/lib/docker/volumes/portfolio_model_cache/_data/torch: file exists`.
   **The Dockerfile pre-created `huggingface/` and `torch/` inside the `model_cache` mount point.**
   Content at a mount point is copied into a fresh named volume during container *create* (not
   start), and `api`, `worker` and `streamlit` all mount that one volume, so their creates raced
   the copy. The mount point itself must stay -- Docker applies its ownership to the volume root,
   and a root-owned mount point leaves appuser unable to cache anything -- but its *contents* must
   not: `huggingface_hub` and `torch.hub` both `makedirs(exist_ok=True)`, so pre-creating them
   bought nothing.

Both reproduced rather than reasoned about. Six concurrent `docker create` on a fresh volume with
two empty dirs at the mount point → EEXIST; with the mount point empty → 48 concurrent creates,
zero errors, `_data` still `appuser:app`, `mkdir -p torch/hub` still works from inside.

**The race fired once in eight rounds**, which is the part that matters for CI: a green bring-up
would not have told us a re-added `mkdir` was safe. So the guard is not the bring-up -- it is a
deterministic step asserting `/home/appuser/.cache` is empty in the built api image, red against
the pre-fix image and green against the fixed one.

**And this is what the smoke job is for.** Four commits of fixes went in while the only job that
builds the images had failed at step 6 every time. Nothing else in the gate can see a
compose/Dockerfile interaction -- `docker compose config` parses compose, and unit tests never
build an image. A red job whose cause was dismissed as "just a registry flake" is rule 12 wearing
different clothes.

**Confirmed green on `141a52c`** -- the first run in which this job executed its assertions rather
than dying at step 6. Every one passed: the mount point is empty in the built image, `/health/ready`
returned 200 on the *first* poll with postgres, qdrant and redis all reachable from the api
container, nginx's generated upstream proxies, auth is enforced through the proxy, and the worker
claimed its queue. Measurements for the next session: the cold image build is **7m35s** (torch +
Docling dominate), the whole job 7m52s, and the four other jobs finish in 2m20s. So a `main` push
is green in ~2.5 minutes and *fully* green in ~8.

### 2026-08-02 — an external review of 51 findings, and two rounds of fixing it

The user had another Claude Code session audit `portfolio/` and pasted the report: 1 critical,
6 high, 21 medium, 23 low. **It was accurate** -- 14 findings spot-checked against the code,
all 14 held. Treat that report as trustworthy if it comes up again.

**Fixed so far (30 of 51):** C1, all six H, M3 M4 M10 M11 M12 M15 M16 M18, L1 L9 L11 L15.
Commits `e23e499`, `7e7df28`, `4731f2c`.

**Two agent reviews of my own fixes, both of which found real defects in them.** Worth
repeating the pattern rather than the details, because both were the same mistake:

1. My H2 fix (filename scoping across spaces/parens) passed its test and **did not work**.
   `mentions_a_document` is a gate `/ask` early-returns on; I widened the resolver and left
   the gate narrow, and the test called the resolver directly. There is now a test that
   drives gate and resolver together.
2. Seven fixes were **mutation-vacuous** -- revertible with the suite green -- including the
   headline H4 handler, one commit after I had invoked rule 15 against someone else's vacuous
   test. Six now go red under mutation. M18 (Streamlit) stays unverifiable: no test harness.
3. A docstring I wrote confidently was **false**: registering a handler for bare `Exception`
   does not put it inside `CORSMiddleware` -- Starlette installs it *as* `ServerErrorMiddleware`,
   the outermost layer. Measured, then corrected.

**The suite was flaky and that invalidated every earlier "green".** Runs varied 230-234 on an
unchanged tree. Two causes: M4 (one fixed key id bucketed against real Redis, so tests began
429ing once the file grew) and `test_concurrent_processes_can_initialise_the_schema` running
`DROP SCHEMA public CASCADE` on the shared test database while three subprocesses raced to
rebuild it. That test now gets a throwaway database of its own; the other three DB suites
truncate instead of dropping, at setup as well as teardown. **Five consecutive runs: 249
passed, 0 skipped.** Do not trust a single green run in this repo -- run it three times.

**Found while fixing, not in the report:** `X-RateLimit-*` vanished on every `APIError` path
(404/422), because the handler builds a fresh response and only the 429 passed its own copy.
Now stashed on `request.state` and re-attached.

**Left (21):** M1 (the user is doing this one), M2, M5-M9, M13, M14, M17, M19-M21, and the
L-tail L2-L8, L10, L12-L14, L16-L23.

**M1 is bigger than "unused dependencies".** `googlemaps`, `pyzbar`, `brightdata-sdk`,
`playwright`, `cairosvg`, `cssutils` are *smads_ai's* dependency set (pyzbar decodes the QR in
its `company_info.py`, googlemaps drives its `google_places.py`), and `[project.urls]` points
at `github.com/cs83/smartico-ai`. The manifest was copied from that project, so classifiers,
description and author are suspect too -- it wants rewriting, not pruning.

### 2026-08-02 — scopes, per-key rate limits, key CRUD, 30-day default expiry

Four asks in one turn: 30-day default expiry from a 30/60/90/365/never menu; scopes as
"option B", a scope set checked per route; 403 for scope failures; rate limiting per key. Plus
a mid-turn fix: `--revoke` looked keys up by id alone with no tenant check.

**Shape.** `app/auth/scopes.py` holds the vocabulary and the pure comparison functions
(`granted`/`has_scope`/`unknown_scopes`/`exceeds`). `Principal` (tenant, key id, scopes) came
out of `resolve_principal`; `resolve_tenant` is now a thin wrapper, kept because most callers
genuinely only want the retrieval scope. `require_scopes` in `deps.py` checks per route.

**Three things that are easy to get wrong and are now pinned:**

1. **An empty scope list means *every* scope.** Keys minted before the column existed have no
   list. Reading `if not key.scopes` as a denial would have revoked all of them.
2. **…which makes an omitted list on `POST /v1/keys` an escalation.** `exceeds([], holder)` is
   vacuously empty, so the guard never fires, and storing `[]` means unrestricted — a
   `keys:write`-only key could mint itself an unrestricted one. The route materialises an
   omitted list into the caller's own scopes.
3. **Overriding `current_tenant` in tests no longer authenticates anything.** `require_scopes`
   and `rate_limited` both hang off `current_principal`, so the seam moved. Five contract
   tests failed exactly this way; the `add-endpoint` skill was corrected.

**`require_scopes` became a callable class**, purely so the route table is introspectable: a
closure hides its requirement in a cell, and `test_scopes.py` walks every route and fails on
any `/v1` route with no requirement — the assertion a newly added route silently falsifies.

**Key CRUD lives in `app/auth/management.py`, not the router.** The Streamlit page
(`streamlit_app/pages/1_API_keys.py`) manages keys in process, exactly as `Home.py` ingests in
process, so the escalation guard and the tenant filter had to be one implementation. The router
is now only the translation from refusal to status code. Same reasoning as
`ingestion/uploads.py`, and it raises its own exceptions rather than `APIError` for the same
reason.

**Verified beyond the suite:** the Streamlit page driven end to end with `streamlit.testing.v1`
against real Postgres (authenticate → list → mint with `["ask"]` and 90 days → the row in
`psql` shows `{ask}` and 90 days), and all three CLI revoke paths (no `--tenant` refuses, wrong
tenant refuses, right tenant revokes). The smoke tenant was deleted afterwards; `apikey` is
empty again.

Schema: `apikey.scopes varchar[] NOT NULL DEFAULT '{}'` added by hand-written `ALTER` on the
dev database (`create_all` does not add columns — see the entry below).

### 2026-08-01 — key expiry, and the API key declared in OpenAPI

`ApiKey.expires_at` added, `NULL` = never. Checked in the `WHERE` clause beside the revocation
check, using `func.now()` — the *database's* clock, so a skewed api process cannot honour a key
past its deadline. Expired reads as unknown, same as revoked. CLI gained `--expires-in DAYS`
and a `_state()` column; it now says out loud when a key has no deadline.

**Deliberately opt-in, not the default.** Defaulting to a deadline is the safer policy and is
recorded in `docs/IDEAS.md` as a decision still to take.

**Operational trap worth remembering — now in `CLAUDE.md`:** `create_all` creates missing
*tables*, never missing *columns*. Adding a field to an existing model changes nothing;
`init_db` reports success and the next query fails with `column ... does not exist`. With no
Alembic, a new column means dropping the table or hand-writing the `ALTER`. `apikey` was empty,
so it was dropped and recreated.

Also, from a mid-session question: the key is now an `APIKeyHeader` security scheme rather than
a bare `Header()` parameter, so `/docs` has an Authorize button and a generated client models
it as a credential instead of a per-call argument. `auto_error=False`, or FastAPI's own 403
would make an absent key distinguishable from an invalid one. Three contract tests pin it.

Tests were mutation-checked: deleting the expiry clause fails 3 of them.

### 2026-08-01 — key format: base62 + CRC32 checksum

Read three sources on API key design (GitHub's 2021 token-format post, Zuplo, jamdesk) and
compared them line by line against what exists. **Most of what they recommend was already
done** — CSPRNG entropy, prefix, hash-only storage, show-once, display prefix, indexed unique
hash, `last_used_at`/`revoked_at`, per-key rate limiting, and the no-bcrypt reasoning that two
of the three explicitly endorse. Confirmation, recorded in `docs/TECHNICAL_DECISIONS.md` so
the next review doesn't redo the comparison.

Three things changed, all free because `apikey` is still empty: base62 instead of base64url
(`-` truncates a double-click selection, so a user copying a key gets a fragment and an opaque
401), a 6-character CRC32 checksum, and a matching gitleaks rule. Key is now 57 characters.

**The checksum is an integrity check, not a security control** — CRC32 is not cryptographic
and anyone can compute a valid one. It buys offline rejection of typos and fabrications
(1-in-2³² false accept), nothing more. A test pins that reading, because the dangerous
misunderstanding is one upgrade in someone's head away.

Still not built, and the only real gaps the review found: **key expiry** and **scopes**
(`docs/IDEAS.md` § Auth).

### 2026-08-01 — API key review: shape check tightened, hash moved to SHA-512

An external review of `app/auth/keys.py` produced three suggestions. One was taken (exact-
length shape check — the old `len > 16` let a prefixed multi-megabyte body reach the hash).
Two were rejected with reasons now in `docs/IDEAS.md`: an HMAC pepper (right advice, wrong
threat model — and it can never be rotated, because re-deriving digests needs the plaintext
keys) and `BYTEA` storage (under 1 MB saved at target scale, against an unreadable column and
a hand-written migration with no Alembic). The review's real value was the two gaps it
surfaced in passing: **no key expiry and no scopes**, both now in `docs/IDEAS.md` § Auth.

Then hashing moved SHA-256 → **SHA-512** at the user's request. Recorded here because the
timing was the whole decision: the `apikey` table had **zero rows**, verified before changing
anything, so this was free. At any other time it is a full re-key of every tenant — plaintext
keys are never stored, so no digest can be recomputed. **`hash_key` is now frozen**, pinned by
a test asserting a known key's exact digest. Reasoning and the two rejected alternatives
(SHA-512/256, not in `hashlib`'s guaranteed set; SHA-3, slower for a property we don't use)
are in `docs/TECHNICAL_DECISIONS.md`.

### 2026-08-01 — repo hygiene: templates, security workflows, pattern and memory docs

Added `.github/` issue forms (bug, feature) and a PR template, all written around this repo's
*silent* failure modes rather than generic prompts — the bug form asks for the pytest skip
count, the PR template's checklist is the tenant boundary and the re-ingestion delete step.

Added `.github/workflows/security.yml`: CodeQL (`security-extended`, scoped to
`portfolio/app|scripts|streamlit_app`) and a gitleaks history scan, both weekly on a schedule
plus on PR. Rationale: the existing pipeline audits *dependencies* and only fires on
`portfolio/**` changes, so a CVE disclosed against untouched code never surfaces, and nothing
looked at our own code or at committed credentials at all. `.gitleaks.toml` allowlists the
documented placeholders (`pf_live_...`, `KEY_PREFIX`, the deliberately-invalid
`sk-ant-something` test fixture) narrowly rather than by silencing directories.

Wrote `docs/PATTERNS.md` (19 patterns, each verified against source, each naming the failure it
prevents) and this file.

**Still to do by hand — I cannot set these:** enable **secret scanning + push protection** in
Settings → Code security. That is the control that stops a key landing; the gitleaks job only
catches what already did.

### 2026-08-01 — measured what an answer costs

Traced one real `/ask` to exact token counts. Findings in **Measurements** above; the
actionable ones are that output dominates cost 60/23, that the answer finished 11 tokens under
`max_tokens`, and that nothing in the codebase records usage (now Open question 4).

### 2026-08-01 — `doc_id` scoping ([`ae53c67`](https://github.com/stanimirdim92/llms/commit/ae53c67))

A question naming `doc_id=019fb3eb…` searched unscoped: the pre-check only looked for
filenames, returned `False`, and skipped the registry read. Four of five reranked chunks came
from the tenant's CV instead of the named advertisement — the question was mostly Pydantic
field descriptions, which embed closer to a CV's contact sections than to a sparse flyer.

Generalisable lesson, and the reason this is worth remembering: **the pre-check gates the
registry read, so any identifier it fails to recognise silently never scopes.** A `False` there
is indistinguishable from a question that named nothing.

`mentions_a_filename` → `mentions_a_document`. Two id spellings accepted: the bare
`{tenant_id}-{hash}` shape, and an explicit `doc_id=` marker — the latter because the curated
corpus uses bare arXiv ids like `2008.10896`, unmatchable on shape against prose.

### 2026-08-01 — filename scoping ([`36c8770`](https://github.com/stanimirdim92/llms/commit/36c8770))

Built `retrieval/document_scope.py`. No model call: the candidate set is the tenant's own
registry rows, so it is string matching against a closed set. Matching requires the full
filename *with extension* — bare stems would let a tenant owning `data.pdf` have "what data
does the study use?" silently narrowed to it.

Two bugs caught during this work, both the same shape — **code inserted between a decorator and
its function**. First, a helper placed under `@router.post` took the decorator, so `/v1/ask`
started returning `DocumentScope`; caught by diffing the generated OpenAPI. Then, inserting
tests between `@pytest.mark.usefixtures` and its function silently unauthenticated an existing
test; caught by the suite. Worth carrying forward as a review reflex.

### 2026-08-01 — filename in chunk metadata ([`85ff4e2`](https://github.com/stanimirdim92/llms/commit/85ff4e2))

(This entry was titled "redis image pinned, filename in chunk metadata" and never mentioned the
redis pin. The reasoning for that pin is real and lives in `redis/Dockerfile`'s own comment,
which is the right place for it; the title has been trimmed to what the body actually covers.
A log entry promising something it does not deliver is worse than a shorter one, because the
next reader searches for it and concludes it was never written down.)

`filename` now rides in the chunk payload and leads the model-visible block title. The symptom
it fixed: the model summarising a document's contents while stating it had no document by that
name, because the only label it was given was a 65-character content hash.

**Consequence still outstanding:** points written before this change carry no `filename`.
Scoping still resolves them (via `doc_id`), but the model won't see the name and Streamlit's
chunk labels fall back to the hash. **A re-upload backfills it.**

### 2026-07-30 → 08-01 — earlier

Python floor 3.13 ([`2cfabbb`](https://github.com/stanimirdim92/llms/commit/2cfabbb)) — the
retarget surfaced a real crash-on-import in `Home.py` that `py314` had hidden behind PEP 649's
deferred annotations. Epic 2 and 3 plans written
([`eeb185f`](https://github.com/stanimirdim92/llms/commit/eeb185f)). Scale target and the
graph-DB verdict recorded ([`ad14a4e`](https://github.com/stanimirdim92/llms/commit/ad14a4e)) —
`microsoft/graphrag` was read closely; it uses no graph database (networkx in memory, parquet
on disk), and all 8 of its packages pin `requires-python <3.14`, so anything taken from it is
reimplemented rather than imported.
