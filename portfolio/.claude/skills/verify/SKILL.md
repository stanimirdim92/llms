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
    uv sync --extra dev --locked                                  # after pyproject.toml edits

**One pass, in a random order.** `pytest-randomly` is installed, so every run reorders the
suite and reseeds `random` per test. This replaced an instruction to run the suite three
times, which was weaker than it read: pytest orders tests identically every run, so three
passes could only catch timing races and state surviving *between* runs -- never a test that
passes because another ran first. Verified the plugin is actually doing it rather than sitting
inert (two seeds produce different collection orders) and that the suite survives it (five
seeds, 372 passed each).

When a randomised run goes red, reproduce it before debugging:

    uv run pytest tests/unit --randomly-seed=last     # replay the order that just failed
    uv run pytest tests/unit -p no:randomly           # was it order, or the test itself?

**`-q` hides the seed.** The header line `Using --randomly-seed=NNN` only prints without it, so
`-q` runs are reproducible via `last` and not from the log. CI runs `-v` deliberately for this;
if a CI run is red, the seed is in its log.
    # `--extra dev` is required, not optional: a bare `uv sync --locked` prunes the dev
    # group and uninstalls pytest, so the next gate command fails with 'no module named
    # pytest' and looks like a broken venv rather than a missing flag.

`ty.toml` sets `error-on-warning`, so a warning is a failure. All five must pass before pushing.

## Trap 1: skipped tests look identical to passing ones

Five suites **skip** when their service is unreachable: `test_auth_touch.py`,
`test_rate_limit.py`, `test_worker_enqueue.py`, `test_key_management.py` and
`test_create_tenant.py`. A run reporting `288 passed, 59 skipped` has not tested auth, rate
limiting, the job queue, key management or the bootstrap CLI -- most of the security-relevant
surface. (It was three for a while, and CI asserted only those three, so the two newer ones could
skip silently -- including the only test of `{"scopes": null}`.)

**Always read the skip count.** The full suite should report **`370 passed, 0 skipped`**. (Treat
the number as a floor that drifts upward, not a checksum — what matters is the *skip* count being
zero. An earlier version of this line said "249 tests ... `116 passed`", two numbers that already
disagreed with each other, which is what a hand-maintained count does.) With no services reachable
the suite reports `308 passed, 59 skipped` across those five files, so a green run then has tested
almost none of the security-relevant surface. Start them rather than shipping:

    pg_isready -h localhost -p 5433 -U portfolio || \
      su postgres -c '/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pgtest -o "-p 5433" -l /tmp/pgtest/server.log start'
    redis-cli -p 6380 ping || (cd /tmp && redis-server --port 6380 --daemonize yes)

    DB_PORT=5433 REDIS_PORT=6380 uv run pytest tests/unit -q

They die repeatedly in a long session (idle reclamation), so re-check before *each* run, not
once at the start. `pg_ctl` refuses to run as root -- hence the `su postgres`.

Outside this container, the compose Postgres/Redis serve the same purpose and need no port
overrides. CI provides both and asserts none of the five suites skipped.

## Trap 2: build the dev venv on 3.13, not 3.14

`requires-python` is `>=3.13` while Docker and CI run 3.14. **`.python-version` pins the local
venv at 3.13**, so the plain commands are now correct:

    uv venv && uv sync --extra dev --locked

Keep that file. Without it, which interpreter you get depends on PATH order -- and on a 3.14
*pre-release*, which is the only 3.14 some environments offer, pydantic cannot build models:

    TypeError: _eval_type() got an unexpected keyword argument 'prefer_fwd_module'

That is the interpreter, not the code: ruff, ty, and `docker compose config` still pass while
pytest and any `import app.api.main` fail. So before believing any failure that looks like
that, check what you are on:

    uv run python -V

`uv venv --python 3.13` still works and overrides nothing that matters -- reach for it if the
pin has been removed. CI overrides the pin deliberately (`setup-uv`'s `python-version` input
sets `UV_PYTHON`, which is measured to win) and then *asserts* the interpreter matches the
matrix leg, so a change in that precedence fails loudly instead of testing 3.13 twice.

This used to require temporarily editing `requires-python` and regenerating `uv.lock`
afterwards. It no longer does -- the floor is 3.13 for real. If you find that editing
procedure anywhere, it is stale.

## Trap 3: `uv run pytest` lies when dev extras are not synced

If `pytest` is absent from the venv, `uv run pytest` does **not** fail with "pytest not
found" -- it resolves pytest into an isolated tool environment that has none of the project
dependencies, then reports a wall of:

    ModuleNotFoundError: No module named 'pydantic'
    ModuleNotFoundError: No module named 'httpx'
    ModuleNotFoundError: No module named 'sqlalchemy'

Twelve collection errors that read as a broken project. The cause is a missing
`uv sync --extra dev`. Confirm before diagnosing anything else:

    uv run python -c "import pydantic, httpx, sqlalchemy; print('deps present')"

If that succeeds while pytest reports the modules missing, pytest is running from somewhere
else. Sync dev extras and re-run.

## Why it takes ~25 seconds

Almost none of it is the tests. Measured with `--durations`: the slowest is 6.75s
(`test_the_api_import_graph_does_not_pull_in_the_ingestion_stack`, which spawns a subprocess on
purpose), then 1.65s (three real subprocesses racing to initialise the schema), and everything else
is under half a second. The rest is **import cost** -- `import docling.chunking` alone takes 4.8s,
and three test modules need it at module scope.

So don't go looking for a slow test. And note the consequence for mutation testing: every
`pytest <one file>` invocation pays that import again, which is why a twelve-mutation sweep costs
minutes rather than seconds. Scope the `-k` tightly and expect it.

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
