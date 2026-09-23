---
paths:
  - "**/app/api/routers/health.py"
  - "**/app/api/main.py"
  - "**/app/worker/tasks.py"
  - "**/.docker/**"
---

# Health checks and provider credentials

Path-scoped: loads when a matching file is read. The general rules (`../CLAUDE.md`) and the
cross-cutting contracts (`CLAUDE.md` § Never, § The tenant boundary) still apply.

## Health checks

`GET /health/live` is static; `GET /health/ready` probes Postgres, Qdrant, and Redis and 503s
when a *required* one is down. Three things not to undo:

- **Liveness must not check dependencies.** A liveness probe failing on a Postgres blip gets the
  process restarted, which fixes nothing and turns a hiccup into a restart loop.
- **Redis is reported but not required.** Rate limiting fails open, so its outage degrades a
  guardrail, not the API. Marking it required would pull instances from rotation over an
  optional component.
- **Readiness must not construct `QdrantStore`.** Its `__init__` sends a throwaway *probe
  embedding* to detect vector size, so that would bill a Voyage call every 30 seconds and report
  Qdrant down whenever Voyage was. `health.py` uses a bare cached `AsyncQdrantClient`.

The container `HEALTHCHECK` targets readiness, so `depends_on: service_healthy` means "can
serve". It previously targeted `GET /`, which returned a static body and so reported healthy
with every dependency down.

Missing `ANTHROPIC_API_KEY`/`VOYAGE_API_KEY` fails the api at boot (`require_provider_credentials`
in the lifespan) and fails an individual *job* in the worker, so the reason lands in
`documentrecord.error_message` rather than killing the worker. Deliberately not a `Settings`
validator -- that would break the unit suite, `ty`, and `scripts/create_tenant.py`, none of which
need provider keys.
