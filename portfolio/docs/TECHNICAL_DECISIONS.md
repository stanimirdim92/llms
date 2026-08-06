# Technical decisions

Why this system is built the way it is. Each entry states the decision, the reasoning, and
what was rejected — including the several choices that were reversed after contact with
reality, since those are the ones worth reading.

`docs/ARCHITECTURE.md` covers the agentic design survey. `CLAUDE.md` holds the operational
failure contracts. This file is the decision record.

---

## Document extraction: Docling, used directly

**Decision.** Docling, imported directly rather than through `langchain-docling`.

Docling's raw `DoclingDocument` exposes per-table and per-figure objects with bounding boxes
and page numbers. That is the whole point: tables must survive as atomic chunks and figures
must become their own chunk type. LangChain's `DoclingLoader` pre-chunks into generic
`Document`s and discards exactly that structure.

**Rejected — `unstructured`.** Broader format coverage, but its output is a flat list of
elements and its table handling is closer to "bounding box plus OCR'd text" than real
cell-structure recovery. For a corpus of materials-science papers, table fidelity *is* the
requirement. Left commented out in `pyproject.toml` rather than deleted, along with the note
that uncommenting it would also require the `tesseract-ocr` system packages Docling doesn't
need (its OCR path is RapidOCR).

**Rejected — PyMuPDF for figure cropping.** An earlier version re-opened the PDF with
PyMuPDF to crop figures, which meant flipping Docling's bbox coordinate origin to match
PyMuPDF's. Both the dependency and the coordinate math were unnecessary:
`PictureItem.get_image(document)` returns the rendered image directly.

## Chunking: three kinds, deliberately

Prose goes through Docling's `HybridChunker` (preserving a `section_path` from headings).
Tables are serialized whole to Markdown as single chunks. Figures become their own chunk
type whose embedded text is a Claude-generated caption.

Tables as atomic chunks is the load-bearing part — a table split mid-row produces chunks that
are individually meaningless and collectively misleading. Figures-as-captions keeps
everything in one embedding space instead of requiring a parallel multimodal retrieval path.

**Figure ids encode position, and that has consequences.** `fig-{page:03d}-{index:02d}`,
where `index` counts *every* picture item including ones that fail to render. This is
deliberate and pinned by `tests/unit/test_figure_ids.py`: the id feeds `chunk_id`, which
feeds the Qdrant point id, so renumbering churns every citation the document has ever produced.
It also desynchronises anything else addressed by that id -- which is why both the caption cache
and (since 2026-08-06) the PNG file itself carry a content digest. See the versioned-ingestion
decision below.

## Vector store: Qdrant, replacing Chroma

**Decision.** A real Qdrant server as a docker-compose service.

Chroma was originally chosen for zero-infra simplicity, which was the wrong trade for a
project whose point is production realism. Three things surfaced during the swap, all of
which cost real debugging time:

1. **The current class is `QdrantVectorStore`** (`langchain_qdrant.qdrant`), not the
   deprecated `Qdrant` in `langchain_qdrant.vectorstores`. They have different constructor
   signatures and different filter support.
2. **Filters must be real `qdrant_client.models.Filter` objects.** The Mongo-style dict
   shorthand (`$in`/`$and`) only ever existed on the deprecated class. This matters more than
   it sounds: a wrong filter doesn't raise, it silently returns the wrong documents — which
   for tenant scoping means cross-tenant reads.
3. **Point ids must be an unsigned integer or a UUID.** Chroma accepted arbitrary strings;
   Qdrant rejects `chunk_id` with a 400. Point ids are therefore
   `uuid5(fixed_namespace, f"{ingestion_version}:{chunk_id}")` — deterministic within one
   generation, deliberately distinct across generations (see the versioned-ingestion decision
   below). The human-readable `chunk_id` stays in the payload, which is where citations read
   it from, and is **not** where the version goes: `chunk_id` is a public response field. This
   one shipped and broke on first real use, because the dev sandbox has no Qdrant to test
   against.

**No native async client.** `asimilarity_search` is `VectorStore`'s thread-pool shim and
`upsert` is synchronous, same as Chroma. The gain from Qdrant is Qdrant, not async.

## Re-ingestion: versioned generations, published by one row (2026-08-06)

**Decision.** Each ingest mints an `ingestion_version`, hashes it into every point id, and inserts
without deleting. `DocumentRecord.ingestion_version` names the live generation and one UPDATE
publishes it; `Retriever` passes that version into the Qdrant filter, so the previous generation is
unreadable from the moment the UPDATE lands. `delete_superseded` prunes afterwards and is allowed to
fail. `upsert` still raises on a batch spanning more than one document or tenant, because
`delete_superseded` derives its selector from the same assumption.

**Rejected: delete-then-insert**, which is what this replaced, so it is recorded rather than
dropped. It deleted every point for the `doc_id` before inserting, and the reasoning was sound as far
as it went: chunk ids encode position (`{doc_id}-text-0000`, `fig-{page}-{index}`), so anything
changing how many chunks a document yields shifts every subsequent id, the new ids insert cleanly,
and the old points stay behind — retrievable and stale. Upserting by `chunk_id` alone genuinely does
not fix that.

What it missed is the failure on the other side. The delete and the insert are two operations with no
transaction around them, so a delete that landed and an insert that failed left a working document
with **no** points while its registry row still said `ingested`: retrieval permitted the `doc_id`,
found nothing, and an unscoped question was answered from the tenant's other documents with no
indication anything had gone wrong. Correctness depended on the *next* statement succeeding, which is
the property versioning removes. Putting the version in the point id makes the id collision-free
across attempts, so the insert is no longer destructive and there is something to fall back to.

**Rejected: appending the version to `chunk_id`.** Simpler to read, and wrong: `chunk_id` is a public
response field (`CitationResponse.chunk_id`, `RetrievedChunkResponse.chunk_id`), documented in
`README.md` and printed by Streamlit. It would churn every citation on every re-ingest and leak an
internal attempt id into the API. Only the point id has to differ.

**Rejected: an `ingestion_version` payload index.** It is filtered on every query, which looks like a
clear case for one, but it is a strictly finer partition of the already-indexed `doc_id` in the same
`must` — so it discriminates only during the window where two generations coexist. Against that, a
payload index is resident RAM on a 16GB target, and `_ensure_payload_indexes` runs from `__init__`,
so on a collection that already holds points the index would land after HNSW is built. Revisit with a
measurement, not an argument.

**Cost, stated plainly.** Storage for as long as a prune has not run, and no reconciliation for
orphans in either direction — a generation whose publish UPDATE never landed is inserted, unreadable,
and uncollected, because the prune only removes versions *other* than the one it keeps. That is why
`activate_document_version` raises rather than no-oping on a missing row: the raise is the only thing
that surfaces it. Reconciliation is still open (`docs/IDEAS.md`).

## Database: Postgres, and only Postgres

**Decision.** One engine, project-wide. No SQLite anywhere — not for tests, not for Epic 3's
LangGraph checkpointer (`langgraph-checkpoint-postgres`, not `-sqlite`), not for its incoming
queue.

The argument is concrete, not aesthetic. An interim version of the auth tests used in-memory
SQLite, and switching them to real Postgres immediately failed: the fixture seeded a `Tenant`
and its `ApiKey` in one flush, which SQLite accepted **because it does not enforce foreign
keys by default**. Postgres rejected it — the models declare no ORM `relationship()`, so
SQLAlchemy has no dependency information to order the inserts with. That is precisely the
class of bug testing on a substitute engine conceals.

The same episode produced a second lesson. `DateTime(timezone=True)` round-trips an aware
value *on Postgres*; SQLite returns naive datetimes, which broke a comparison against
`datetime.now(UTC)`. The fix is not defensive normalization but an explicit test
(`test_stored_timestamps_come_back_timezone_aware`) pinning the assumption, so a schema
change that drops `timezone=True` fails loudly rather than being silently absorbed.

**Async engine, tuned pool.** `create_async_engine` via psycopg 3's native asyncio support —
no separate driver package, unlike MySQL's psycopg2/aiomysql split. `pool_pre_ping=True`
matters most: without it, a connection dropped by the server or a proxy surfaces as an
`OperationalError` on the next request instead of being quietly reconnected.

