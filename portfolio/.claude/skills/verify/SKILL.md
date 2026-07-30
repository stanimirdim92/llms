---
name: verify
description: Run this project's full verification gate correctly -- lint, format, type check, unit tests against live Postgres/Redis, compose config, and lockfile freshness. Use before any commit or push, when asked to "verify", "check", "run the tests", or "is this green", and whenever a test run reports skips. Handles the two traps that make a green run meaningless here: silently skipped service-backed suites, and the pre-release-interpreter workaround.
---

# Verifying a change

The gate is five checks, and two of them lie by default. Read the traps before running.

## The gate

    uv run ruff check . && uv run ruff format --check .
    uv run ty check
    uv run pytest tests/unit
    cd .docker && docker compose --env-file ../.env config -q     # after compose/Dockerfile edits
    uv sync --locked                                              # after pyproject.toml edits

`ty.toml` sets `error-on-warning`, so a warning is a failure. All five must pass before pushing.

## Trap 1: skipped tests look identical to passing ones

`test_auth_touch.py`, `test_rate_limit.py`, and `test_worker_enqueue.py` **skip** when their
service is unreachable. A run reporting `91 passed, 25 skipped` has not tested auth, rate
limiting, or the job queue -- which is most of the security-relevant surface.

**Always read the skip count.** The full suite is currently 116 tests and should report
`116 passed` with nothing skipped. If you see skips, start the services rather than shipping:

    pg_isready -h localhost -p 5433 -U portfolio || \
      su postgres -c '/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pgtest -o "-p 5433" -l /tmp/pgtest/server.log start'
    redis-cli -p 6380 ping || (cd /tmp && redis-server --port 6380 --daemonize yes)

    DB_PORT=5433 REDIS_PORT=6380 uv run pytest tests/unit -q

They die repeatedly in a long session (idle reclamation), so re-check before *each* run, not
once at the start. `pg_ctl` refuses to run as root -- hence the `su postgres`.

Outside this container, the compose Postgres/Redis serve the same purpose and need no port
overrides. CI provides both and asserts none of the three suites skipped.

## Trap 2: the interpreter may not be able to run pytest

`requires-python` is `>=3.14`. If the only 3.14 available is a **pre-release**, pydantic fails
to build models on it:

    TypeError: _eval_type() got an unexpected keyword argument 'prefer_fwd_module'

That is the interpreter, not the code. ruff, ty, and `docker compose config` still work; pytest
and any `import app.api.main` do not. Workaround, in this order:

1. `sed -i 's/^requires-python = ">=3.14,<4.0"/requires-python = ">=3.13,<4.0"/' pyproject.toml`
2. `uv sync --extra dev --python 3.13 -q`
3. run the tests
4. **`git checkout pyproject.toml`**, then `rm -f uv.lock && uv lock` and `uv sync --extra dev --locked`

Step 4 is not optional and is easy to half-finish. `uv sync` **re-resolves the lock** under the
relaxed floor, so a lockfile generated during the detour pins `>=3.13` and must be regenerated
before committing. Check it:

    grep -m1 'requires-python' uv.lock        # must read ">=3.14, <4.0"

On Python 3.14 *final* none of this applies -- run the suite directly.

## What green does NOT mean

Say this plainly rather than implying full coverage:

- **The live Qdrant client is untested.** `test_qdrant_filtering.py` proves the filter excludes
  correctly via `qdrant_client`'s in-memory engine, but nothing exercises the real client over
  the wire -- which is where the point-ID constraint escaped to production.
- **The queued upload path has no end-to-end test.** Transactional enqueue is verified;
  api -> worker -> Qdrant -> registry as one flow is not.
- **nginx config syntax is unvalidated** without a Docker daemon. `docker compose config` parses
  compose, not nginx.

## After pyproject.toml changes

`uv lock` and commit the result. CI and the Docker build use `--locked`, which fails on a stale
lock. Note `--frozen` would *not* -- it uses the lock without checking, so a dependency added and
not re-locked is silently omitted and fails at runtime as an ImportError.
