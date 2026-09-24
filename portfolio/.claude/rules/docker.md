---
paths:
  - "**/.docker/**"
  - "**/.dockerignore"
  - "**/.env.example"
  - "**/app/config.py"
  - "**/app/ingestion/parser.py"
---

# The Docker stack: compose, nginx, postgres container, timeouts

Path-scoped: loads when a matching file is read. The general rules (`../CLAUDE.md`) and the
cross-cutting contracts (`CLAUDE.md` § Never, § The tenant boundary) still apply.

## Failure contracts

- **Compose `${VAR}` substitution cannot see `../.env`.** It resolves against the
  shell or a `.env` beside the compose file only. Anything a *service* needs from
  `portfolio/.env` must arrive via `env_file:`. This silently broke the postgres
  healthcheck once: the container had the real password while the healthcheck
  still checked the fallback.
- **`cap_drop: [ALL]` strips root's privileges too** -- they're capability-gated,
  not UID-gated. nginx needs `NET_BIND_SERVICE, SETUID, SETGID, CHOWN` (its master
  process chowns `/var/cache/nginx` even though the entrypoint scripts don't);
  postgres needs `CHOWN, SETUID, SETGID, DAC_OVERRIDE, FOWNER`. Drop any of those
  and the container crash-loops.
- **postgres `initdb` runs once, on an empty volume.** The entrypoint bootstraps only when
  `PGDATA` is empty (it tests for `PG_VERSION`), so on any later start it skips `initdb`,
  `CREATE DATABASE $POSTGRES_DB` *and* `/docker-entrypoint-initdb.d` entirely. Two consequences,
  and the second is the one that surprises people: changing `POSTGRES_*` after first boot does
  nothing, and **dropping the database by hand is equally unrecoverable** — no number of restarts
  will recreate it. `docker compose down -v` is the fix for both, because the volume is the state.
  Tables are a separate mechanism (`init_db` → `alembic upgrade head`) that cannot run at all
  while the database is missing, so "the tables didn't get created either" is a symptom of this,
  not a second fault.
- **The postgres healthcheck must connect to the database, not just to the server.** It is
  `psql … -tAc 'select 1'` and must not go back to `pg_isready`, which reports success for a
  database that does not exist: measured in the running container, `pg_isready -d
  absolutely_no_such_db` exits **0** ("accepting connections") where `psql` exits **2**. With the
  weak check, `depends_on: postgres: condition: service_healthy` gated on nothing — compose called
  postgres healthy, started api and worker on that signal, and both crash-looped with `FATAL:
  database "portfolio" does not exist`, which reads as an application fault rather than an
  uninitialised volume. Confirmed by mutation 2026-08-06: the same container is `unhealthy` under
  `psql` and `healthy` under `pg_isready`.
- **postgres 18+ wants the volume at `/var/lib/postgresql`, not `.../data`.** From 18 the
  official images store data in a major-version-specific subdirectory so `pg_upgrade --link`
  doesn't cross a mount boundary. The pre-18 mount path makes the entrypoint refuse to start
  with "there appears to be PostgreSQL data in: /var/lib/postgresql/data (unused
  mount/volume)" -- which reads as a corrupt volume rather than a wrong path. Bumping the
  image major version means checking the mount, and a pre-18 volume needs `pg_upgrade` or a
  fresh volume; hence `postgres_data_v18`.

## Config invariants

- **`PORT` is the single source of truth** for the api port: gunicorn's `--bind`,
  the compose port mapping, and nginx's upstream (baked in at nginx build time by
  `sed` on the `__API_PORT__` placeholder). Deliberately not nginx's `envsubst`
  templates -- those substitute every `$`-token and would wipe nginx's own
  `$scheme`/`$remote_addr` too. `GUNICORN_TIMEOUT` and `MAX_UPLOAD_SIZE_MB` reach
  nginx the same way (`REQUEST_TIMEOUT`/`MAX_UPLOAD_MB` build args), and the nginx
  build fails on any unsubstituted `__PLACEHOLDER__`.
- **Compose needs `--env-file` or none of that works.** Run it as
  `docker compose -f .docker/docker-compose.yml --env-file .env up` from `portfolio/`.
  Compose reads `${VAR}` from the shell or a `.env` in the *project directory*
  (`.docker/`) -- never from `portfolio/.env`, and `env_file:` on a service doesn't
  help (different mechanism). Measured: both documented invocation styles silently
  used the fallback defaults. And the halves disagree, so it doesn't error --
  `PORT=9000` in `.env` alone gives gunicorn on 9000, a mapping of `8000:8000`, and
  an nginx upstream on `api:8000`.
- **Timeouts are one value, not three.** gunicorn `--timeout` and nginx's
  `proxy_read_timeout`/`client_body_timeout` are all 120s from `GUNICORN_TIMEOUT`,
  because the shorter one silently becomes the real budget: nginx-first is a 504 with
  the worker still burning CPU, gunicorn-first is a SIGKILL mid-parse that reaches the
  client as a bare connection failure naming nothing. `proxy_connect_timeout` stays 75s
  on purpose -- nginx caps it there regardless, so a larger number is decoration.
  The 120s gunicorn value predates Phase 5.1 (uploads became jobs the same day it was last
  raised) and no longer has a stated reason to exceed a normal default -- `client_body_timeout`
  is different, since bytes still arrive over the wire regardless of what processes them.
  `--graceful-timeout`
  (630s, `GUNICORN_GRACEFUL_TIMEOUT`) is a fourth, unrelated number -- how long a worker
  gets to finish in-flight requests after a reload signal before being force-killed, not
  the per-request ceiling above. It has no recorded reasoning for 630s and was not
  re-derived when `GUNICORN_TIMEOUT` last changed; it only needs to stay `>=
  GUNICORN_TIMEOUT`.
  **`DOCLING_DOCUMENT_TIMEOUT` is a fifth and belongs to the queue, not the request.** Uploads
  return 202 and the worker parses, so no HTTP request waits on Docling -- unifying it with the
  three above would tie a background budget to a request-side one and, at 120s, put back a
  ceiling that rejects any paper over about ten pages. It was hardcoded at 90 in `parser.py`,
  which is Docling's own generic recommendation for the field and is ~7 pages on four cores: it
  rejected **all six** papers of the eval corpus as it stood on 2026-09-16 (six cathode-materials
  reviews, since replaced). Default 600, sized from 6.8-12.1 s/page measured that day. Never set it to `None`/empty -- Docling reads that as no
  ceiling, and an unbounded parse holds one of `WORKER_CONCURRENCY` slots with nothing failing.
  Too *low* is the safe direction: `parse_document` raises on a partial parse, so the document is
  rejected rather than half-indexed.