**Pool sizing is per worker, not global.** Each gunicorn worker gets its own engine, so
`GUNICORN_WORKERS * (db_pool_size + db_max_overflow)` must stay under Postgres's
`max_connections` (100 by default). At the default 2 workers that is 30. A box running the
~17 workers an 8-core host would want needs either a lower `db_pool_size`, a raised
`max_connections`, or PgBouncer — called out in `config.py` rather than discovered in
production.

**Alembic**, adopted 2026-08-05. This said "no Alembic" and treated dropping the volume as the
migration path, which was defensible only while nothing in Postgres was worth keeping. It stopped
being defensible once the database held tenants and API keys, and the concrete failure was worse
than the inconvenience: `create_all` creates missing *tables* and never missing *columns*, so adding
a model field changed nothing, `init_db` reported success, and the next query failed with `column ...
does not exist`. `_migrate_to_head` runs `upgrade head` inside the boot advisory lock, and CI runs
`alembic check` so a model field without a revision fails there rather than in production.

## Tenant scoping: one field, derived only from auth

**Decision.** `tenant_id` replaced `session_id` entirely. `AskRequest` has no scope field at
all and sets `extra="forbid"`.

The original design accepted a client-supplied `session_id` on both upload and `/ask`. That
meant **any caller could read another tenant's documents by passing their id** — the schema's
own comment promised the opposite. Removing the field from the request rather than merely
ignoring it is the point: an absent field cannot be spoofed, and `extra="forbid"` means a
stale client gets a 422 instead of silently receiving answers scoped to somebody else and
appearing to work.

**Collapse rather than nest.** `tenant_id` from auth *plus* a `session_id` grouping key
underneath it was the alternative. It was rejected because it would keep a client-supplied
value in the security filter — safe, since the tenant would still be ANDed in from auth, but
the same *shape* as the bug being fixed. Collapsing leaves the filter derived entirely from
the authenticated identity, with no request-supplied component at all. That is a stronger
invariant and a much harder one to regress. If per-project scoping is ever wanted, add a
`workspace_id` then; it is a metadata addition plus one filter condition.

### The shared corpus, removed 2026-08-03

`GLOBAL_TENANT = "global"` used to tag a curated set of six arXiv papers, readable by every
tenant and owned by none, with `uuid7().hex` real ids guaranteeing no tenant could be issued that
value. It is gone, at the user's call, and the reasoning is worth keeping because the tradeoff was
real in both directions.

**What it bought.** Zero-setup demo value: clone, start, ask a question, get a cited answer. For a
portfolio that is not nothing — it is the difference between a reviewer seeing the system work and
a reviewer having to find a PDF first.

**What it cost, and why that won.** A permanent exception in the one sentence that matters most
about this system. Isolation was not "a tenant reads its own documents"; it was "a tenant reads its
own documents **plus global**", and every explanation of the boundary had to carry that footnote.
Concretely, it meant `_build_filter` matched `MatchAny([global, caller])`, and a list of permitted
tenants is a shape that invites a second element. It also forced a *second* registry query
(`list_scope_candidates`) whose only reason to exist was the corpus — and the two queries
disagreed, producing a 404 on every document the docs told callers to name.

**What replaced it.** One tenant, matched with `MatchValue`. `tenant_id` is required everywhere,
with no default: the old default *was* `GLOBAL_TENANT`, and once the corpus is gone any default
would silently file one tenant's data under another name. `_build_filter` raises on an empty
tenant rather than building a filter with no tenant condition, which is what the previously-safe
`tenant_id=None` ("corpus only") would have degenerated into.

**What it costs us going forward, stated rather than discovered.** A fresh install answers nothing
until someone uploads. And Epic 2's golden set now has no fixed document set to measure recall
against, so that has to be rebuilt as tenant-owned fixtures before any retrieval metric exists —
recorded in the README's known-gaps list.

## Authentication: database-backed API keys

**Decision.** `tenants` + `api_keys` tables; an `x-api-key` header resolved to a tenant by a
FastAPI dependency. Modelled on the Anthropic Console: the tenant boundary belongs to the
key's owner, so the server *derives* identity rather than trusting the client to assert it.

**Keys are hashed with SHA-512, deliberately not argon2/bcrypt.** Slow KDFs exist to make
brute-forcing *low-entropy* secrets expensive. An API key here is 256 bits of
CSPRNG output — there is no guessable structure to attack, so a KDF would add
latency to every authenticated request while buying nothing, and it would break the indexed
single-row lookup by requiring a per-row salt and a scan. Passwords are the opposite case;
Phase 5's login path must use argon2id.

**Expiry is a separate column from revocation, and `NULL` means never.** Collapsing the two
into one timestamp would make "did a human kill this key, or did it just lapse?" unanswerable,
and that is the first question asked after an incident. `NULL` had to mean *never* rather than
*immediately*, or adding the column would have expired every key minted before it existed.

The check lives in the `WHERE` clause next to the revocation check, not in Python after the
fetch. Two reasons, both about failure modes rather than performance: a dead key stays
indistinguishable from an unknown one, because both simply return no row and there is no
branch that could later grow a distinguishing error message; and `func.now()` is the
*database's* clock, so a skewed application server cannot honour a key past its deadline. With
several api processes, "expired" has to mean one thing. A test expires a key by one
millisecond, which only a clock can reject.

**Expiry defaults to 30 days, from a fixed menu of 30/60/90/365/never.** It shipped opt-in
first, with the CLI merely stating the choice out loud; that was the wrong default, because a
forever-key is the one people create by omission rather than on purpose. Both policies are
defensible — only one of them is safe as the value you get by not thinking about it.

The menu is a fixed set rather than a free integer, in both the API (`Literal[30, 60, 90,
365] | None`) and the CLI (`choices` built from `EXPIRY_CHOICES`). An arbitrary
`--expires-in 4000` is not a lifetime anyone chose; it is a typo that reads as a decision. The
two spellings exist because a `Literal` is what puts a real enum in the OpenAPI schema, and
`test_key_expiry.py` holds them together so they cannot drift.

**The API key is declared as an OpenAPI security scheme, not just accepted as a header.** A
plain `Header()` parameter authenticates identically, so nothing at runtime distinguishes the
two — but an `APIKeyHeader` emits a `securitySchemes` entry and a per-operation `security`
requirement, which is what turns the key into a client-level credential in a generated client
and an Authorize button in `/docs`. A bare header becomes a parameter every call site must
remember to pass. The Phase 6 React client is generated from this schema, so the difference is
the contract, and three tests pin it. `auto_error=False` because FastAPI's built-in rejection
is a 403 with its own wording; every failure mode has to reach the same 401, or an absent key
becomes distinguishable from an invalid one by status code alone.

**Key format: `pf_live_` + 43 base62 chars + a 6-char CRC32.** Drawn from GitHub's 2021 token
redesign and the Stripe prefix convention, and each part earns its place for a different
reason.

The *prefix* is the industry-standard move and the one with the biggest payoff: GitHub
replaced 40-char hex tokens precisely because they were "indistinguishable from other encoded
data like SHA hashes", and reported the prefix alone taking secret-scanning false positives
down to 0.5%. `pf_live_` is what `.gitleaks.toml`'s rule matches on.

*Base62 rather than base64url* is a smaller point but free: base64url's alphabet includes `-`,
which terminates a double-click selection in most editors and terminals, so a user copying a
key that way silently gets a fragment and an opaque 401. Underscore does not break the
selection — GitHub's stated reason for choosing it as their separator.

The *checksum* is the part worth arguing about. GitHub's rationale is secret-scanning
precision, and that argument is weaker here: their problem was hex tokens no scanner could
find, whereas `pf_live_` is already distinctive. What earns it a place is offline rejection —
`looks_like_key` now refuses a mistyped or fabricated key without a database round-trip, with
a 1-in-2³² false-accept rate. **It is an integrity check and never a security control.** CRC32
is not cryptographic; anyone can compute a valid checksum for a string they chose. It says
"not mistyped", never "issued by us", and a test pins that reading so nobody upgrades it in
their head.

