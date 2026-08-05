# Patterns

The recurring shapes in this codebase, each with the file that demonstrates it and **the
failure it exists to prevent**. That last part is the point: a pattern justified only by "it's
good practice" gets dropped the first time it's inconvenient, and a pattern whose failure mode
is named survives review.

Related but different documents: `docs/TECHNICAL_DECISIONS.md` says why a *technology* was chosen
over its alternatives. `CLAUDE.md` is the rule list — the short, imperative version of the
non-negotiables below. This file explains the shapes those rules protect.

---

## 1. Authorization is a dependency, not middleware

`api/deps.py` resolves one `Principal` (tenant, key id, scopes) per request and exposes three
things layered on it: `CurrentTenant` for the retrieval scope, `require_scopes(...)` for the
capability check, and `rate_limited(...)` for the budget. Every route declares what it needs.

Middleware was the obvious alternative and is worse on three counts: it can't be overridden
per-test (`app.dependency_overrides[deps.current_principal]` is what makes the auth suite run
with no database), it doesn't appear in the OpenAPI schema the Phase 6 React client generates
from, and it would have to reimplement path matching to know which routes to skip.

One principal, three consumers, one lookup: the key resolves once per request because FastAPI
caches dependency results, so the scope check and the rate-limit bucket cost no extra query.

**Prevents:** an untestable auth layer, and a security control invisible to API consumers.

**Costs:** the boundary is re-declared per route, so a route added without it is unauthenticated
— or authenticated but reachable by every key — and *nothing raises*. Paid down with a
per-route 401 test and `tests/unit/test_scopes.py`, which walks the route table and fails on
any `/v1` route with no scope requirement. See `.claude/skills/add-endpoint`.

## 2. No ambient authority — the tenant filter is re-established per query

`tenant_id` never lives in a request-scoped global that downstream code implicitly trusts. It
is passed explicitly and lands in the WHERE clause (`registry/db.py::get_document_record`) or
in the Qdrant filter (`vectorstore/qdrant_store.py::_build_filter`).

The specific trap, stated correctly on the second attempt. Both this section and
`registry/db.py`'s own docstring used to say "`doc_id` is a content hash, so two tenants
uploading identical bytes share one id" — which is **false here**: `upload_doc_id` salts the
digest with `tenant_id`, and a passing test asserts exactly that. (This same file says so two
sections down.) The rule survives the correction, but for a different reason: a `doc_id` is
client-supplied on the way *in* to a lookup, so nothing about how it was generated constrains
what a caller can send. `GET /v1/documents/{doc_id}` receives whatever the client typed, and one
tenant can paste another's id — from a shared log, a screenshot, a colleague. The WHERE clause is
what makes that a 404 instead of a row. Filtering after the query — `if row.tenant_id != caller`
— is not equivalent, because by then the row has been read.

Worth flagging as a documentation failure in its own right: this project treats its own docs as
verified fact, so a wrong *reason* attached to a right *rule* is how the rule gets "simplified"
away later by someone who checks the reason and finds it doesn't hold.

**Prevents:** cross-tenant reads. This class of bug returns data instead of raising, so it is
invisible until someone reports seeing a stranger's document.

## 3. Client-supplied identifiers are resolved against the caller's own rows

An id in a request body is user input no matter how authoritative it looks.
`retrieval/document_scope.py` matches filenames and `doc_id`s against the output of
`list_document_records(tenant_id=...)` — entitlement-filtered in the WHERE clause — so an id the
caller may not read resolves to nothing and returns 404, rather than reaching a Qdrant filter.

There were two such queries until 2026-08-03, and the pair is worth remembering even though it is
gone. A shared corpus readable by every tenant made "what may I scope to" strictly wider than
"what do I own", so scoping used a separate `list_scope_candidates`. They disagreed: the narrower
one excluded the corpus, so the documented `doc_id=<arXiv id>` form 404'd on every curated paper
while its unit test passed against a made-up tenant id. **Two functions answering almost the same
question is the shape to distrust** — with the corpus removed they collapsed into one, and the
only surviving difference is a `limit` passed at the call site.

