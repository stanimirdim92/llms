"""row-level security on documentrecord, and the low-privilege role it requires

Revision ID: a4f8c1d92e07
Revises: 307f47df6135
Create Date: 2026-08-07 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4f8c1d92e07"
down_revision: str | None = "307f47df6135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "portfolio_app"


def upgrade() -> None:
    # **This migration is pointless without the role it creates.** `documentrecord`'s policy
    # below checks `current_setting('app.tenant_id')` against every row -- but Postgres
    # superusers, and the table owner unless FORCE is set (and even FORCE does not touch
    # superusers), bypass row-level security unconditionally. `app/db.py::get_admin_engine`
    # connects as `postgres_user`, which the official postgres Docker image always creates as a
    # superuser; `app/db.py::get_engine` (every request-time query) must therefore connect as a
    # *different*, ordinary role, or this whole migration is a policy nothing ever checks.
    # `app.config.Settings.app_db_password` is what the app actually authenticates with; read it
    # here rather than hardcoding a password in a public repository.
    from app.config import get_settings  # noqa: PLC0415 -- migration-local, not a module-level import

    password = get_settings().app_db_password.get_secret_value()

    # `CREATE ROLE ... IF NOT EXISTS` does not exist in Postgres; the DO block is the standard
    # idiom. Idempotent on purpose: roles are cluster-wide, not per-database, so this same
    # migration runs once per *database* (dev, and every `_test` database the suite creates) but
    # must not fail the second and third time it finds the role already there.
    op.execute(
        sa.text(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{_ROLE}') THEN
                CREATE ROLE {_ROLE} LOGIN;
            END IF;
        END
        $$;
        """)
    )
    # NOT a bind parameter: `ALTER ROLE ... PASSWORD` is DDL, and Postgres's wire protocol
    # doesn't accept `$1`-style placeholders there -- confirmed by trying it first, which
    # failed with a syntax error pointing at the placeholder rather than at anything explaining
    # why. Escaped by doubling embedded single quotes (the standard SQL-literal escape) instead,
    # which is safe here because the value is an operator-controlled deployment secret from
    # `Settings`, not untrusted request input. Reissued unconditionally on every migration run:
    # setting the same password twice is a no-op, and there is no cheap way to check the
    # current one first (Postgres stores it hashed).
    escaped_password = password.replace("'", "''")
    op.execute(sa.text(f"ALTER ROLE {_ROLE} WITH PASSWORD '{escaped_password}'"))

    # Grants covering what already exists (`ALTER DEFAULT PRIVILEGES` below only reaches
    # objects created *after* it runs, so the tables Alembic already built need this explicit
    # pass). `CONNECT`/`USAGE` are the two grants a non-superuser role needs before any table
    # grant means anything.
    op.execute(sa.text(f"GRANT CONNECT ON DATABASE {op.get_bind().engine.url.database} TO {_ROLE}"))
    op.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {_ROLE}"))
    op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_ROLE}"))
    op.execute(sa.text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_ROLE}"))

    # Covers every table this migration's own connection creates *later* -- which includes
    # procrastinate's, applied by `app/db.py::_apply_procrastinate_schema` under the same
    # `postgres_user` role immediately after this migration runs on a fresh database, and any
    # future Alembic revision that adds a table. Without this, a new table is invisible to
    # `app_db_user` until someone remembers a second, manual GRANT -- which is exactly the kind
    # of silent gap this project's own history keeps finding in other layers.
    op.execute(sa.text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_ROLE}"))
    op.execute(sa.text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {_ROLE}"))

    # `FORCE`, not just `ENABLE` -- without it, RLS is skipped for the table's *owner*, which is
    # exactly the role every migration in this project runs as. `ENABLE` alone would make this
    # migration pass its own smoke test (query as `postgres_user`, see one tenant's rows only)
    # for a reason that has nothing to do with the policy: the owner was never subject to it.
    # Neither `FORCE` nor `ENABLE` affects superusers, which is why the role split above is not
    # optional.
    op.execute(sa.text("ALTER TABLE documentrecord ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE documentrecord FORCE ROW LEVEL SECURITY"))

    # `current_setting(..., true)` (the `true` = missing_ok) returns NULL rather than raising
    # when `app.tenant_id` was never set for this transaction -- and `tenant_id = NULL` is never
    # true under SQL's three-valued logic, so an application bug that forgets to set the
    # variable fails CLOSED (zero rows visible) rather than open. `WITH CHECK` is what stops an
    # INSERT or UPDATE from writing a row under a *different* tenant_id than the session claims;
    # `USING` alone only governs which existing rows are visible to SELECT/UPDATE/DELETE.
    op.execute(
        sa.text("""
        CREATE POLICY tenant_isolation ON documentrecord
        USING (tenant_id = current_setting('app.tenant_id', true))
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """)
    )

    # `tenant` and `apikey` deliberately do NOT get this policy. Authentication resolves
    # `tenant_id` *from* a row in `apikey` (by `key_hash`, before the caller's tenant is known
    # at all) -- a policy requiring `app.tenant_id` to already be set would make the lookup that
    # establishes it impossible. RLS's value here is specifically the retrieval/document-access
    # path this project's own failure contracts already worry about; auth resolution is a
    # different threat model (a single indexed lookup keyed on a 256-bit hash, not a filter).


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON documentrecord"))
    op.execute(sa.text("ALTER TABLE documentrecord NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE documentrecord DISABLE ROW LEVEL SECURITY"))

    # Revoke before drop -- `DROP ROLE` refuses while the role still owns privileges anywhere in
    # the cluster, including other databases' `ALTER DEFAULT PRIVILEGES` entries for it. This
    # only cleans up the current database; a role also migrated into `portfolio_test` and
    # `portfolio_migrations_test` needs the same downgrade run there before the role will drop.
    op.execute(sa.text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {_ROLE}"))
    op.execute(sa.text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM {_ROLE}"))
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {_ROLE}"))
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {_ROLE}"))
    op.execute(sa.text(f"REVOKE USAGE ON SCHEMA public FROM {_ROLE}"))
    op.execute(sa.text(f"REVOKE CONNECT ON DATABASE {op.get_bind().engine.url.database} FROM {_ROLE}"))
    op.execute(sa.text(f"DROP ROLE IF EXISTS {_ROLE}"))