Everything else those sources recommend was already in place and is worth recording as
confirmation rather than change: CSPRNG entropy (they suggest 128 bits, this uses 256),
hash-only storage, show-once, a stored display prefix, an indexed unique hash column,
`last_used_at`/`revoked_at`, revocation as a timestamp rather than a delete, and per-key rate
limiting. Two of the three explicitly endorse the no-bcrypt reasoning below. Zuplo raises
constant-time comparison and then notes it does not apply when the comparison is an indexed
database lookup — which is what this does; `hmac.compare_digest` would be required only if
digests were ever compared in application code. Rotation with a grace period already works,
because a tenant may hold several live keys: mint the new one, move clients over, revoke the
old. The two genuine gaps they surfaced — **key expiry** and **scopes** — have both since been
built; see below.

**SHA-512 rather than SHA-256 is margin, not a fix, and the function is now frozen.** What
protects a stolen `key_hash` is the input entropy — 256 bits of CSPRNG output is not
invertible under either function — so the wider digest buys cryptanalytic reserve rather than
closing a gap. It cost ~0.25 µs per authentication and 64 characters per row, both negligible,
and it was taken while `apikey` was **empty**: because the plaintext keys are deliberately not
stored, no digest can ever be recomputed, so changing the hash invalidates every key at once.
Free at zero rows, a full re-key at any other time. `test_the_hash_function_is_frozen` pins a
known key to its exact digest so the change cannot pass as a green suite.

Two alternatives were rejected while making that choice. **SHA-512/256** is the better fit on
paper — 256-bit output, immune to length extension — but is not in `hashlib.algorithms_
guaranteed`; it comes from OpenSSL, so a rebuild against a trimmed OpenSSL would break
authentication everywhere simultaneously. That is an unacceptable dependency for a persisted
digest. **SHA-3** is guaranteed and sponge-based, but measurably slower here for a property we
don't rely on: length extension requires an `H(secret ‖ message)` construction, and this
hashes a whole key and compares digests.

**Many keys per tenant, revoked individually.** Hence a separate table rather than a column on
`Tenant`: one tenant holds a laptop key, a CI key, a prod key, and revoking one must not
disturb the others. Revocation is a timestamp, not a delete, so "was this leaked key ever
used?" remains answerable.

**Rejected — static keys in `Settings`.** No rotation, no per-key revocation, and a key in
env is unrevocable by definition.

**A dependency, not middleware.** The build plan called for `api/middleware/auth.py`, which
names the wrong mechanism: middleware cannot be overridden per-route in tests, cannot declare
itself in the OpenAPI schema, and would have to reimplement path matching to skip
unauthenticated routes. `api/deps.py` gets all three for free.

**Streamlit authenticates too**, for a non-obvious reason: it calls the pipeline *in process*,
so the FastAPI dependency never runs for it. It prompts for a key and resolves it through the
same `auth.service.resolve_tenant` — one auth implementation, not two — rather than minting a
tenant id as it originally did.

## Scopes: a set on the key, checked per route

**Decision.** Five strings — `ask`, `documents:read`, `documents:write`, `keys:read`,
`keys:write` — stored as a Postgres `ARRAY` on `apikey`, checked by a `require_scopes(...)`
dependency declared on each route.

**Deliberately five.** A scope list you can hold in your head is one people use correctly; a
taxonomy is one people paste from an example and stop reading. `keys:*` exist because key
management is a capability like any other — without them any key could mint any other, and the
whole vocabulary would be decorative.

**An empty list means *every* scope, not none.** This is the load-bearing decision and the one
most likely to be "corrected" by someone reading `if not key.scopes` as a denial. Keys minted
before the column existed have no list; the other reading would have revoked all of them the
moment it shipped. Same rule as `expires_at IS NULL` meaning never: absent data must mean the
pre-existing behaviour, or adding a column becomes an outage. The cost, stated because it is
real, is that "unrestricted" and "not yet configured" are the same value — acceptable while
keys are minted by a human who sees the list, and fixable with a NOT NULL default if they ever
aren't.

**A `ARRAY` column, not a join table.** The set is tiny, fixed, and read on every authenticated
request, so a second query to assemble a five-element list would be pure overhead. It is also
never queried *by* scope — the question is always "what may this key do", never "which keys may
do X" — and that query shape is the one that would justify normalising.

**403 for a missing scope, 404 for another tenant's resource.** Everywhere else in this API an
authorization failure is a 404, to avoid confirming that someone else's resource exists. Scopes
are the deliberate exception: the caller *is* authenticated and *is* entitled to the tenant,
they simply hold the wrong capability, so naming the missing scope tells them only about their
own key. Hiding it produces a client retrying forever against a 404 it cannot fix.

**Scopes hang off the key, not the tenant.** The tenant decides what data is reachable — that
is the retrieval filter, and it is not negotiable per key. A scope decides what the holder may
do with it.

**A key may only grant scopes it already holds.** Without that guard, `keys:write` is
equivalent to every scope: a narrow key mints a wide one and promotes itself. The subtle half
is that an *omitted* scope list cannot be stored as-is — empty means unrestricted, and
`exceeds([], holder)` is vacuously satisfied, so the guard never sees it. `POST /v1/keys`
therefore materialises an omitted list into the caller's own scopes.

**Declared per route, like `CurrentTenant`, with the same consequence:** a route that forgets
one is reachable by any key and nothing raises. `require_scopes` attaches its requirement to
the returned closure so `test_scopes.py` can walk the route table and fail on any `/v1` route
with no requirement — the assertion a newly added route silently falsifies.

## Rate limiting: the `limits` library on redis-py

**Decision.** A sliding-window limiter in `app/rate_limit.py`, per **key** and per scope.

**Per key, not per tenant.** Once keys differ in capability, a CI key hammering uploads should
not exhaust the budget of the dashboard key beside it — with one shared bucket that becomes a
support ticket about the wrong component. **The consequence, stated because it is real:** a
tenant holding N keys now has N times the budget, so this is a fairness device between clients
and not a cost ceiling. Making it a ceiling means a second bucket keyed on `tenant_id` checked
alongside this one — two Redis round trips instead of one, recorded in `docs/IDEAS.md` rather
than built, because nothing here bills by request today.

**`slowapi` was planned and was re-examined once the hand-rolled version was running**, on the
fair objection that a battle-tested library beats 124 lines of ours. The re-examination did not
change the decision, but it did correct two things this document previously got wrong, and the
corrections matter more than the verdict.

*What was wrong.* The claim was "uv reports the resolution as unsatisfiable". That holds only
when `limits` is pinned: `limits[redis]>=5` requires `redis>3,<8.0.0` against this project's
`redis[hiredis]>=8.0.0,<9.0.0`, and uv does refuse that pair. But asking for `slowapi`
**unpinned** resolves happily — to `limits==1.6` and `slowapi==0.1.6`, releases from 2018 and
2022. A silent decade-old downgrade is a worse outcome than an error, and it is what anyone
casually running `uv add slowapi` would get. The stated pin was also wrong (`>=8.0.1`; it is
`>=8.0.0`).

*What the real cost is.* `slowapi` 0.1.10 has **no async storage path**. `extension.py` imports
`limits.storage` and `limits.strategies` — the synchronous modules — and calls
`self.limiter.hit(...)` inline in the request path. So the Redis round trip blocks the event
loop. Measured against localhost Redis, steady state, best of five rounds:

