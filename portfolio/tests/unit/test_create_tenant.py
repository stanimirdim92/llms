"""`scripts/create_tenant.py` -- the only way to get a first usable API key.

Untested until now, which is the wrong way round: this CLI is what a new deployment runs
before anything else, its mistakes are unrecoverable (a revoked key's plaintext cannot be
reissued), and it is the one caller that mints an *unrestricted* key. Nothing about it is
exercised by the HTTP contract tests, because the HTTP routes deliberately cannot mint
unrestricted keys -- see `test_scopes.py::test_an_unrestricted_key_can_confer_anything`.

Split in two. The argument-parsing half is pure and always runs. The rest
needs a real Postgres and skips without one, for the same reason `test_auth_touch.py` does:
`revoke`'s guard *is* a two-column WHERE clause, and there is nothing left to test once the
query is faked.

Loaded with `importlib` from its path rather than imported: `scripts/` is not a package (no
`__init__.py`, and it is not shipped in the image), so `from scripts.create_tenant import ...`
would only work by accident of the current working directory.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app import db as app_db
from app.auth.keys import hash_key
from app.auth.models import ApiKey, Tenant
from app.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from types import ModuleType

    SessionFactory = Callable[[], AsyncSession]


def _load_cli() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "create_tenant.py"
    spec = importlib.util.spec_from_file_location("create_tenant_cli", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli()


# ---------------------------------------------------------------------------------------------
# Pure: argument handling. No database.
#
# The `_state`/`_day` tests that used to live here moved to `test_key_expiry.py` along with the
# functions themselves: the same two were implemented in this CLI and in the Streamlit key page,
# with different wording, and `app/auth/expiry.py` now owns one copy.
# ---------------------------------------------------------------------------------------------


async def test_revoking_without_a_tenant_is_refused_before_any_database_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard that makes `--tenant` more than decoration, and it has to run *before*
    `init_db` -- otherwise the refusal is unreachable on a machine with no database, which is
    exactly where a mistyped command is likeliest.
    """
    monkeypatch.setattr(sys, "argv", ["create_tenant.py", "--revoke", "some-key-id"])
    monkeypatch.setattr(cli, "init_db", _must_not_run)

    with pytest.raises(SystemExit) as excinfo:
        await cli.main()

    assert excinfo.value.code == 2  # argparse's own usage-error code


async def test_no_arguments_prints_help_without_a_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`init_db` used to run before the dispatch, so the bare invocation -- the one a
    first-time reader types -- answered with a psycopg connection error instead of usage.
    """
    monkeypatch.setattr(sys, "argv", ["create_tenant.py"])
    monkeypatch.setattr(cli, "init_db", _must_not_run)

    await cli.main()

    assert "usage:" in capsys.readouterr().out


async def _must_not_run() -> None:
    raise AssertionError("init_db must not be reached on this path")


# ---------------------------------------------------------------------------------------------
# Against a real Postgres. Skipped when unreachable; never substituted with SQLite.
# ---------------------------------------------------------------------------------------------

TENANT_A = "a" * 32
TENANT_B = "b" * 32


def _test_database_url() -> str:
    url = get_settings().database_url.get_secret_value()
    base, _, name = url.rpartition("/")
    return f"{base}/{name}_test"


async def _postgres_reachable(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect():
            return True
    except Exception:  # any connection failure means "skip", not "fail"
        return False
    finally:
        await engine.dispose()


async def _truncate(engine: AsyncEngine) -> None:
    """Empty every SQLModel table without dropping it -- three suites share this database and a
    `drop_all` here pulls the schema out from under whichever one runs next.
    """
    tables = ", ".join(f'"{table.name}"' for table in reversed(SQLModel.metadata.sorted_tables))
    if not tables:
        return
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SessionFactory]:
    url = _test_database_url()
    if not await _postgres_reachable(url):
        pytest.skip(f"no Postgres at {url.rsplit('@', 1)[-1]} -- start it with docker compose")

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        # The production migration path, not `create_all` -- see the note in
        # `test_worker_enqueue.py`'s fixture. `create_all` never adds a column to a table that
        # already exists, so an existing `portfolio_test` silently keeps an old schema.
        await app_db._migrate_to_head(conn)
    # At setup as well as teardown: a test that errors mid-way skips its own teardown, and the
    # next one then collides on a fixed primary key and reports as a setup ERROR elsewhere.
    await _truncate(engine)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    # The CLI does `from app.db import get_session`, which binds the name in *its* namespace --
    # patching `app.db.get_session` would leave the script still calling the real one.
    monkeypatch.setattr(cli, "get_session", _session)
    yield factory

    await _truncate(engine)
    await engine.dispose()


async def _stored(factory: SessionFactory, key_id: str) -> ApiKey:
    """The row, or a failure that says the row is missing.

    A bare `session.get(...)` is `ApiKey | None`, so reading `.revoked_at` off it typechecks
    only by accident -- and a test whose assertion silently ran against `None` would pass for
    the wrong reason.
    """
    async with factory() as session:
        stored = await session.get(ApiKey, key_id)
    assert stored is not None, f"no key {key_id} in the database"
    return stored


async def _seed_key(factory: SessionFactory, *, tenant_id: str = TENANT_A, key_id: str | None = None) -> str:
    """A tenant and one key for it, committed in that order.

    Two transactions, because `ApiKey.tenant_id` is a real foreign key and the models declare
    no ORM `relationship()` -- so SQLAlchemy cannot order the inserts itself.
    """
    key_id = key_id or uuid.uuid4().hex
    async with factory() as session:
        if await session.get(Tenant, tenant_id) is None:
            session.add(Tenant(id=tenant_id, name="Acme"))
            await session.commit()
    async with factory() as session:
        session.add(
            ApiKey(
                id=key_id,
                tenant_id=tenant_id,
                # Derived from `key_id` because `apikey.key_hash` is UNIQUE -- a constant here
                # let one test pass and the next fail on a duplicate-key violation that named
                # the index rather than the fixture.
                key_hash=hash_key(f"pf_live_{key_id}"),
                prefix="pf_live_xxxx",
                name="ci",
            )
        )
        await session.commit()
    return key_id


async def test_creating_a_tenant_mints_a_key_whose_hash_matches_what_was_printed(
    db: SessionFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one property the whole CLI exists for: the plaintext printed once must be the key
    the database will later authenticate. Only the hash is stored, so if these ever disagree
    the operator holds a string that nothing accepts and no error says so.
    """
    await cli.create_tenant("Acme Corp", "bootstrap", 30)

    printed = [line.split()[-1] for line in capsys.readouterr().out.splitlines() if line.startswith("key ")]
    assert len(printed) == 1
    async with db() as session:
        stored = (await session.exec(select(ApiKey))).all()
    assert len(stored) == 1
    assert stored[0].key_hash == hash_key(printed[0])
    assert stored[0].expires_at is not None


