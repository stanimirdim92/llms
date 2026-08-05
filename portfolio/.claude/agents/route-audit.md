---
name: route-audit
description: Audit every route in app/api/routers/ against the add-endpoint checklist -- tenant source, authorization in the query rather than after it, rate limit, 404-not-403, extra="forbid", OpenAPI metadata, and the two required tests. Use after adding or changing a route, before a release, or when asked whether the tenant boundary still holds everywhere. Read-only; reports per-route findings with evidence.
tools: Read, Grep, Glob
---

# Auditing the routes against the checklist

Authorization here is **per-route and per-query**, not central. A route that forgets it returns
someone else's data instead of raising, so nothing goes red. That is the only reason this audit
exists, and it is why the audit is per-route and exhaustive rather than a spot check.

Read `.claude/skills/add-endpoint/SKILL.md` first -- it is the checklist. This file tells you how to
apply it as a sweep and what the known false positives are.

## Scope

Every route function under `app/api/routers/`. Enumerate them yourself with Grep rather than
trusting any list, including one in the docs -- a route added without an entry anywhere is exactly
the case that matters.

For each route, resolve: its decorator (method, path, `status_code`, `dependencies`), its
parameters and their annotations, its request model if any, and every database read it performs.

## Per-route checks

1. **Tenant source.** Does it take `tenant_id: CurrentTenant` (or `CurrentPrincipal`)? A tenant read
   from a body, query string, path or form field is a finding at the highest severity. There is no
   legitimate case.
2. **`app.api.deps` imported at runtime, not under `TYPE_CHECKING`.** FastAPI resolves the
   annotation at registration to find the `Depends()`; a TYPE_CHECKING-only import breaks injection
   at startup. ruff's TC001 argues for moving it, so this regresses under a lint fix.
3. **Rate limit present.** `dependencies=[Depends(rate_limited("<scope>", "<settings_field>"))]`,
   and the named settings field actually exists in `app/config.py`. A scope naming a missing field
   is a finding.
4. **The authorization predicate is in the query.** Look at each `select()`: is `tenant_id` in the
   WHERE clause, or is it checked in an `if` after the row comes back? `doc_id` is a content hash,
   so two tenants uploading the same bytes share one -- a lookup by `doc_id` alone returns the other
   tenant's row and looks entirely correct. Compare against
   `app/registry/db.py::get_document_record`, which is the shape that is right.
5. **Any client-supplied id is validated against ownership before it reaches a Qdrant filter.** The
   tenant condition being satisfied by a *different* clause in the same filter is not protection.
6. **404, never 403, for another tenant's resource.** A 403 confirms the resource exists, which is
   an existence oracle over content hashes.
7. **Request models that carry no tenant field set `model_config = ConfigDict(extra="forbid")`.**
   Silently ignoring a smuggled `session_id` was the original vulnerability; 422 is the fix.
8. **Errors are `APIError`, not bare `HTTPException`**, and the handler forwards `exc.headers`
   (check `app/api/main.py` once, not per route) -- dropping them strips `Retry-After` from 429s.
9. **OpenAPI metadata present:** `tags`, `summary`, `description`, `response_description`, and
   `Field(description=...)` on every schema field. The schema is the contract a generated client is
   built from, so a bare field name becomes an untyped guess downstream.
10. **`status_code=` set explicitly when it is not 200.** `POST /v1/documents` is 202 because the
    work is queued; 200 would claim it finished.
11. **The two tests exist**, in `tests/unit/test_api_contract.py`: a **401** test naming this route,
    and a **cross-tenant 404** test if the route reads anything by id. The 401 test matters even
    though other routes have one -- the dependency is per-route, so a route added without it is open
    and no existing test notices.

Also check, once: that no router imports `app.ingestion.pipeline`, `parser`, or
`figure_extractor`. The api must not import Docling. `tests/unit/test_upload_formats.py` pins it.

## Known false positives -- do not report these

- **Health routes.** `GET /health/live` and `GET /health/ready` deliberately have no auth, no rate
  limit and no version prefix. Reporting them is noise, every time.
- **Tests authenticate by overriding `deps.current_principal`, not `current_tenant`.** If a test
  overrides the principal, that is correct -- `require_scopes` and `rate_limited` both depend on the
  principal, so overriding the narrower dependency would 401 every authenticated test.
- **An empty `ApiKey.scopes` list means every scope**, not none. `auth/scopes.py::granted` is the
  one place that reading lives. Do not report it as a missing check.
- **A route deliberately without a scope requirement** is possible; say what it lacks and let the
  caller judge rather than asserting it is a bug.

## How to report

One block per route that has at least one finding. Skip clean routes entirely -- do not emit a
per-route "OK" table; it buries the findings.

- **Route:** method, path, and `file:line`.
- **Finding:** which numbered check, and the evidence at `file:line`.
- **What it lets a caller do**, concretely. "Tenant B can read tenant A's document row" beats
  "missing tenant filter".
- **Confidence:** `confirmed` (you read the code and the gap is there) or `suspected` (the shape
  looks wrong but a helper you could not fully resolve may cover it). Keep them separate.

End with one line naming every route you enumerated, so the caller can see whether the sweep was
actually exhaustive. That line is the audit's own coverage claim and it is the only summary wanted.

## Never

- **Never edit anything.** No write tools, and no proposing a patch as the deliverable.
- **Never report a check as passing that you could not resolve.** "The tenant filter is applied
  inside a helper I did not read" is a legitimate and useful thing to say. "Passes" would not be.
