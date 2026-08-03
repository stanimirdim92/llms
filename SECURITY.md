# Security Policy

This repository holds four independent projects. Only **`portfolio/`** is under active
development and is the only one that runs as a service; `fastai-dl/`, `transformers-course/`
and `LLM Engineers Handbook/` are course and book material with no deployed surface.

## Scope

`portfolio/` is a work in progress and is **not deployed anywhere**. There is no production
instance, no hosted endpoint, and no user data. Reports are still welcome and will be acted on,
but treat the severity framing accordingly: a finding here is a bug to fix before there is
anything to compromise, not an incident.

The security-relevant surface, so a report can be specific:

- **`app/auth/`** — API-key authentication, scopes, expiry, revocation.
- **`app/api/deps.py`** — the only place a tenant identity is established.
- **`app/vectorstore/qdrant_store.py::_build_filter`** and `app/registry/db.py` — tenant
  isolation for retrieval and for the document registry. A wrong filter here returns another
  tenant's data rather than raising, which is the highest-value class of bug in this codebase.
- **`app/rate_limit.py`** — per-key budgets. Fails open by design; see
  `docs/TECHNICAL_DECISIONS.md`.
- **`.docker/`** — the compose stack, nginx configuration, and container capabilities.

## Supported versions

There are no releases and no version numbers. `main` is the only supported ref; fixes land
there and nowhere else. The GitHub-template version table this file used to carry
(`5.1.x`, `4.0.x`, …) described a project that does not exist.

## Reporting a vulnerability

**Use GitHub's private vulnerability reporting** — the *Security* tab → *Report a
vulnerability*. That keeps the report out of public issues until there is a fix.

If that is unavailable to you, email **stanimirdim92@gmail.com** with `SECURITY` in the
subject. Please do not open a public issue for anything exploitable.

What to include, in whatever detail you have: the file and line, what an attacker gets, and the
smallest reproduction you can manage — a failing test against `tests/unit/` is ideal, since that
is how the fix will be verified.

**What to expect.** This is one person's project, not a staffed programme: acknowledgement
within about a week, and a fix or an explicit "won't fix, here's why" rather than silence. If a
report is declined you will be told the reasoning, and you are free to publish at that point.

## Already known, and deliberate

Please don't report these as findings — they are documented decisions, with the reasoning in
`portfolio/docs/TECHNICAL_DECISIONS.md` and `portfolio/CLAUDE.md`:

- **Rate limiting fails open.** An unreachable Redis allows the request and logs loudly. A
  guardrail's outage must not become the service's outage.
- **Rate limits are per API key, not per tenant**, so a tenant holding N keys has N times the
  budget. It is a fairness device between clients, not a cost ceiling.
- **Redis runs with no password and `protected-mode no`**, reachable only on the compose network
  and published on `127.0.0.1` only.
- **An empty scope list on a key means *every* scope**, not none — back-compatibility for keys
  minted before the column existed.
- **CORS defaults to `*` origins**, which is inert because credentials are off and no headers are
  allow-listed; the combination that would be dangerous is refused at startup.

## Automated checks

`.github/workflows/security.yml` runs CodeQL and secret scanning; `portfolio-ci.yml` runs
`pip-audit` against the locked dependency set and fails on a known advisory. A finding those
miss is exactly the kind worth reporting.