async def test_never_stores_no_deadline_rather_than_a_far_future_one(db: SessionFactory) -> None:
    """`--expires-in never` has to mean NULL, not "a hundred years": `auth/service.py` reads
    NULL as never, and a sentinel date would silently retire the bootstrap key one day.
    """
    await cli.create_tenant("Acme Corp", "bootstrap", None)

    async with db() as session:
        stored = (await session.exec(select(ApiKey))).all()
    assert stored[0].expires_at is None


async def test_adding_a_key_to_an_unknown_tenant_is_refused(db: SessionFactory) -> None:
    """Without the existence check the insert fails on the foreign key instead -- a psycopg
    IntegrityError traceback, from which the actual problem (a mistyped tenant id) is not
    obvious. And the failure must not be a *success*: `ApiKey` rows are the credential table.
    """
    with pytest.raises(SystemExit) as excinfo:
        await cli.add_key("nonexistent", "ci", 30)

    assert excinfo.value.code == 1
    async with db() as session:
        assert (await session.exec(select(ApiKey))).all() == []


async def test_a_key_cannot_be_revoked_through_the_wrong_tenant(db: SessionFactory) -> None:
    """The typo guard, and the same shape as the HTTP route's authorization boundary. Both ids
    must agree; `revoke` filtering on `key_id` alone would cut off whichever customer that id
    happened to name, unrecoverably.
    """
    key_id = await _seed_key(db, tenant_id=TENANT_A)
    async with db() as session:
        session.add(Tenant(id=TENANT_B, name="Other"))
        await session.commit()

    with pytest.raises(SystemExit) as excinfo:
        await cli.revoke(TENANT_B, key_id)

    assert excinfo.value.code == 1
    assert (await _stored(db, key_id)).revoked_at is None


async def test_revoking_the_right_key_stamps_it(db: SessionFactory) -> None:
    key_id = await _seed_key(db, tenant_id=TENANT_A)

    await cli.revoke(TENANT_A, key_id)

    assert (await _stored(db, key_id)).revoked_at is not None


async def test_revoking_twice_leaves_the_first_timestamp_alone(db: SessionFactory) -> None:
    """Idempotent, and it must not re-stamp: `revoked_at` is the audit answer to "when did we
    cut this off", so a second accidental run would move the date to today.
    """
    key_id = await _seed_key(db, tenant_id=TENANT_A)
    await cli.revoke(TENANT_A, key_id)
    first = (await _stored(db, key_id)).revoked_at

    await cli.revoke(TENANT_A, key_id)

    assert (await _stored(db, key_id)).revoked_at == first


async def test_listing_nothing_says_so_instead_of_printing_an_empty_table(
    db: SessionFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    await cli.list_all()

    assert "no tenants yet" in capsys.readouterr().out


async def test_listing_shows_each_tenants_own_keys(db: SessionFactory, capsys: pytest.CaptureFixture[str]) -> None:
    """`list_all` reads every tenant and every key and then pairs them in Python. The pairing is
    the part worth pinning: it is a comprehension over `keys`, so getting it wrong prints one
    tenant's credentials under another tenant's heading.
    """
    key_a = await _seed_key(db, tenant_id=TENANT_A)
    key_b = await _seed_key(db, tenant_id=TENANT_B)

    await cli.list_all()

    lines = capsys.readouterr().out.splitlines()
    heading_a = next(index for index, line in enumerate(lines) if line.startswith(TENANT_A))
    heading_b = next(index for index, line in enumerate(lines) if line.startswith(TENANT_B))
    under_a = lines[heading_a + 1]
    under_b = lines[heading_b + 1]
    assert key_a in under_a
    assert key_b in under_b