| concurrent checks | async (ours) | sync (slowapi's path) |
|---|---|---|
| 1 | 0.36 ms | 0.32 ms |
| 10 | 1.20 ms | 3.42 ms |
| 50 | 5.09 ms | 12.99 ms |
| 100 | 11.05 ms | 21.41 ms |
| 200 | 18.48 ms | 65.51 ms |

Single-request latency is a wash — slowapi is marginally *faster*, having no event-loop
overhead. The cost is head-of-line blocking, roughly 2–3.5× wall time under concurrency, and it
scales with Redis RTT: on localhost the blocked interval is ~0.3 ms, on a managed Redis one hop
away it is 1–5 ms per request, during which nothing else on that worker runs.

*What slowapi would genuinely do better.* Three things, and they are real. It emits
`X-RateLimit-Limit`/`-Remaining`/`-Reset` alongside `Retry-After` where we emit only
`Retry-After` — though `headers_enabled` defaults to **False**, so out of the box its 429
carries no headers at all. It has an `in_memory_fallback` mode, which degrades to partial
protection when Redis dies rather than to none as our fail-open does. And its `limits` backend
is far more exercised than ours, which is the whole of the argument for it.

*What it would cost beyond the blocking.* A redis-py major downgrade to 7.x (everything else
resolves at current versions). `key_func(request)` only sees the Request, so the principal
would have to be stashed on `request.state` again — a mechanism deliberately removed when
authorization moved into a dependency. Its default 429 body is `{"error": ...}` rather than
this API's `{"detail": ...}`, so a custom handler is required to keep the contract. Only the
decorator form can be used, not `SlowAPIMiddleware`, since middleware runs before dependencies
resolve and there would be no principal yet.

*Not a differentiator:* the algorithm. `limits`' sync Redis storage implements
`moving-window` with its own Lua scripts, so `strategy="moving-window"` is semantically
equivalent to ours. slowapi's default is `fixed-window`, which is the weaker choice — a caller
can spend a full budget at the end of one window and again at the start of the next.

*The library that should have been evaluated instead of slowapi: `limits` on its own.* slowapi
is a thin FastAPI wrapper over `limits`; `limits` is the engine (98 releases, also behind
flask-limiter) and it is the part that is actually well exercised. Evaluated properly, it turns
out **`limits` runs fully async on redis-py 8** — the blocker attributed to it was slowapi's,
not its own:

```python
RedisStorage("async+redis://...", implementation="redispy")  # not the coredis default
```

`limits.aio.storage.redis` ships four bridges (`coredis`, `redispy`, `valkey`, cluster) and the
redis-py one requires `redis>=5.2.0` **with no upper bound** — the `<8.0.0` pin is on the
*synchronous* `redis` extra only. So no downgrade, no coredis, no third redis client. Verified
against live Redis with `MovingWindowRateLimiter`, and the performance is a dead heat with ours:

| concurrent | ours | `limits` async (redispy) |
|---|---|---|
| 1 | 0.36 ms | 0.45 ms |
| 10 | 1.20 ms | 1.23 ms |
| 50 | 5.09 ms | 5.02 ms |
| 100 | 11.05 ms | 11.11 ms |
| 200 | 18.48 ms | **`MaxConnectionsError`** |

Two real costs. `hit()` and `get_window_stats()` are **two** round trips, where our script
returns `allowed`, `remaining`, and `reset` from one — and two calls means the header describes
a different instant than the decision. And at 200 concurrent the default pool for the basic
redispy bridge raised `MaxConnectionsError: Too many connections` rather than queueing
(`max_connections=1000` is the *cluster* default only); ours completed. Configurable, but it is
the kind of ceiling you find in production rather than in the docs. Everything HTTP-shaped —
the dependency, the 429, the headers — is still ours to write either way, which is most of what
`deps.rate_limited` already is.

*Where `limits` wins, measured 2026-08-03 and not part of the original comparison.* The above
benchmarked `MovingWindowRateLimiter`, matching our exact semantics. `limits` also ships
`SlidingWindowCounterRateLimiter`, an *approximation* — it weights the previous window's count
rather than tracking individual requests — and it is dramatically cheaper in Redis. Per key,
after 60 requests, `MEMORY USAGE`:

| implementation | Redis type | bytes |
|---|---|---|
| `limits` SlidingWindowCounter | string | **120** |
| `limits` MovingWindow | list | 1464 |
| ours | zset, 32-char uuid members | **3120** |

At 10k tenants × 2 scopes with keys near their limits that is ~62 MB against ~2.4 MB — on a
16 GB box it is not fatal, but it is the first argument for `limits` that our own numbers
support. Note where the 26× actually comes from: `limits`' own *exact* moving window costs
1464 bytes for the same 60 requests, so more than half our overhead is the uuid member, not
the algorithm. A shorter unique member is a cheaper fix than a rewrite and keeps one round
trip, exact windows, fail-open and the headers. Parked in `docs/IDEAS.md`.

*Also re-confirmed at the same time, since a decision is only as good as its facts.*
`slowapi` 0.1.10 (2026-06-13) still imports `limits.storage`/`limits.strategies` and still
calls a bare `self.limiter.hit(...)` at `extension.py:514` — checked in the published wheel.
`limits[async-redis]>=5` and `redis[hiredis]>=8,<9` **do** resolve together (coredis 5.7.0
alongside redis 8.1.0), and with `implementation="redispy"` coredis is not needed at all. The
`MaxConnectionsError` ceiling reproduces with the counter strategy too, so it is a property of
the storage bridge and not of the strategy. And `limits` fails **closed**: an unreachable
Redis raises `redis.exceptions.ConnectionError` straight out of `hit()`, so adopting it means
writing the fail-open wrapper ourselves — the opposite of the usual "the library handles it".

*The rest of the survey.* `fastapi-limiter` 0.2.0 (2026-02) is the only other maintained,
async-native, redis-8-compatible option: it delegates to `pyrate-limiter` 4.x, which has a real
Lua-backed Redis bucket. It was rejected on two specifics. Its default 429 is a bare
`HTTPException(429, "Too Many Requests")` — no `Retry-After`, no `X-RateLimit-*`, and
`try_acquire_async` returns a bool, so a custom callback has nothing to compute them from. And
its bucket key is `f"{rate_key}:{route_index}:{dep_index}"` where `route_index` is the
**position of the route in `app.routes`**, found by a linear scan on every request: inserting a
route above `/v1/ask` silently changes the identity of every existing bucket.

Everything else was dead or inapplicable: `asgi-ratelimit` (last release 2022), `ratelimit`
(2018), `aiolimiter` (in-process only, so useless across gunicorn workers), `throttled-py`
(active, but pins `redis<8.0.0` exactly as `limits[redis]` does). There is no commercial Python
package in this space — the "enterprise" answer is a *gateway*: Kong, Zuplo, AWS API Gateway
usage plans, or Cloudflare, all of which rate-limit ahead of the app and none of which know
about API-key scopes. `redis-cell` (a GCRA Redis module) would move the algorithm into Redis
itself, at the cost of a non-default module in the image.

*Verdict, superseded: `limits` was adopted on 2026-08-03.* The reasoning above is kept because
every fact in it still holds — what changed is the weighting, and by the user's call after the
tradeoff was laid out. "One round trip instead of two" is a latency argument on a path that was
never the bottleneck, and shedding ~45 lines of Lua plus a sorted-set expiry contract onto a
library with 98 releases is worth two round trips.

**The memory argument that first justified it was framed wrongly, and is corrected below.** It
compared `limits`' *cheapest* strategy (120 bytes/key) against *our* implementation (3120) and
called it 26×. Like for like — exact against exact — `limits`' `MovingWindowRateLimiter` costs
1464 bytes, so the honest figure is **2× cheaper than the ZSET**, not 26×. That mattered, because
the 26× bought a strategy that was wrong.

*What adoption actually cost, since "use the battle-tested library" undersells it.* `limits`
supplies the counting and has no opinion about anything else, so all of the following stayed
ours and every one of them had to be re-established rather than inherited:

1. **Fail-open.** `limits` fails *closed* — an unreachable Redis raises
   `redis.exceptions.ConnectionError` out of `hit()`. Without the `except` in `check`, a Redis
   blip becomes a 500 on every request. Both `hit` and `get_window_stats` are inside one `try`,
   and there is a test for a failure *between* them: `hit` succeeding then stats failing would
   otherwise 500 a caller whose budget was already spent.
2. **`X-RateLimit-Reset` had to be corrected, not just forwarded.** `limits` stores the counter
   with a TTL of twice the window and derives the reset as `current_expires_in % expiry`. That
   is right inside the window — at t seconds in, `(2w - t) % w == w - t` — and **wrong at the
   instant one opens**, where `120 % 60 == 0`. So the first request against a fresh key was told
   `X-RateLimit-Reset: 0`: retry now, with a budget already spent. For a low-traffic key that is
   the common request. `_reset_seconds` clamps it; a test pins the clamp and goes red without it.
3. **`max_connections` had to be set.** `limits` defaults it to **100** and its pool raises
   `MaxConnectionsError` rather than queueing — the ceiling this document already recorded at
   200 concurrent, now explained rather than just observed. Reproduced with both the moving
   window and the counter, so it is the storage bridge, not the strategy.
4. **Per-event-loop storage.** Every `limits` example is a module-level
   `storage_from_string(...)`. That binds a `redis.asyncio` pool to whichever loop imported it,
   which this project has already been bitten by: Streamlit's script model and per-test loops
   both produce a client attached to a closed loop.
5. **Precision genuinely lost.** `remaining` now comes from a second round trip, so under
   concurrency it can disagree with what the next request is granted. The concurrency test used
   to assert the grants reported distinct `remaining` values counting down to zero; that
   assertion is deleted, not weakened, and the reason is written where it was.
6. **The strategy had to be chosen twice.** `SlidingWindowCounterRateLimiter` shipped first, on
   the memory number, and was replaced by `MovingWindowRateLimiter` the same day — see the next
   section. An earlier version of this list closed by saying `Retry-After` had merely become
   "conservative rather than tight — never shorter, which is the safe direction". That was
   **false** under the counter, and it took measuring to find out.

### The strategy: `MovingWindowRateLimiter`, chosen the second time

`SlidingWindowCounterRateLimiter` was used for one day, on the memory argument, and the entry
above should have been suspicious of an approximation adopted to save 27 MB on a 16 GB box. It
was replaced once the approximation was measured rather than reasoned about, and the measurement
is worth keeping because the failure is invisible from the API's shape:

| after spending a 10-request / 2-second budget | told to wait | granted after waiting 2.2 s |
|---|---|---|
| `MovingWindowRateLimiter` | 2.00 s | **10 / 10** |
| `SlidingWindowCounterRateLimiter` | 2.00 s | **2 / 10** |

Both advertise the same `Retry-After`. Only one honours it. The counter weights the *previous*
window's count instead of expiring individual requests, so a client that waits exactly as long as
it was told still gets a 429 — and does not recover its full budget until 4.2 s, twice the
window. The natural client-side reaction to "I waited and was refused anyway" is a tight retry
loop, which is the specific failure the sliding-window choice exists to prevent in the first
place.

It also reported `X-RateLimit-Reset: 0` on the first request against a fresh key
(`current_expires_in % expiry` = `120 % 60`, against a TTL of twice the window), which needed a
clamp in `_reset_seconds`. The exact strategy reports a full window there, so the clamp was
deleted rather than kept as defensive-looking dead code.

**Two tests hold the line, both measured red in 5 of 5 mutation runs** with the counter
reinstated: `test_the_full_budget_returns_after_the_advertised_reset`, and the `1x`-vs-`2x` TTL
bound in `test_window_expiry_is_set_so_buckets_do_not_leak` (the counter must retain a window
twice as long, to weight it as "previous"). A third,
`test_a_fresh_window_advertises_a_full_window_not_zero`, is red in only **8 of 10** — the modulo
lands on zero only when the first hit falls within a millisecond of the window opening — so it is
documented as a hint, not a guard.

The cost is 1464 bytes per key against the counter's 120: ~29 MB against ~2.4 MB at 10k tenants ×
2 scopes. `FixedWindowRateLimiter` is cheaper again and wrong for the original reason — a caller
straddles the boundary and spends two budgets back to back.

*Net:* the counting is a library's problem now, the policy is still ours and is where all four
historical bugs lived, and two of the five items above were bugs found *during* the swap that
the old implementation did not have. Revisit if the approximation ever shows up as a real
over- or under-count, or if cluster/sentinel/GCRA is needed — all of which `limits` now brings
for free.

**Sliding window, not fixed.** A fixed window lets a caller spend its entire budget at the end
of one window and again at the start of the next — an observed burst of twice the configured
limit.

**The count must be atomic**, however it is implemented. A read-then-write version lets concurrent
requests all observe a count below the limit and all proceed, which is the exact scenario rate
limiting exists to prevent. A test fires 25 concurrent requests at a limit of 5 and asserts exactly
5 pass. This was a hand-rolled Lua script until 2026-08-03; `limits` now owns the atomicity, which
is the one part that was never the problem here.

**Keyed per API key**, not per tenant and not per IP — an IP key punishes shared corporate egress
and is trivially evaded, and a tenant key lets one client exhaust another's budget (see § Per key,
not per tenant above; this paragraph said "per tenant" and contradicted it). **Per scope** too, so
exhausting the upload budget does not also block questions.
Uploads get a much tighter budget (10/min vs 60/min) because they cost Docling CPU plus one
Anthropic vision call per figure plus one Voyage embedding call per chunk; `/ask` is a
retrieve, a rerank, and one generation.

