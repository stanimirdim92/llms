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
feeds the Qdrant point id, so renumbering would orphan previously-stored figures. See the
delete-then-insert decision below for why that is survivable now.

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
   `uuid5(fixed_namespace, chunk_id)` — deterministic, so the same chunk maps to the same
   point. The human-readable `chunk_id` stays in the payload, which is where citations read
   it from. This one shipped and broke on first real use, because the dev sandbox has no
   Qdrant to test against.

**No native async client.** `asimilarity_search` is `VectorStore`'s thread-pool shim and
`upsert` is synchronous, same as Chroma. The gain from Qdrant is Qdrant, not async.

## Re-ingestion: delete-then-insert, not upsert-by-id

**Decision.** `QdrantStore.upsert` deletes every point for the document's `doc_id` before
inserting, and raises if handed chunks spanning more than one document.

Upserting by id alone is *not* idempotent here, and believing otherwise was a real bug. Chunk
ids encode position (`{doc_id}-text-0000`, `fig-{page}-{index}`), so anything that changes how
many chunks a document yields — a different `chunk_max_tokens`, a Docling upgrade detecting
one more figure, toggling `do_ocr` — shifts every subsequent id. The new ids insert cleanly
while the old points remain, still matching the tenant filter, still retrievable, now stale.
There was no other cleanup path in the store.

The multi-document guard exists because delete-by-`doc_id` would otherwise wipe the wrong
document's points if a future caller batched across documents.

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

**No Alembic.** With three tables, a schema change means dropping the volume and
re-ingesting. That is a real simplification while there is no data worth migrating rather
than recreating, and it should be revisited the moment there is.

## Tenant scoping: one field, derived only from auth

**Decision.** `tenant_id` replaced `session_id` entirely. `AskRequest` has no scope field at
all and sets `extra="forbid"`.

The original design accepted a client-supplied `session_id` on both upload and `/ask`. That
meant **any caller could read another tenant's documents by passing their id** — the schema's
own comment promised the opposite. Removing the field from the request rather than merely
ignoring it is the point: an absent field cannot be spoofed, and `extra="forbid"` means a
stale client gets a 422 instead of silently receiving corpus-only answers and appearing to
work.

**Collapse rather than nest.** `tenant_id` from auth *plus* a `session_id` grouping key
underneath it was the alternative. It was rejected because it would keep a client-supplied
value in the security filter — safe, since the tenant would still be ANDed in from auth, but
the same *shape* as the bug being fixed. Collapsing leaves the filter derived entirely from
the authenticated identity, with no request-supplied component at all. That is a stronger
invariant and a much harder one to regress. If per-project scoping is ever wanted, add a
`workspace_id` then; it is a metadata addition plus one filter condition.

`GLOBAL_TENANT` (`"global"`) is the shared corpus: readable by every tenant, owned by none.
Real ids are `uuid7().hex`, so no tenant can ever be issued that value and claim it.

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

## Rate limiting: hand-rolled on `redis.asyncio`

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

*Verdict: keep the hand-rolled version.* One Lua script, no new dependency, no event-loop
blocking, and 124 lines with a test suite that runs against real Redis. Revisit if the
`X-RateLimit-*` headers are wanted (cheap to add directly) or if a Redis-outage fallback
becomes worth more than the simplicity.

**Sliding window, not fixed.** A fixed window lets a caller spend its entire budget at the end
of one window and again at the start of the next — an observed burst of twice the configured
limit.

**The check is a Lua script because it must be atomic.** A read-then-write implementation
lets concurrent requests all observe a count below the limit and all proceed, which is the
exact scenario rate limiting exists to prevent. A test fires 25 concurrent requests at a limit
of 5 and asserts exactly 5 pass.

**Keyed per tenant**, not per IP — an IP key punishes shared corporate egress and is trivially
evaded. **Per scope** too, so exhausting the upload budget does not also block questions.
Uploads get a much tighter budget (10/min vs 60/min) because they cost Docling CPU plus one
Anthropic vision call per figure plus one Voyage embedding call per chunk; `/ask` is a
retrieve, a rerank, and one generation.

**Counters live in Redis, not memory**, because in-process counters are per gunicorn worker —
with N workers the real limit becomes N times the configured one.

**Fails open.** Unreachable Redis allows the request and logs a warning: a guardrail's outage
must not become the API's outage. The tradeoff is that protection disappears exactly when
load may be why Redis is struggling, which is why the log is loud and why `docker-compose.yml`
gates `api` on redis being healthy — otherwise the gap would be silently open at startup.

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

- procrastinate ships its own SQL migrations, so "no Alembic" below stops being the whole story.
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
back, which also rewrote `uv.lock` each time. Now `uv venv --python 3.13 && uv sync
--extra dev` just works. That is the whole reason to prefer the lowest floor the code
honestly supports rather than the highest one it happens to run on.

## Testing: real services, and skip rather than fake

Unit tests that can be pure are pure. The two exceptions are deliberate:

- **Auth tests run against real Postgres.** Substituting SQLite hid a foreign-key bug and a
  timezone bug, as described above.
- **Rate-limit tests run against real Redis.** The limiter is a Lua script and a sorted-set
  expiry contract; a fake would only assert that the fake behaves as written.

Both **skip** when their service is unreachable, so the suite still runs on a bare machine.
That has a cost worth naming: a green local run may have tested less than it appears. CI
therefore provides both services *and* asserts that neither suite skipped, since a silently
skipped auth suite is indistinguishable from a passing one.

Nothing exercises Qdrant. Store-layer bugs surface only on a real ingest — which is exactly
how the point-id constraint was found, after it shipped.

## Scale target: 10k tenants x 10 documents

The working assumption is **100,000 documents** (10,000 tenants, ~10 each) on an 8 vCPU /
16 GB host. It was 2,000 (1k x 2) until 2026-07-31; the 50x revision is recorded here
because several decisions above were sized against the smaller number and one of them
changes verdict:

- **The Qdrant payload index on `metadata.tenant_id` moves from deferred to required.**
  `CLAUDE.md` and `docs/EPIC_4_PLAN.md` call it "harmless at 6 documents". At ~100k documents and
  roughly 10 chunks each -- order 1M points -- every tenant-filtered query without a keyword
  index on that field degrades toward a scan. The vendored `qdrant-multitenancy` skill
  specifies a keyword index with `is_tenant=true`; that is now a prerequisite for load, not
  an optimization.
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

- **It cannot be a dependency here.** Every one of its eight packages pins
  `requires-python = ">=3.11,<3.14"`. Against this project's `>=3.14` floor that is an
  unsatisfiable resolution, not a warning -- the same class of conflict as `slowapi` against
  `redis>=8`. Anything taken from it is reimplemented, not imported. MIT licence, so that is
  permitted with attribution.
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