**Prevents:** the validation gap that would otherwise open the moment any id becomes an input.
Note the accident this avoids relying on: an unowned `doc_id` ANDed with the tenant condition
returns *zero results*, which is safe — but reads as "the document is empty" and is correct
only by coincidence. Correct-by-coincidence stops being correct when someone reorders the
conditions.

## 4. Deterministic work gets plain code; the model gets judgment calls

`document_scope.py` does no model call. The candidate set is closed — the tenant's own
documents — so recognising a named document is string matching, not extraction. The reranker,
the answer generation, and figure captioning are model calls because each is a genuine
judgment.

**Prevents:** paying latency, cost, and nondeterminism for work `if`/`else` does exactly. The
second-order benefit is bigger: the deterministic half unit-tests with no services and no API
keys, which is why `test_document_scope.py` runs in CI on every push.

## 5. Fail fast on configuration, fail open on guardrails

Two opposite behaviours, chosen per component by asking *what does an outage of this thing
actually mean?*

- **Fail fast:** `config.py::require_provider_credentials` aborts the api at boot when
  `ANTHROPIC_API_KEY` or `VOYAGE_API_KEY` is missing. A process that starts and then fails every
  request is worse than one that never starts — it passes the liveness probe.
- **Fail open:** the Redis rate limiter allows the request and logs a warning when Redis is
  unreachable (`rate_limit.py`). A guardrail's outage must not become the API's outage.

The same reasoning splits the health checks: readiness 503s when Postgres or Qdrant is down but
only *reports* Redis, because pulling instances from rotation over an optional component is a
self-inflicted outage.

**Prevents:** both a silent-startup-into-total-failure and an optional dependency taking the
service down with it.

## 6. Liveness and readiness answer different questions

`GET /health/live` is static. `GET /health/ready` probes dependencies. Merging them means a
Postgres blip restarts the process, which fixes nothing and converts a hiccup into a restart
loop.

Readiness also must not construct `QdrantStore`: its `__init__` sends a probe embedding to
detect vector size, so that would bill a Voyage call every 30 seconds and report Qdrant down
whenever Voyage was. `health.py` uses a bare cached `AsyncQdrantClient` instead.

**Prevents:** restart loops, and a health check that costs money and lies about which
dependency failed.

## 7. Idempotence by deletion, not by id collision

`QdrantStore.upsert` deletes every point for a `doc_id` before inserting. It is tempting to
think deterministic point ids make that redundant — they don't. Chunk ids encode position
(`{doc_id}-text-0000`), so anything changing how many chunks a document yields — a different
`chunk_max_tokens`, a Docling upgrade detecting one more figure, toggling `do_ocr` — shifts
every later id. The new ids insert cleanly while the old points remain, still matching the
tenant filter, still retrievable, now stale.

**Prevents:** stale chunks that survive re-ingestion. There is no other cleanup path.

## 8. Content-addressed ids for documents, time-ordered ids for rows

`doc_id = f"{tenant_id}-{sha256(tenant_id + NUL + bytes)[:32]}"` (`ingestion/uploads.py`) —
deterministic, so re-uploading identical content updates rather than duplicates. The tenant is
both a prefix *and* an input to the digest, so two tenants' ids for the same file share no
common suffix and comparing ids cannot reveal that they uploaded the same document.

Tenant and key ids use `uuid7` (`app/ids.py`) instead, because they are primary keys and want
index locality — a `uuid4` fallback was explicitly rejected for that reason.

**Prevents:** duplicate documents on re-upload, an id that leaks content equality across
tenants, and B-tree fragmentation on the hot tables.

## 9. Blocking work is offloaded, not wrapped in `async def`

`ingest_document` calls `asyncio.to_thread(_parse_and_chunk, ...)` and
`asyncio.to_thread(store.upsert, chunks)`. Docling parsing is CPU-bound and
`QdrantVectorStore.upsert` is synchronous; marking either `async def` frees nothing and one
upload stalls every other request on that worker.

**Prevents:** event-loop starvation that presents as unrelated requests timing out.

## 10. The producer and the consumer do not share imports