**Counters live in Redis, not memory**, because in-process counters are per gunicorn worker —
with N workers the real limit becomes N times the configured one.

**Fails open.** Unreachable Redis allows the request and logs a warning: a guardrail's outage
must not become the API's outage. The tradeoff is that protection disappears exactly when
load may be why Redis is struggling, which is why the log is loud and why `docker-compose.yml`
gates `api` on redis being healthy — otherwise the gap would be silently open at startup.

## Secrets in Settings, and the config comments that moved here

**Decision.** Every credential on `Settings` is a `SecretStr`. Not defence in depth for its own
sake -- it closes one specific, easy accident. That object holds a live Anthropic key, a Voyage key,
a LangSmith key and the Postgres password, so anything rendering it renders all four: a
`log.info(..., settings=settings)` while debugging, a `repr()` in a traceback frame a crash reporter
serialises, an exception from `model_validator` quoting the model. `SecretStr` prints `**********`
for all of those, and **this repository is public**, so a key reaching a log someone pastes is
disclosed the moment it is pasted.

The cost is that code genuinely needing the characters says `.get_secret_value()`, which is a
readable marker of exactly where a secret escapes. **Grep for it; do not trust a count.** A count
lived in `config.py` claiming eight and naming four, and it was wrong in both halves -- a number
nobody can reconcile is worse than no number, because the reader assumes the list is the stale part
and the count is right.

The provider clients need no change: `ChatAnthropic.anthropic_api_key`,
`VoyageAIEmbeddings.voyage_api_key` and `VoyageAIRerank.voyage_api_key` are declared `SecretStr`
themselves (verified against the installed packages), so passing these through removes a coercion
rather than adding one.

### Why this section exists

`app/config.py` carried 99 comment lines against 270 of code, and an external review named the
density as the main thing harming maintainability: "reviewers must read historical incident reports
to understand small functions". The rule the comments were trimmed against is the repo's own rule 15
-- *a comment records the failure, not the mechanism*, and not the history of how the mechanism
arrived. So each one kept the sentence saying what breaks, and the narrative around it landed here.

Nothing was deleted outright. What moved:

- **`figure_caption_concurrency`** was ingestion's sequential stage: a 15-figure paper meant 15
  Anthropic round-trips back to back, which no amount of CPU touches. Bounded rather than unbounded
  because the ceiling is Anthropic's rate limit and a 429 storm is slower than running serially.
- **`figure_min_dimension_px = 64`** came from a real one-page CV that yielded five "figures", all
  ~20x20px icons; each cost a vision call and became a retrievable chunk, and the vision model
  answered each with "I'm not able to see the image", which then *won reranking*.
- **`db_pool_size`/`db_max_overflow`** are sized for one gunicorn worker's own engine --
  `--preload` does not eagerly open a connection, so pools are not shared across forks.
- **`docling_num_threads`** reuses Docling's own `DOCLING_NUM_THREADS` (its `AcceleratorOptions` is
  a `BaseSettings` with `env_prefix="DOCLING_"`), so one value configures both paths instead of two
  competing knobs. Docling's own default of 4 leaves most of a modern box idle during layout and
  table inference, which is the CPU-bound bulk of ingestion.
- **`worker_concurrency` was once a field** here, read by nothing, whose default coincidentally
  matched the worker CMD's `${WORKER_CONCURRENCY:-2}` fallback -- so the two agreed by accident and
  a `.env` change would have moved only one. Deleted; the CMD is the single source.
- **CORS defaults** drifted from the original hardcoded `CORSMiddleware` call as `DELETE` and the
  rate-limit `expose_headers` were added. `DELETE` is there because revocation is the first thing a
  browser client needs and the one call nobody wants to debug under pressure.
- **`redis_max_connections`** was added after measuring `limits` 5.8.0's default of 100 and its
  `MaxConnectionsError` on exhaustion rather than queueing.
- **`manifest_path` and `raw_pdf_dir`** pointed at `data/manifest.json` and the PDFs
  `scripts/fetch_corpus.py` downloaded; both went with the curated corpus (2026-08-03).

## Async design: where it helps and where it doesn't

The `/ask` path is genuinely I/O-bound end to end (Qdrant, Voyage, Anthropic) and is async
throughout. Ingestion is not, and treating it as though it were would have been worse than
leaving it synchronous.

