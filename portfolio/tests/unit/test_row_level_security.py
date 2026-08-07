"""Proves migration `a4f8c1d92e07`'s row-level security actually stops a cross-tenant read at
the database, not just at the application's own WHERE clause.

Against a real Postgres, skipped when none is reachable -- like every other service-backed
suite here. RLS cannot be simulated: `qdrant_client`'s in-memory engine has an analogue for
Qdrant's filter, but there is no in-memory Postgres that enforces `CREATE POLICY`, and SQLite
is excluded project-wide regardless (`CLAUDE.md` -- Postgres is the only database engine).

The point these tests exist to make is specific: connect as `app_db_user` (never
`postgres_user` -- see `app/db.py::get_engine`'s docstring for why that distinction is the
whole mechanism) and issue a query with **no tenant filter at all**. If any of these pass
while the policy is disabled, they are not testing what their names say -- which is why each
one is paired with a mutation instruction in its docstring instead of trusting the assertion
alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

TENANT_A = "a" * 32
TENANT_B = "b" * 32


def _test_admin_url() -> str:
    url = get_settings().database_url.get_secret_value()
    base, _, name = url.rpartition("/")
    return f"{base}/{name}_test"


def _test_app_url() -> str:
    """Same test database as the admin URL above, but as `app_db_user` -- the role RLS applies
    to. Built by swapping the credential half of the admin URL rather than reading
    `Settings.app_database_url` directly, because that field points at the *development*
    database (`postgres_db`), not the `_test`-suffixed one every other suite here uses.
    """
    settings = get_settings()
    admin_url = _test_admin_url()
    scheme, _, rest = admin_url.partition("://")
    _credentials, _, host_and_db = rest.partition("@")
    return f"{scheme}://{settings.app_db_user}:{settings.app_db_password.get_secret_value()}@{host_and_db}"


async def _reachable(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect():
            return True
    except Exception:  # noqa: BLE001 -- any connection failure means "skip", not "fail"
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def rls() -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    """Two engines against the same test database: `admin` (table owner, bypasses RLS -- used
    only to seed rows and to prove the contrast) and `app` (the role every real request uses).

    Runs the real migration chain via `app_db._migrate_to_head`, exactly like every other
    Postgres-backed fixture here -- this is what creates `app_db_user` and the policy in the
    first place, so a database this fixture hasn't touched yet has neither.
    """
    admin_url = _test_admin_url()
    if not await _reachable(admin_url):
        pytest.skip(f"no Postgres at {admin_url.rsplit('@', 1)[-1]} -- start it with docker compose")

    from app import db as app_db  # noqa: PLC0415

    admin_engine = create_async_engine(admin_url)
    async with admin_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await app_db._migrate_to_head(conn)

    app_engine = create_async_engine(_test_app_url())

    yield admin_engine, app_engine

    await app_engine.dispose()
    await admin_engine.dispose()


async def _seed(admin_engine: AsyncEngine) -> None:
    async with admin_engine.begin() as conn:
        for tenant, doc_id in ((TENANT_A, "a" * 32), (TENANT_B, "b" * 32)):
            await conn.execute(
                text(
                    "INSERT INTO documentrecord "
                    "(doc_id, tenant_id, filename, content_hash, file_extension, file_size_bytes, "
                    " chunk_count, status) "
                    "VALUES (:doc_id, :tenant_id, 'x.pdf', :doc_id, '.pdf', 1, 0, 'pending')"
                ),
                {"doc_id": doc_id, "tenant_id": tenant},
            )


async def test_an_unscoped_query_as_the_app_role_sees_only_the_set_tenant(rls: tuple[AsyncEngine, AsyncEngine]) -> None:
    """The core claim: `SELECT * FROM documentrecord` with **no WHERE clause at all**, as
    `app_db_user`, with `app.tenant_id` set to tenant A, returns tenant A's row and nothing of
    tenant B's -- even though the query never named a tenant.

    Mutation check: drop `FORCE ROW LEVEL SECURITY` from the migration (keep `ENABLE`) and this
    still passes, for the wrong reason -- `app_db_user` isn't the table owner, so `FORCE` makes
    no difference to it specifically. Drop the whole migration and this goes red with both
    rows returned, which is the failure this test exists to catch.
    """
    admin_engine, app_engine = rls
    await _seed(admin_engine)

    async with app_engine.connect() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": TENANT_A})
        rows = (await conn.execute(text("SELECT doc_id, tenant_id FROM documentrecord"))).all()

    assert [r.tenant_id for r in rows] == [TENANT_A], f"expected only tenant A's row, got {rows}"


async def test_no_tenant_context_set_means_zero_rows_not_every_row(rls: tuple[AsyncEngine, AsyncEngine]) -> None:
    """Rule 8's inverse, at the database layer: absent context must mean nothing is visible, not
    everything. `current_setting(..., true)` returns NULL when unset, and `tenant_id = NULL` is
    never true under SQL's three-valued logic -- fail closed, not open.

    Mutation check: change the policy to `current_setting('app.tenant_id', true) IS DISTINCT
    FROM tenant_id` inverted incorrectly, or use `missing_ok=false` (drops the `true` argument)
    and this test starts raising `unrecognized configuration parameter` instead of asserting
    zero rows -- a different failure, but still not "returns everything", which is the one
    outcome that must never happen.
    """
    admin_engine, app_engine = rls
    await _seed(admin_engine)

    async with app_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT doc_id FROM documentrecord"))).all()

    assert rows == [], f"no app.tenant_id was set, and the database returned rows anyway: {rows}"


async def test_inserting_under_a_different_tenant_than_the_session_claims_is_refused(
    rls: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """`WITH CHECK`, not just `USING`: a write, not only a read. `USING` alone only governs which
    *existing* rows are visible to SELECT/UPDATE/DELETE.

    Postgres defaults an omitted `WITH CHECK` to the `USING` expression for a policy covering
    every command (this one does, having no `FOR SELECT`/`FOR INSERT` restriction) -- confirmed
    by deleting the clause outright, which left this test green, not red, because Postgres
    reused `USING` as the check anyway. The real gap is a `WITH CHECK` that's present but
    permissive: mutate the migration's `WITH CHECK` to `(true)` and this insert succeeds
    instead of raising, silently filing tenant B's document under a connection that believes
    it is acting for tenant A. Written explicitly here rather than left to the Postgres default
    so a reader doesn't have to know that default to see the policy covers writes too.
    """
    _admin_engine, app_engine = rls

    async with app_engine.connect() as conn:
        await conn.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": TENANT_A})
        with pytest.raises(Exception, match="row-level security"):
            await conn.execute(
                text(
                    "INSERT INTO documentrecord "
                    "(doc_id, tenant_id, filename, content_hash, file_extension, file_size_bytes, "
                    " chunk_count, status) "
                    "VALUES ('c' || repeat('c', 31), :tenant_id, 'x.pdf', 'x', '.pdf', 1, 0, 'pending')"
                ),
                {"tenant_id": TENANT_B},
            )


async def test_the_admin_role_is_unaffected_by_the_policy(rls: tuple[AsyncEngine, AsyncEngine]) -> None:
    """The other half of the contrast this migration depends on: `postgres_user` (table owner,
    what `get_admin_engine()` connects as) sees every tenant's rows regardless of
    `app.tenant_id`, because it is exempt from RLS by role, not by any setting this test
    controls. That's deliberate -- Alembic and procrastinate's schema apply need it -- and it is
    also exactly why `get_engine()` (every request-time query) must never be this role. If this
    test ever fails, something upstream of it silently exempted the admin role from something
    it shouldn't have needed to be exempt from in the first place, which is worth noticing on
    its own terms rather than only inferring it from the app role's test passing.
    """
    admin_engine, _app_engine = rls
    await _seed(admin_engine)

    async with admin_engine.connect() as conn:
        rows = (await conn.execute(text("SELECT tenant_id FROM documentrecord"))).all()

    assert {r.tenant_id for r in rows} == {TENANT_A, TENANT_B}