`POST /v1/documents` returns 202 and enqueues; the `worker` service ingests. The api **must
not** import the ingestion stack: `worker/app.py` carries no `import_paths` and defers by task
*name* so it never pulls Docling into an api process (~2s of startup, ~157MB each).
`ingestion/formats.py` therefore keeps a pinned extension list, drift-checked against Docling
in `test_upload_formats.py`.

**Prevents:** a convenient import silently making every api process fatter and slower, with
nothing failing.

## 11. Cross-process coordination uses the database, not the process

`init_db` takes `pg_advisory_xact_lock` before `create_all`. An `asyncio.Lock` only serializes
coroutines within one process, and the real concurrency is `GUNICORN_WORKERS` processes plus
the worker container booting together. Both `create_all`'s checkfirst and procrastinate's
existence check are check-then-create, so the loser crashes with `DuplicateObject`.

Transaction-scoped on purpose: a session-level lock leaked by a crashed process would deadlock
every later boot.

**Prevents:** a startup race that reads as a database fault. Observed on the first real boot,
and pinned by a test that must use real subprocesses — an `asyncio.gather` version passes even
with the lock removed.

## 12. One settings object, resolved once

`config.py::Settings` is a single `pydantic-settings` model behind `@lru_cache`-ed
`get_settings()`. Same shape for the other expensive singletons: `@lru_cache` factories for the
engine (`db.py`), the reranker (`retrieval/reranker.py`), the answer service, and the health
probe client.

One deliberate exception: the Redis client is cached **per event loop**, not per process,
because a `redis.asyncio` client binds its pool to the creating loop and a process-wide
singleton breaks under repeated `asyncio.run()` (Streamlit, CLIs, per-test loops).

**Prevents:** re-reading env vars per request, rebuilding clients per call, and — for the Redis
case — a cache that works in the api and fails everywhere else.

## 13. Swappable backends behind a factory, chosen by config

`retrieval/reranker.py` returns a Voyage or a local cross-encoder compressor based on
`settings.reranker_backend`. The caller sees one function.

Deliberately *not* generalised into a formal `Protocol` or plugin registry: there are two
implementations and one switch point. An abstraction layer here would be speculative.

**Prevents:** hard-coding a paid API into a path that needs to run offline — while not paying
for indirection nobody asked for.

## 14. Errors are a typed taxonomy that carries its own HTTP semantics

Code raises `APIError(msg, code=...)` from `exceptions.py`, never a bare `HTTPException`. It
carries `headers`, because a 429 without `Retry-After` tells a client to back off but not for
how long — so it guesses, or hammers. The handler in `api/main.py` logs structurally and must
forward those headers; it overrides FastAPI's default, so dropping them silently strips
`Retry-After` from every rate-limit response.

**Prevents:** unstructured error logging, and a rate limiter that provokes the retry storm it
exists to stop.

## 15. Refuse rather than answer from the wrong material

Recurring across three unrelated components:

- An unowned document name is a **404**, not a fallback to searching everything.
- A parse yielding no text raises `EmptyDocumentError` rather than recording `ingested` with
  `chunk_count=0`. A scanned flyer extracted 30 characters with `do_ocr=False` versus 395 with
  it on; the lie is only discoverable by asking a question and getting someone else's document.
- A figure caption matching `_UNUSABLE_CAPTION_MARKERS` is dropped. The vision model's "I'm not
  able to see the image" answers became chunks, won reranking, and grounded answers.

**Prevents:** the worst failure mode this system has — a fluent, confident, wrong answer, which
is indistinguishable from a correct one at the point of use.

## 15b. Content-addressed caches, never position-addressed

The figure-caption cache keys on a sha256 of the rendered PNG, not on `figure_id`. `figure_id` is
`fig-{page}-{index}` over every picture item, so inserting a picture earlier in a document shifts
every later index down onto an id an earlier figure already held — and nothing deletes stale
entries, so that is a **collision**, not a miss. Measured before the fix: a newly inserted figure
was handed the caption written for whatever used to sit at index 0.