`ingest_document` is `async def`, but Docling parsing is **CPU-bound**: marking it async
would not free the event loop, it would just hide the blocking behind a coroutine. It goes
through `asyncio.to_thread`, as does the Qdrant client's synchronous `upsert`. Without that,
one slow upload stalls every other request on the same worker.

**Figure captioning is the sequential stage that CPU tuning cannot fix.** It is one Anthropic
call per figure — a 15-figure paper meant 15 back-to-back round trips. It now goes through
`llm.batch` with a bounded `max_concurrency`; the ceiling is Anthropic's rate limit, not local
cores, so the bound is deliberate rather than unlimited.

Worth stating plainly: of the six stages in an ingest, only two are CPU-bound. The ceiling on
hardware tuning is lower than it looks.

## Ingestion latency: mostly not inference

The first upload appeared to take two minutes of "inference". Most of it was **model
downloads** — Docling fetches its layout model, table-structure model, and RapidOCR weights
on first use, and with no cache volume that repeated on every container recreate. The
Dockerfile now points `XDG_CACHE_HOME`/`HF_HOME`/`TORCH_HOME` into one directory that
docker-compose mounts as a named volume.

`AcceleratorOptions` also defaults to `num_threads=4` regardless of host core count, so a
multi-core box ran the layout and table passes at a fraction of capacity. It now defaults to
`os.cpu_count()`, overridable via `DOCLING_NUM_THREADS` — the same env var Docling's own
settings read, so one value configures both paths.

`device` is left at `"auto"`: Docling already probes cuda/mps/xpu and falls back to cpu, so
pinning a device could only downgrade the result.

**`do_ocr=False` was considered and rejected as a default.** Docling's OCR is already
selective (`force_full_page_ocr` defaults to `False`), so on born-digital papers the OCR
*inference* barely runs — nearly all of what it cost was the model download the cache volume
now fixes. Meanwhile disabling it would make scanned PDFs ingest as silently empty and break
direct image uploads, which the format allowlist permits.

## Serving: gunicorn with UvicornWorker

**Decision.** `gunicorn` + `uvicorn.workers.UvicornWorker`, not bare uvicorn.

Process supervision and multi-worker serving, with `gunicorn[http2]` already a dependency.
`UvicornWorker`'s own `CONFIG_KWARGS` defaults to `loop="auto"`, so uvloop is still picked up
per worker — no separate loop flag needed.

`--preload` shares the heavy import graph (Docling, LangChain, torch) across forked workers
via copy-on-write. This is only safe because nothing opens a connection at import time: the
`@lru_cache`d store and service getters construct their clients on a worker's first request,
after the fork. The Redis client is likewise created lazily and cached **per event loop** —
a `redis.asyncio` client binds its pool to the creating loop, so a process-wide singleton
breaks under repeated `asyncio.run()`.

## Deployment: `.docker/` and one source of truth for the port

Infra config lives in `.docker/` (Dockerfile and docker-compose.yml together), with `redis/`
as a sibling build context and `nginx/` nested inside `.docker/`.

**`PORT` is the single source of truth** for the api port: gunicorn's `--bind`, the compose
port mapping, and nginx's upstream all derive from it. nginx's is baked in at image build time
by a `sed` on an `__API_PORT__` placeholder — deliberately *not* nginx's `envsubst` templates,
which substitute every `$`-prefixed token and would happily blank nginx's own `$scheme` and
`$remote_addr` throughout the file. `GUNICORN_TIMEOUT` and `MAX_UPLOAD_SIZE_MB` reach nginx
the same way, as `REQUEST_TIMEOUT`/`MAX_UPLOAD_MB` build args, and the nginx image's build
fails if any `__PLACEHOLDER__` is left unsubstituted — a literal `__FOO__` in an nginx
directive is a config parse error, i.e. a crash-loop to debug instead of a build error to read.

**That single source of truth requires `--env-file`**, which is not obvious and was wrong
until it was measured:

    docker compose -f .docker/docker-compose.yml --env-file .env up      # from portfolio/

Compose resolves `${VAR}` from the shell or from a `.env` in the *project directory* — which
is `.docker/`, not `portfolio/` and not the cwd. Verified both documented invocation styles
with a value set only in `portfolio/.env`: **both silently used the fallback default.** A
service's `env_file: ../.env` is a different mechanism (it populates a container's
environment) and does not feed substitution.

The failure is worse than a wrong default because the halves disagree. `PORT=9000` in
`.env` alone yields gunicorn bound to 9000 *inside* the container, a published mapping of
`8000:8000`, and an nginx upstream pointing at `api:8000` — three values, one correct, no
error anywhere. This is the same class of bug as the postgres healthcheck reading the
fallback password while the container ran with the real one.

**Timeouts are wired together rather than set independently.** nginx's `proxy_read_timeout`
derives from the same value as gunicorn's `--timeout` (600s), because whichever is shorter
silently becomes the real budget: nginx first gives a 504 while the worker keeps burning CPU
on an abandoned request; gunicorn first SIGKILLs the worker mid-parse, so the client gets a
bare connection failure that never names the timeout. `proxy_connect_timeout` is deliberately
*not* wired to it and stays at 75s — nginx documents that this one "cannot usually exceed 75
seconds", so the 315s previously configured there was never real.

`client_body_timeout` was 32s and is now also 600s. It bounds the gap between reads of the
request body, and 32s kills real uploads from a phone on mobile data — a 408 that reads as a
server fault. **It is the one timeout an async job queue will not make irrelevant**: the bytes
still have to arrive over the wire regardless of what processes them afterwards. The 600s
gunicorn timeout, by contrast, is a stopgap for synchronous ingestion and should come back
down once uploads are jobs (`docs/EPIC_4_PLAN.md` 5.1) — a 10-minute worker timeout means one
stuck request holds a worker for ten minutes.

`client_max_body_size` derives from `MAX_UPLOAD_SIZE_MB` for a related reason: nginx enforces
it *first*, so if it were the smaller of the two the app's own limit would be dead code and
raising `MAX_UPLOAD_SIZE_MB` would appear to do nothing — every oversized upload getting a
413 from nginx that looks exactly like the app's own 413.

## CORS: wildcard origins and credentials are mutually exclusive

`Settings` refuses to construct when `cors_allow_credentials` is true and `cors_allow_origins`
contains `"*"`. Starlette does not reject that pair, and what it does instead is the problem —
from `starlette/middleware/cors.py` (1.3.1):

```python
if self.allow_all_origins and self.allow_credentials:
    self.allow_explicit_origin(headers, origin)
```

It reflects back whatever `Origin` the caller sent, alongside `Access-Control-Allow-Credentials:
true`. A literal `Allow-Origin: *` would at least make browsers refuse to attach cookies;
reflecting the origin tells the browser that this specific attacker's site is trusted. Any page
on the internet could then call the API with the victim's session cookie and read every
document and conversation. There is no partial version of this mistake.

The wildcard default is inert **today** and the guard exists so it can't stop being inert
quietly: `cors_allow_credentials` is false and `cors_allow_headers` is empty, so a browser
can't attach `x-api-key` cross-origin, the preflight fails, and nothing authenticated is
reachable. The moment Phase 5 adds cookie sessions that changes, which is exactly when
someone flips credentials on without revisiting origins.

Raised at construction rather than logged, because nothing looks wrong from the server's
side — it serves correct responses, and the damage is only visible from the attacker's page.
`tests/unit/test_cors.py` pins it, including a wildcard buried in an otherwise-explicit list
(`["https://app.example.com", "*"]` is exactly as open as `["*"]`, since Starlette checks
`"*" in allow_origins`).

## Job queue: procrastinate, replacing the planned arq

Not yet built — recorded here because the choice was made and the reasoning is the load-bearing
part. `arq` was the plan and is in **maintenance-only mode** upstream ("we'll continue to fix
critical security issues […] but don't expect work on new fixes"), so it's not abandoned but
isn't something to start new work on. Same call as `fastapi-users`.

All of `procrastinate`, `rq`, `celery`, `saq`, and `arq` resolve under `requires-python =
">=3.14"` with this project's pins (checked with `uv lock`, the method that caught the
`slowapi` conflict), so resolvability didn't decide it. `procrastinate` wins on:

