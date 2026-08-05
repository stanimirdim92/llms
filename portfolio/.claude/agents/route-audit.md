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

**Apply every item in the skill's *Non-negotiable*, *Request/response shape* and *Tests* sections
to each route.** Do not work from a copy of that list. An earlier version of this file restated all
eleven checks, and within a day check 4's copy had drifted into a claim the code contradicts -- it
said `doc_id` is a plain content hash so two tenants share one, when `upload_doc_id` salts the
digest with `tenant_id` and they do not. `docs/PATTERNS.md` §2 had already recorded that correction
and warned that a wrong reason attached to a right rule is how the rule gets deleted later. A second
copy of a checklist is how the wrong reason survives, so there is no second copy here.

Only three things need framing specific to a sweep:

- **Check every `select()` individually, not the route as a whole.** One route can hold a filtered
  read and an unfiltered one, so "has a tenant filter somewhere" is not an audited route. Compare
  each against `app/registry/db.py::get_document_record`.
- **Resolve helpers before judging.** If the tenant predicate lives in a function you did not read,
  that check is *unresolved*, not passed. Name the helper you could not follow.
- **The 401 test is per route.** Other routes having one proves nothing: the dependency is declared
  per route, so a route added without it is open and no existing test notices. Confirm a test names
  *this* route.

Also check once, rather than per route: that no router imports `app.ingestion.pipeline`, `parser`,
or `figure_extractor`. The api must not import Docling. `tests/unit/test_upload_formats.py` pins it.

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
