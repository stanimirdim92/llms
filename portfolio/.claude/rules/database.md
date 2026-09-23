---
paths:
  - "**/app/db.py"
  - "**/app/registry/**"
  - "**/app/**/models.py"
  - "**/migrations/**"
  - "**/alembic.ini"
  - "**/app/worker/app.py"
  - "**/scripts/create_tenant.py"
  - "**/tests/unit/test_migrations.py"
  - "**/tests/unit/test_row_level_security.py"
  - "**/tests/unit/test_structural_boundaries.py"
  - "**/tests/unit/test_worker_enqueue.py"
  - "**/.docker/Dockerfile"
---

# Postgres: models, migrations, schema init, row-level security

Path-scoped: loads when a matching file is read. The general rules (`../CLAUDE.md`) and the
cross-cutting contracts (`CLAUDE.md` § Never, § The tenant boundary) still apply.

## Failure contracts

- **`SQLModel` datetime fields need an explicit `sa_column`** in any module using
  `from __future__ import annotations` with `datetime` imported under `TYPE_CHECKING`.
  Without it SQLModel infers the column type from an annotation that is a string it can't
  resolve, failing at *import* time with `issubclass() arg 1 must be a class` -- which
  reads like a library bug rather than a missing argument. Use
  `Column(DateTime(timezone=True))`, which also keeps values aware -- see the next entry.
- **...and `datetime` must ALSO be a runtime import in model modules.** `sa_column` fixes
  the import-time half only. `model_dump()` makes pydantic resolve those stringified
  annotations against the module's *runtime* globals, so a TYPE_CHECKING-only `datetime`
  raises ``PydanticUserError: `X` is not fully defined`` from inside `model_dump`. This is
  not hypothetical: it made every `save_document_record` call fail *after* the Qdrant upsert
  had already committed, so documents were searchable with no row in Postgres, and it
  survived for weeks because it only triggers when a row is actually written -- no import,
  lint, or type check sees it. Import `datetime` normally and `# noqa: TC003` the linter.
  `tests/unit/test_worker_enqueue.py` now covers the registry write path.

- **Schema changes go through Alembic, and `migrations/env.py` must exclude `procrastinate_*`.**
  `init_db` runs `alembic upgrade head` inside the advisory lock; it used to run
  `SQLModel.metadata.create_all`, which creates missing *tables* and never missing *columns*, so
  adding a field changed nothing and the next query failed with `column ... does not exist`.
  Four things not to undo:
  - **`include_object` filters out `procrastinate_*`.** Those tables are not in `SQLModel.metadata`,
    so `--autogenerate` reads them as "should not exist" -- verified by removing the filter, which
    produced `drop_table` for all four. It would delete the job queue.
  - **A database with no `alembic_version` but with `documentrecord` is *stamped*, not migrated.**
    That is what the old `create_all` left behind; `upgrade head` there fails with
    `DuplicateTable`, on every boot. Rule 8, and mutation-confirmed.
  - **`alembic.ini` and `migrations/` are COPYed into the image.** They are runtime files, not
    tooling. Absent, the container boots and fails at the first database call.
  - **CI runs `alembic check`.** Adding a model field without a revision is otherwise invisible
    until production -- the exact failure Alembic was adopted to end.

  `migrations/env.py` imports every model module, because that is where `SQLModel.metadata` gets
  populated now; a model missing there is silently omitted from the migration.

- **`migrations/env.py` must import every model module** -- not `app/db.py::init_db`, which is where
  these imports lived under `create_all` and where they no longer belong. `SQLModel.metadata` is
  populated as an import side effect, so a model whose module is not imported *there* is invisible to
  `--autogenerate`: the revision comes out empty, `alembic check` is satisfied, and the table only
  fails later as "relation does not exist".
- **Schema creation is guarded by a Postgres advisory lock, not just the asyncio one.**
  `init_db`'s `asyncio.Lock` only serializes coroutines inside one process, and the real
  concurrency is `GUNICORN_WORKERS` processes booting at once plus the `worker` container.
  Both Alembic's version check (`_migrate_to_head`, which the lock now covers) and procrastinate's
  existence check are check-then-create, so the loser crashes at startup with
  `DuplicateTable`/`DuplicateObject: type "procrastinate_job_status"
  already exists` -- which reads as a database fault. Observed on the first real boot.
  `pg_advisory_xact_lock` is transaction-scoped on purpose: a session-level lock leaked by a
  crashed process would deadlock every later boot.
  `test_concurrent_processes_can_initialise_the_schema` pins it, and has to use real
  subprocesses -- an `asyncio.gather` version passes even with the lock removed.