- **Async-native**, matching `ingest_document` and the async SQLAlchemy engine. Celery and RQ
  are sync-first, so every job would wrap `asyncio.run(...)` and open a fresh event loop and
  connection pool per job.
- **Transactional enqueue.** Being Postgres-backed, the `DocumentRecord` row and its job commit
  together — there is no window where a document exists with no job (stuck "pending" forever)
  or a job with no row. With a Redis broker those are two systems and the gap is real.
- **No new infrastructure**: uses the existing Postgres through `psycopg` 3, already a
  dependency. Redis stays purely a rate-limit counter store, consistent with the existing
  "Redis is a cache, Postgres is the database" split.

The strongest argument against it is `rq`'s fork-per-job isolation, which would contain a
Docling segfault better than in-process async workers. Recorded rather than dismissed.
`taskiq` was excluded for declaring `Development Status :: 3 - Alpha` in its own metadata.

**Transactional enqueue does not work the documented way.** `procrastinate.contrib.sqlalchemy`
exists and is psycopg2-based and sync-only, so it is unusable against this project's psycopg 3
async engine. The path that works is `defer_async(connection=...)` with the raw
`psycopg.AsyncConnection` unwrapped from the session — `await session.connection()` →
`get_raw_connection()` → `.driver_connection`. Verified against a live Postgres before anything
was built on it: defer inside a transaction then roll back leaves 0 rows in
`procrastinate_jobs`; commit leaves 1.

**The producer defers by task name, not by importing the task.** `app/worker/app.py` carries no
`import_paths`, because `configure_task` calls `perform_import_paths()` first — so an
`import_paths` entry would make the *api* import `tasks.py`, and with it the ingestion pipeline
and Docling. Measured at ~10s inside the first upload request. The worker CLI is pointed at
`app.worker.tasks.app` instead, since importing that module is what registers the task. The
trade-off: a wrong task name is no longer an import error but a job no worker claims, so a test
asserts the registered name matches the shared constant.

Two costs of this choice, both real:

- procrastinate ships its own SQL migrations, and they are **not** Alembic's -- so adopting Alembic
  did not absorb them, and `migrations/env.py` has to exclude `procrastinate_*` or autogenerate
  writes `drop_table` for all four.
  The initial schema is applied from `init_db` behind a `to_regclass` existence check (its
  `schema.sql` uses bare `CREATE TABLE` and is not idempotent), chosen over a deploy step that
  fails as "relation does not exist" when forgotten. **Version upgrades still need
  `procrastinate schema --migrate`** — that is a boundary, not a solved problem.
- Postgres now serves both the registry and the queue. Fine at this scale (thousands of
  documents, not thousands of jobs per second), and worth revisiting only if queue throughput
  starts competing with application queries for the same connection pool.

**Capabilities are dropped and re-added minimally.** `cap_drop: [ALL]` removes root's
privileges too, because they are capability-gated rather than UID-gated. nginx needs
`NET_BIND_SERVICE` (port 80), `SETUID`/`SETGID` (dropping to `www-data`), and `CHOWN` — the
last one discovered only by running it: nginx's *master process* chowns `/var/cache/nginx`
even though the image's entrypoint scripts don't, and without it nginx crash-loops. Postgres
needs `CHOWN`, `SETUID`, `SETGID`, `DAC_OVERRIDE`, `FOWNER` to bootstrap a fresh volume.

**Compose project name is pinned** (`name: portfolio`), because otherwise Compose derives it
from the invoking directory and the same stack gets two identities depending on where you run
it from — which is how a stale container survives and collides on a published port.

## Keeping the ingestion stack out of the api process

Docling plus torch plus transformers is the heaviest thing this project imports. Once ingestion
moved to a worker, the api had no use for it — but two imports kept dragging it in anyway, and
neither was visible as a problem because nothing broke:

1. `app/worker/app.py`'s `import_paths` (see above), and
2. `app/ingestion/formats.py`, which derived its upload extension allowlist from Docling's
   `FormatToExtensions` mapping at import time.

The second is the more instructive one. Deriving the list reads as the *more* rigorous choice —
it can't go stale — and the README even advertised these helpers as "deliberately
dependency-free (no docling import)", which was false. Measuring `import app.api.main` with and
without it: **8.74s / 830MB → 6.78s / 673MB.**

The list is now pinned in the module, with a per-format drift check in
`tests/unit/test_upload_formats.py` — importing Docling in a test costs nothing. That also makes
the allowlist better on its own terms: it is a validation boundary on a public endpoint, and a
dependency bump should not silently widen what strangers may upload. Widening it is now an edit
someone makes on purpose.

A test asserts `app.api.main` imports no `docling*` module, because this regresses invisibly:
one convenience import in a router and the api is slow and fat again with nothing failing. The
test deliberately does *not* assert on torch/transformers — those arrive through
`langchain_core.language_models.base`, reached via `ChatAnthropic`, which `/ask` genuinely needs.
Traced rather than assumed, and not something this project can fix.

## Observability: LangSmith, not Phoenix

Every generation, retrieval, and rerank call is already a LangChain object, so tracing is
zero-code once `LANGSMITH_*` env vars are set. Running Phoenix alongside it would mean two
trace backends covering the same call graph. Phoenix is dropped from the plan rather than
layered on top.

## Python floor: 3.13, after 3.12 and 3.14

Three positions, in order, and the middle one was wrong in both directions.

`>=3.12` was the original floor and the code could not honour it: `uuid.uuid7()` is 3.14
stdlib and raises `AttributeError` below it. Raised to `>=3.14`, correctly at the time.

Lowered again to **`>=3.13`** once the justification was re-checked and found to be almost
entirely stale. The comment in `pyproject.toml` claimed `api/routers/documents.py` and
`streamlit_app/Home.py` called `uuid7()` for session ids; both call sites disappeared when
`session_id` became an auth-derived `tenant_id`, and nobody updated the comment. What
actually remained was **two calls in `scripts/create_tenant.py`** -- a host-side CLI that is
deliberately not copied into the image. The app's own uuid usage is `uuid5` (Qdrant point
ids) and `uuid4` (rate-limit script keys), both ancient.

`app/ids.py::new_id` now supplies the id, using `uuid.uuid7()` when the interpreter has it
and an RFC 9562 §5.7 implementation when it does not. **A `uuid4` fallback was rejected**:
these are primary keys, and v7's leading 48-bit timestamp is what gives them index locality
on insert. A fallback that silently dropped the ordering would make key distribution depend
on which interpreter minted the row -- visible months later as index bloat, never as an
error. `tests/unit/test_ids.py` asserts the version and variant bits, that the timestamp
occupies the leading 48 bits, and that hex ordering matches creation order, so substituting
`uuid4` fails the suite rather than passing quietly.

Docker and CI stay on 3.14. A runtime newer than the floor is the normal case; the floor
states what the code *requires*, and nothing requires 3.14 any more.

**What this actually bought**: local testing. The only 3.14 available in some environments
is a pre-release, and on 3.14.0rc2 pydantic fails to build models
(`_eval_type() got an unexpected keyword argument 'prefer_fwd_module'`) -- so the suite could
not run locally at all under a `>=3.14` floor, since `uv sync` refuses a 3.13 interpreter.
Previously that was worked around by editing the floor temporarily and remembering to put it
back, which also rewrote `uv.lock` each time. Now `uv venv && uv sync --extra dev` just works,
because **`.python-version` is tracked and pins 3.13**. That is the whole reason to prefer the
lowest floor the code honestly supports rather than the highest one it happens to run on.

Two consequences of that pin, both learned the hard way. It is excluded in `.dockerignore`:
`python:3.14-slim` has no 3.13 and `UV_PYTHON_DOWNLOADS=0` forbids fetching one, so a future
`COPY . .` would fail the build with a message about a missing interpreter. And CI overrides it
per job via `setup-uv`'s `python-version` (which sets `UV_PYTHON`, measured to win over the
file) and then **asserts** the interpreter it actually got -- otherwise a change in that
precedence would make the 3.14 matrix leg a second 3.13 run and report green, which is the
same shape of lie as a skipped test passing.

## Corpus fetching: plain HTTP, after dropping the `arxiv` client (both now deleted)

