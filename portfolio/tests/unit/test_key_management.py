"""`/v1/keys` against a real Postgres, driven through the real ASGI app.

Skipped when no Postgres is reachable, and deliberately not substituted with SQLite -- same
reasoning as `test_auth_touch.py`, with one extra edge here: `ApiKey.scopes` is a Postgres
`ARRAY`, so an engine without it would not be testing the column that ships.

What these cover that the contract tests cannot: the scope list surviving a write and a read
(an ARRAY column is the kind of thing that round-trips as a string when mis-declared), and
revocation being filtered by `tenant_id` in the WHERE clause rather than checked afterwards.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import deps
from app.api.main import app
from app.auth import management
from app.auth.expiry import DEFAULT_EXPIRY_DAYS
from app.auth.models import ApiKey, Tenant
from app.auth.scopes import ALL_SCOPES, ASK, DOCUMENTS_READ, KEYS_READ, KEYS_WRITE, UNRESTRICTED
from app.auth.service import Principal
from app.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    SessionFactory = Callable[[], AsyncSession]

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
    except Exception:  # noqa: BLE001 -- any connection failure means "skip", not "fail"
        return False
    finally:
        await engine.dispose()


async def _truncate(engine: AsyncEngine) -> None:
    """Empty every SQLModel table without dropping it.

    Row-level isolation is all these suites need, and unlike `drop_all` it cannot pull the
    schema out from under a sibling suite. CASCADE because `apikey.tenant_id` is a real
    foreign key, and RESTART IDENTITY so nothing carries a sequence across tests.
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
        # `create_all` only, never `drop_all`. Three suites here build the schema on the same
        # `portfolio_test` database, and a drop in one wipes the tables the next one relies on
        # `init_db` having created -- which surfaces as `relation "documentrecord" does not
        # exist` in a test that has nothing to do with whoever dropped it. Isolation comes from
        # truncating rows below, which is what these tests actually need.
        await conn.run_sync(SQLModel.metadata.create_all)
    # Truncate at *setup* as well as teardown. A test that errors mid-way skips its own
    # teardown, and the next test's fixture then collides inserting the same seed rows --
    # which reports as a setup ERROR in an innocent test and hides the original failure.
    await _truncate(engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def _no_init() -> None:
        """The schema is already built above. The real `init_db` also applies procrastinate's
        schema, which this suite has no use for and which is slow enough to notice.
        """

    monkeypatch.setattr(management, "get_session", _session)
    monkeypatch.setattr(management, "init_db", _no_init)

    async with factory() as session:
        session.add_all([Tenant(id=TENANT_A, name="Acme"), Tenant(id=TENANT_B, name="Globex")])
        await session.commit()

    yield factory
    await _truncate(engine)
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def authenticate() -> Iterator[Callable[[str, list[str]], None]]:
    def _as(tenant_id: str, scopes: list[str]) -> None:
        # A fresh key id per call, because the rate limiter buckets on it against a *real*
        # Redis whose counters outlive the test. A fixed id makes the eleventh request of the
        # session a 429 -- which surfaces as an unrelated test failing, intermittently, in
        # whatever order pytest happened to pick.
        key_id = f"key-{uuid.uuid4().hex}"
        app.dependency_overrides[deps.current_principal] = lambda: Principal(
            tenant_id=tenant_id, key_id=key_id, scopes=scopes
        )

    yield _as
    app.dependency_overrides.clear()


async def test_a_created_key_is_returned_once_and_stored_only_hashed(
    db: SessionFactory, client: AsyncClient, authenticate: Callable[[str, list[str]], None]
) -> None:
    authenticate(TENANT_A, UNRESTRICTED)

    response = await client.post("/v1/keys", json={"name": "ci", "scopes": [ASK]})

    assert response.status_code == 201
    body = response.json()
    assert body["key"].startswith("pf_live_")

    async with db() as session:
        stored = (await session.exec(select(ApiKey))).all()
    assert len(stored) == 1
    assert body["key"] not in (stored[0].key_hash, stored[0].prefix)
    assert stored[0].scopes == [ASK], "the scope list must survive the ARRAY column verbatim"

    listed = await client.get("/v1/keys")
    assert listed.status_code == 200
    assert "key" not in listed.json()[0], "only the create response may carry the plaintext"


async def test_omitting_scopes_copies_the_callers_own_rather_than_storing_empty(
    db: SessionFactory, client: AsyncClient, authenticate: Callable[[str, list[str]], None]
) -> None:
    """The escalation `exceeds` cannot see. An empty stored list means *unrestricted*, so a
    key holding only `keys:write` that omitted the field would mint itself an unrestricted
    key -- and `exceeds([], holder)` is vacuously empty, so the guard never fires.
    """
    authenticate(TENANT_A, [KEYS_WRITE, KEYS_READ])

    response = await client.post("/v1/keys", json={"name": "inherited"})

    assert response.status_code == 201
    async with db() as session:
        stored = (await session.exec(select(ApiKey))).all()
    assert stored[0].scopes == [KEYS_READ, KEYS_WRITE], "must be materialised, never left empty"
    assert response.json()["scopes"] == [KEYS_READ, KEYS_WRITE]


async def test_an_explicit_json_null_for_scopes_behaves_exactly_like_omitting_it(
    db: SessionFactory, client: AsyncClient, authenticate: Callable[[str, list[str]], None]
) -> None:
    """`{"scopes": null}` used to be a 422 while an omitted field succeeded.

    The difference is invisible from the caller's side, because most generated clients serialise
    an unset optional field as an explicit null -- and `expires_in_days` next door already
    accepted `null`, so the schema disagreed with itself about what "not specified" looks like.

    Accepting it is safe for the reason the test above establishes: the escalation guard runs on
    the *materialised* value, not on what was submitted, so all three spellings -- omitted,
    `null`, `[]` -- resolve to the caller's own scopes and none can store an empty list.
    """
    authenticate(TENANT_A, [KEYS_WRITE, KEYS_READ])

    response = await client.post("/v1/keys", json={"name": "explicit-null", "scopes": None})

    assert response.status_code == 201
    async with db() as session:
        stored = (await session.exec(select(ApiKey))).all()
    assert stored[0].scopes == [KEYS_READ, KEYS_WRITE], "must be materialised, never left empty"


async def test_an_unrestricted_caller_materialises_every_scope(
    db: SessionFactory, client: AsyncClient, authenticate: Callable[[str, list[str]], None]
) -> None:
    authenticate(TENANT_A, UNRESTRICTED)

    response = await client.post("/v1/keys", json={"name": "everything"})

    async with db() as session:
        stored = (await session.exec(select(ApiKey))).all()
    assert stored[0].scopes == list(ALL_SCOPES)
    assert response.json()["scopes"] == list(ALL_SCOPES)


async def test_a_key_expires_in_thirty_days_unless_told_otherwise(
    db: SessionFactory, client: AsyncClient, authenticate: Callable[[str, list[str]], None]
) -> None:
    """The default is a deadline, not "never". Both are defensible; only one is safe as the
    value people get by not thinking about it.
    """
    authenticate(TENANT_A, UNRESTRICTED)

    defaulted = await client.post("/v1/keys", json={"name": "default"})
    forever = await client.post("/v1/keys", json={"name": "forever", "expires_in_days": None})

    assert defaulted.json()["expires_at"] is not None
    assert forever.json()["expires_at"] is None

    async with db() as session:
        stored = {key.name: key for key in (await session.exec(select(ApiKey))).all()}
    # Rounded, not floored. `expires_at` is computed from the application clock and
    # `created_at` from Postgres's, so the gap is a few milliseconds short of the interval and
    # `timedelta.days` truncates it to 29.
    created_at, expires_at = stored["default"].created_at, stored["default"].expires_at
    assert created_at is not None
    assert expires_at is not None
    assert round((expires_at - created_at).total_seconds() / 86400) == DEFAULT_EXPIRY_DAYS


async def test_listing_never_shows_another_tenants_keys(
    db: SessionFactory, client: AsyncClient, authenticate: Callable[[str, list[str]], None]
) -> None:
    authenticate(TENANT_A, UNRESTRICTED)
    await client.post("/v1/keys", json={"name": "a-key"})
    authenticate(TENANT_B, UNRESTRICTED)
    await client.post("/v1/keys", json={"name": "b-key"})

    listed = await client.get("/v1/keys")

    assert [key["name"] for key in listed.json()] == ["b-key"]


async def test_revoking_another_tenants_key_is_404_and_leaves_it_alive(
    db: SessionFactory, client: AsyncClient, authenticate: Callable[[str, list[str]], None]
) -> None:
    """404 rather than 403: distinguishing "not yours" from "does not exist" would confirm
    that a given key id is real. The second half matters more -- a check that returns the
    right status while still performing the write is the bug this shape prevents.
    """
    authenticate(TENANT_A, UNRESTRICTED)
    created = await client.post("/v1/keys", json={"name": "a-key"})
    key_id = created.json()["key_id"]

    authenticate(TENANT_B, UNRESTRICTED)
    response = await client.delete(f"/v1/keys/{key_id}")

    assert response.status_code == 404
    async with db() as session:
        stored = await session.get(ApiKey, key_id)
    assert stored is not None
    assert stored.revoked_at is None


async def test_revoking_your_own_key_records_a_timestamp_rather_than_deleting(
    db: SessionFactory, client: AsyncClient, authenticate: Callable[[str, list[str]], None]
) -> None:
    """A deleted row cannot answer "was this leaked key ever used?"."""
    authenticate(TENANT_A, UNRESTRICTED)
    key_id = (await client.post("/v1/keys", json={"name": "a-key"})).json()["key_id"]

    response = await client.delete(f"/v1/keys/{key_id}")

    assert response.status_code == 204
    async with db() as session:
        stored = await session.get(ApiKey, key_id)
    assert stored is not None
    assert stored.revoked_at is not None

    still_listed = await client.get("/v1/keys")
    assert [key["name"] for key in still_listed.json()] == ["a-key"], (
        "revoked keys stay in the list -- the audit question is usually about a key that stopped working"
    )


async def test_a_narrow_key_cannot_widen_itself_through_the_api(
    db: SessionFactory, client: AsyncClient, authenticate: Callable[[str, list[str]], None]
) -> None:
    """The end-to-end version of the escalation guard: nothing is written, not merely a 403."""
    authenticate(TENANT_A, [KEYS_WRITE, DOCUMENTS_READ])

    response = await client.post("/v1/keys", json={"name": "wider", "scopes": ["documents:write"]})

    assert response.status_code == 403
    async with db() as session:
        assert (await session.exec(select(ApiKey))).all() == []
