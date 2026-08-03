---
name: add-endpoint
description: Checklist for adding or changing a route in app/api/routers/. Use when adding an endpoint, exposing a new field, adding a query/path parameter that names a document or tenant, or reviewing a route diff. Exists because authorization here is per-route and per-query -- a route that forgets it returns data instead of erroring, so the failure is silent.
---

# Adding an API route

The tenant boundary is not enforced centrally. It is re-established in **every route** and in
**every query**, so a new route that forgets it is unauthenticated or cross-tenant, and nothing
raises. That is the entire reason this checklist exists.

## Non-negotiable

1. **Take `tenant_id: CurrentTenant`.** Never read a tenant from the body, query string, path,
   or form. An earlier version accepted a client-supplied `session_id`, which let any caller
   read another tenant's documents by passing their id.
2. **Import from `app.api.deps` at runtime**, not under `TYPE_CHECKING`. FastAPI resolves the
   annotation when registering the route to find the `Depends()` inside `CurrentTenant`; a
   TYPE_CHECKING-only import breaks injection at startup. ruff's TC001 will suggest moving it --
   don't.
3. **Add a rate limit**: `dependencies=[Depends(rate_limited("<scope>", "<settings_field>"))]`.
   Pick an existing scope or add a `rate_limit_*` field to `Settings`. Uploads get a far tighter
   budget than reads because they cost Docling CPU plus a vision call per figure plus an
   embedding call per chunk. Buckets are **per key**, not per tenant, so a tenant with N keys
   has N times the budget -- fairness between clients, not a cost ceiling.
4. **Declare the scope it needs**: `Depends(require_scopes(<SCOPE>))` from `app.auth.scopes`,
   in the same `dependencies=[...]` list. A route without one is reachable by every key.
   `tests/unit/test_scopes.py` walks the route table and fails on any `/v1` route with no
   requirement -- add yours to `EXPECTED_ROUTE_SCOPES` there. Scope failures are **403** (the
   caller is entitled to the tenant and merely lacks a capability); another tenant's resource
   is still 404, see below.
5. **Put `tenant_id` in the WHERE clause**, not in an `if` after the query. See
   `registry/db.py::get_document_record`. This matters more than it looks: `doc_id` is a content
   hash, so two tenants uploading the same file share an id -- a lookup by `doc_id` alone returns
   the *other* tenant's row while looking entirely correct.
6. **Validate any client-supplied id against ownership before it reaches a Qdrant filter.** A
   `doc_ids` parameter (planned, `docs/EPIC_4_PLAN.md` 5.4) is a fresh cross-tenant read otherwise:
   the tenant condition is satisfied by the other clause and the filter happily returns someone
   else's chunks.
7. **Return 404, not 403, for another tenant's resource.** Distinguishing "not yours" from
   "doesn't exist" confirms to any caller that a given file has been uploaded by *somebody* --
   a confirmed account for every `doc_id` that leaks into a log, a screenshot, or a bug report.
   (Not an oracle you can *compute* into: `upload_doc_id` salts the digest with `tenant_id`, so
   two tenants with the same file get different ids. The risk is ids that are already in hand.)

## Request/response shape

- Request models that carry no tenant field must set `model_config = ConfigDict(extra="forbid")`,
  so a stale client sending one gets a 422 instead of being silently ignored. Silence was the
  original vulnerability.
- Every schema field takes `Field(description=...)` and every route takes
  `tags`/`summary`/`description`/`response_description`. The OpenAPI schema is the contract the
  Phase 6 React client generates from, so a bare field name becomes an untyped guess downstream.
- Raise `APIError(msg, code=...)` from `app/exceptions.py`, never a bare `HTTPException`. The
  handler in `api/main.py` logs structurally and **forwards `exc.headers`** -- dropping them
  silently strips `Retry-After` from 429s.
- Set `status_code=` explicitly when it isn't 200. `POST /v1/documents` is 202 because the work
  is queued; returning 200 would claim it finished.

## Tests, both of them

In `tests/unit/test_api_contract.py`:

1. **A 401 test for the new route.** Add it even though other routes have one -- the dependency
   is declared per-route, so a route added without it is open and no existing test notices.
2. **A cross-tenant test** if the route reads anything by id: tenant B must get 404 for tenant
   A's resource. `test_worker_enqueue.py` has the DB-level pattern.

Authenticate by overriding **`deps.current_principal`**, returning a `Principal`. Not
`current_tenant` -- that is the narrower dependency, and overriding it leaves `require_scopes`
and `rate_limited` resolving a real key, so every authenticated test gets a 401. The
`as_tenant_a` fixture does this already; `as_a_key_holding(scopes)` is the variant for
authorization cases. Overriding at all works only because auth is a dependency rather than
middleware -- middleware can't be swapped per-test, which is one of the reasons it was chosen.

## Don't

- Don't add auth as middleware. It can't be overridden per-route in tests, can't appear in the
  OpenAPI schema, and would have to reimplement path matching.
- Don't import the ingestion stack (`app.ingestion.pipeline`, `parser`, `figure_extractor`) into
  a router. The api enqueues and must not import Docling -- `tests/unit/test_upload_formats.py`
  asserts this, and it costs ~2s of startup per process when it regresses.
- Don't put health/probe routes behind auth or a rate limit, and don't version them.

Then run the `verify` skill -- and read the skip count.