**Superseded 2026-08-03**: the curated corpus was removed, so `scripts/fetch_corpus.py`,
`scripts/ingest.py`, `data/manifest.json` and `tests/unit/test_fetch_corpus.py` are all deleted.
Kept as a decision record because the *lesson* outlived the code -- see the closing paragraph on
what "this dependency only resolved a URL" missed.

The `arxiv` package was a direct dependency used in exactly one place -- `scripts/fetch_corpus.py`
-- to turn a manifest id into `Result.pdf_url`. Dropped, because that URL is deterministic:
`https://arxiv.org/pdf/<id>` serves the latest version, verified with a HEAD returning
`200 application/pdf` and no redirect. The dependency was already half-unused, since `arxiv>=4`
removed `Result.download_pdf` and the file was fetched over plain HTTP regardless. `requests`
went with it (nothing imports it now; it still arrives via docling, streamlit and langsmith) and
`httpx` is declared in its place -- guaranteed anyway by `fastapi[standard]`, `anthropic` and
`qdrant-client`, but a script imports it directly so the manifest should say so.

**What the swap initially lost, and now does not.** `arxiv.Client` defaults to
`delay_seconds=3.0` and `num_retries=3`, and its own docstring ties those to arXiv's Terms of
Use. The first version of the replacement was a bare `client.get` loop: back-to-back multi-MB
requests to a public academic host, hard-failing the build on the first 5xx. Invisible at six
papers, which is why it passed review; `data/manifest.json` says to expand toward ~45. Both are
restored explicitly (`_REQUEST_SPACING_SECONDS`, `_ATTEMPTS`) rather than inherited from a
library, and `tests/unit/test_fetch_corpus.py` pins them. Recorded because "this dependency only
resolved a URL" was *nearly* true, and the part that was not true was the part that mattered.

## Testing: real services, and skip rather than fake

Unit tests that can be pure are pure. The exceptions are deliberate, and there are now **five**
suites, not the two this section originally described:

- **Auth tests run against real Postgres.** Substituting SQLite hid a foreign-key bug and a
  timezone bug, as described above.
- **Rate-limit tests run against real Redis.** A fake would only assert that the fake behaves as
  written. (This originally read "the limiter is a Lua script and a sorted-set expiry contract" —
  true until the swap onto `limits`, and the reason still holds under `MovingWindowRateLimiter`.)
- **Worker/registry, key-management and the `create_tenant` CLI** joined later, for the same
  reason and with the same skip behaviour.

All five **skip** when their service is unreachable, so the suite still runs on a bare machine.
That has a cost worth naming: a green local run may have tested less than it appears — 59 tests'
worth. CI therefore provides both services *and* asserts that none of the five skipped, since a
silently skipped auth suite is indistinguishable from a passing one. It asserted three for a
while, which let the two newest skip in CI unnoticed.

Qdrant's **filtering** is exercised — `tests/unit/test_qdrant_filtering.py` runs `_build_filter`
through `qdrant_client`'s in-memory engine, so tenant isolation is proved by execution in CI with
no server. Its **network path** is not, which is where the point-id constraint escaped to
production. Do not shorten this to either "Qdrant is tested" or "nothing exercises Qdrant"; the
second is what this paragraph used to say, and it was the flat opposite of the other five places
that describe it.

## Scale target: 10k tenants x 10 documents

The working assumption is **100,000 documents** (10,000 tenants, ~10 each) on an 8 vCPU /
16 GB host. It was 2,000 (1k x 2) until 2026-07-31; the 50x revision is recorded here
because several decisions above were sized against the smaller number and one of them
changes verdict:

- **The Qdrant payload index on `metadata.tenant_id` moved from deferred to required, and is
  now built** (2026-08-03, `qdrant_store._ensure_payload_indexes`). `CLAUDE.md` and
  `docs/EPIC_4_PLAN.md` called it "harmless at 6 documents". At ~100k documents and roughly 10
  chunks each -- order 1M points -- every tenant-filtered query without a keyword index on that
  field degrades toward a scan, so it became a prerequisite for load rather than an
  optimization.

  `metadata.tenant_id` carries **`is_tenant=True`**, which is the part that is easy to lose
  while thinking the index is still there: the flag tells Qdrant the field identifies tenants,
  so each tenant's vectors are stored together and a tenant-filtered search is served by
  sequential reads. A plain keyword index makes the filter fast to evaluate; `is_tenant` is what
  makes the *reads* sequential. `metadata.doc_id` gets a plain keyword index (it is filtered by
  `delete_document` on every re-ingest and by `/ask`'s document scoping).
  `metadata.chunk_type` gets none -- `_build_filter` accepts `chunk_types` but no production
  caller passes it, so an index would cost write amplification on every upsert to serve nothing.

  **Verified against a real server, because it cannot be verified anywhere else.**
  `qdrant_client`'s local/in-memory mode -- which every other Qdrant test in this project uses
  -- warns "Payload indexes have no effect in the local Qdrant" and reports an empty
  `payload_schema`, so an in-memory assertion would have been vacuous. Against
  `qdrant/qdrant:v1.18.3`: `metadata.tenant_id` came back `data_type=keyword, is_tenant=True`,
  `metadata.doc_id` `is_tenant=False`, `metadata.chunk_type` absent, and a second identical call
  returned `completed` rather than raising (so it needs no existence check). The unit tests
  assert the calls and their parameters and say in their docstrings that this is what they can
  reach.

  Creation failures are logged and swallowed. An index is a performance property, not a
  correctness one -- the filters return the same points either way -- so refusing to construct
  the store would turn a scale concern into an outage. Same reasoning as the rate limiter
  failing open.
- **Anything O(corpus) per query is out.** Answering a question by making one model call per
  document costs 100,000 calls. Corpus-level answering has to be bounded by retrieval first
  (see the map-reduce note below), never by a full scan.
- **Per-document disk is now the sizing question**, not per-document tokens: `processed_dir`
  holds one parsed JSON per document plus a PNG per surviving figure. At 100k documents that
  volume needs a real number attached to it before a deploy.

## Graph RAG: the graph is a computation, not a storage tier

`docs/IMPLEMENTATION_PLAN.md` records Neo4j as eventual work, and the registry schema was
kept deliberately flat so a later sync job could read from it. Evidence found on 2026-07-31
argues against the graph database specifically, and it is worth recording before that work
is scheduled.

`microsoft/graphrag` (MIT, v3.1.1) is the reference implementation of the technique, from the
team that published it. It uses **no graph database**. The graph is built in memory with
`networkx`, communities are detected with hierarchical Leiden via `graspologic-native`, and
the result is persisted as **parquet tables** read back with `pyarrow`. Vector storage is
LanceDB / Azure AI Search / CosmosDB. There is no Neo4j, and no traversal-time graph engine
of any kind.

So the graph is derived, batch-computed, and re-derivable from the documents. Adding a fourth
stateful service to store it buys nothing until a query pattern needs traversal at request
time -- and none of the planned queries do. Postgres plus columnar files on disk covers it.

Two further findings from the same read, recorded so they are not re-derived:

- **~~It cannot be a dependency here.~~ Corrected 2026-08-05: this reason no longer holds.** Every
  one of its eight packages pins `requires-python = ">=3.11,<3.14"`, and that was written against a
  `>=3.14` floor, where it would indeed have been unsatisfiable. **The floor was lowered to
  `>=3.13`** (see § Python version, and `pyproject.toml`), and `>=3.13` with `<3.14` resolves fine.
  The verdict below still stands on its own -- per-document indexing cost -- but this argument is
  dead and must not be reused. MIT licence, so importing would be permitted.
- **Its per-document indexing cost rules out the pipeline at this scale.** Entity extraction
  is roughly a model call per chunk, plus description summarisation, plus a report per
  detected community. Estimated at ~20 calls per document, 100k documents is ~2M model calls,
  re-run incrementally as uploads arrive. The technique is designed for one large static
  corpus queried by many readers; this system is many small per-tenant corpora that change
  constantly. The economics invert.

What *is* worth taking from it is the **global-search reduce step**, which is a genuine
answer to a question this system cannot currently answer at all: map over candidate
documents, have each return scored key points, drop everything scoring zero, sort by score,
and pack into a token budget. The zero-score branch returns a canned "no data" answer rather
than synthesising from weak material -- the same principle as dropping unusable figure
captions, arrived at independently. Bounded by retrieval rather than run over the whole
corpus, it fits; run globally, it does not.