- **procrastinate's schema is all-or-nothing.** `schema.sql` has 3 `CREATE TYPE`, 4
  `CREATE TABLE`, and 18 `CREATE FUNCTION`, none of them `OR REPLACE`, and the existence
  check keys only on `procrastinate_jobs`. A partially-applied schema (interrupted apply,
  or a hand-written partial drop) therefore fails every subsequent start and cannot be
  repaired incrementally -- reset with `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`
  on a throwaway database, or drop the volume.

## Test fixtures (the service-backed suites that skip when Postgres/Redis is unreachable)

Their fixtures run **`app.db._migrate_to_head`**, not `SQLModel.metadata.create_all`. That was a
straight reproduction of the failure Alembic was adopted to end: `create_all` never adds a column to
an existing table, so `ingestion_version` was simply absent on any developer's `portfolio_test` and
twelve tests failed with `column ... does not exist`. CI could not see it, because a fresh service
container has no old table -- which is the worst possible place for that asymmetry to live.

## Row-level security: a second, database-enforced layer (2026-08-07)

Everything above is application-level: a query built without `tenant_id` in its WHERE clause
leaks, and the only thing standing between that and production is a human remembering the
rule, `add-endpoint`'s checklist, and `route-audit`. Postgres can enforce the same boundary
itself, independently of whether any given query remembered its filter -- migration
`a4f8c1d92e07` adds that as a second, redundant layer on `documentrecord`, not a replacement
for the WHERE clauses above.

- **RLS is real only because request-time queries run as a non-superuser role.**
  `postgres_user` (`app/db.py::get_admin_engine`) is the postgres image's bootstrap account,
  always a superuser, and superusers bypass row-level security unconditionally -- `FORCE ROW
  LEVEL SECURITY` does not touch them either. `app_db_user` (`app/db.py::get_engine`, used by
  `get_session()` and therefore every request-time query, api and worker alike) is the
  ordinary role RLS actually applies to. **Never point `get_session()`/`get_engine()` at
  `database_url`/`postgres_user`** -- that would make every RLS check pass for the wrong
  reason (nothing was ever checking) rather than the right one.
- **`app/registry/db.py::_set_tenant_context` runs first in every function that touches
  `documentrecord`.** `SELECT set_config('app.tenant_id', tenant_id, true)`, scoped to the
  current transaction only (`is_local=true`). Centralized in the module that already owns
  every query against this table, rather than pushed to call sites, for the same reason the
  WHERE clause lives there: one place to get right instead of N.
- **`current_setting('app.tenant_id', true)` fails closed on a missing context.** The `true`
  (missing_ok) makes an unset variable read as SQL `NULL`, and `tenant_id = NULL` is never
  true -- so a bug that forgets to call `_set_tenant_context` returns *zero rows*, not every
  tenant's. Dropping the `true` turns that into a hard error instead (`unrecognized
  configuration parameter`) rather than "everything visible" -- still not the dangerous
  direction, but worth knowing which failure mode a given mutation produces.
  `tests/unit/test_row_level_security.py` pins this against a real Postgres, connected as
  `app_db_user`, with a deliberately unscoped query -- RLS cannot be simulated in-memory the
  way Qdrant's filter can.
- **`tenant`/`apikey` deliberately do NOT get this policy.** Authentication resolves
  `tenant_id` *from* a row in `apikey`, by `key_hash`, before the caller's tenant is known at
  all -- a policy requiring `app.tenant_id` to already be set would make the lookup that
  establishes it impossible. RLS's value here is specifically the retrieval/document-access
  path; auth resolution is a single indexed lookup keyed on a 256-bit hash, a different threat
  model.
- **`app_db_user`'s grants are broad on purpose (`SELECT`/`INSERT`/`UPDATE`/`DELETE` on every
  table, via `ALTER DEFAULT PRIVILEGES` for future ones too), not narrowed per-table.** RLS is
  what does the narrowing for `documentrecord`; a second, hand-maintained grant list per table
  would be one more thing to remember when a migration adds a table, which is exactly the
  silent-gap shape this project keeps finding elsewhere.
- **`tests/unit/test_structural_boundaries.py` is the other half**, and doesn't need
  Postgres at all: an AST sweep asserting `DocumentRecord` is queried (`select`/`update`/
  `delete`/`session.get`) from `app/registry/db.py` alone. RLS is a backstop for a query that
  forgot its filter; this catches a *new* query built outside the one module that centralizes
  them, before it ships.