The same shape applies to `content_hash` in the registry (a digest of the bytes, answering "did
the content change under a stable id") and, in the negative, to Qdrant point ids — which *are*
derived from position (`{doc_id}-text-0000`) and are only safe because `upsert` deletes every
point for the document first. Two conventions, one of them safe for a different reason; see
"Never remove the delete step" in `CLAUDE.md`.

**Prevents:** a cache entry describing something other than what asked for it — which reads as
perfectly good content at every point of use. Also, deduplicate *within* a batch and not only
against the cache, or the first pass pays per duplicate and gets a different answer for each.

## 16. 404 over 403 for another tenant's resource

Distinguishing "not yours" from "doesn't exist" confirms to any caller that a given id belongs
to *somebody* — and ids leak: out of a shared log, a screenshot, a support thread, a URL in a
bug report. A 403 turns each leaked id into a confirmed account.

(This used to be phrased as "an existence oracle over content hashes", which implied an attacker
could *derive* another tenant's id by hashing a file they both have. They cannot —
`upload_doc_id` salts the digest with `tenant_id`. The rule stands; the enumeration it prevents
is over ids someone already has, not ids they can compute.)

**Prevents:** enumeration. Costs a slightly less helpful error for the legitimate case.

## 17. Tests execute the real engine; only the network is faked

`test_qdrant_filtering.py` runs `_build_filter` through `qdrant_client`'s in-memory engine with
fake embeddings, so tenant isolation is proved by execution in CI with no server and no API
keys. The auth and worker suites hit a **real Postgres** — an interim SQLite version surfaced a
genuine tz bug but was replaced, because testing on an engine the app never runs is how
backend-specific bugs hide.

The assumption SQLite exposed is now pinned by an explicit test
(`test_stored_timestamps_come_back_timezone_aware`) rather than by defensive normalisation.

**Prevents:** mocks that assert the code calls itself the way you wrote it. What remains
untested is the real client over the wire — which is exactly where the point-ID constraint
escaped to production, so don't say "Qdrant is tested" without that qualifier.

## 18. A skipped test must not look like a passing one

Service-backed suites skip when Postgres or Redis is unreachable, so a green local run can have
tested far less than it appears to. CI provides both services and **asserts none of the five
suites skipped** (`.github/workflows/portfolio-ci.yml`). It guarded three for a while, which let
the two newer ones skip in CI silently — the failure this pattern exists to prevent, occurring
inside the guard against it.

**Prevents:** the most expensive kind of false confidence, because it is self-reinforcing —
every subsequent green run inherits it.

## 19. Comments record the failure, not the mechanism

Throughout. Comments here answer "what breaks if this changes", not "what does this line do".
The `redis/Dockerfile` spends 20 lines on why `USER redis` is safe *today* and what re-enabling
persistence would break; `_build_filter` explains that a wrong filter returns data rather than
raising.

**Prevents:** a future reader — human or model — reverting a subtle constraint because the code
looked redundant. Every entry in `CLAUDE.md`'s "Failure contracts" section began as one of
these comments.

---

## Deliberately absent

Naming these is as useful as naming the patterns, because each is a thing a reviewer might
otherwise "fix":

| Not used | Why |
|---|---|
| Repository/DAO classes | `registry/db.py` is module-level functions taking an `AsyncSession`. There is one backend and no second implementation to swap; a class would add a layer with no seam behind it. |
| A service layer over the routers | Routers are thin and call one collaborator. An intermediate layer would be pass-through. |
| Dependency-injection container | FastAPI's `Depends` plus `@lru_cache` factories cover it. |
| Alembic migrations | One `create_all` at startup, called out as a simplification worth revisiting when the schema starts changing under live data. Recorded, not forgotten. |
| ORM lazy loading | Async SQLAlchemy makes implicit IO-on-attribute-access a trap; queries are explicit. |
| SQLite anywhere | Postgres-only, including tests. `DateTime(timezone=True)` round-tripping an aware value is a Postgres guarantee. |
| Mocking the vector store in unit tests | The in-memory Qdrant engine is real and free. |
| Retry wrappers around model calls | The SDKs already retry 429/5xx with backoff. A second layer multiplies the wait. |
