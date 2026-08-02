"""The HTTP contract, exercised through the real ASGI app.

Until now every test was below the HTTP layer, so nothing checked what a client actually
receives: that an unauthenticated call is 401 on *every* route, that a smuggled `session_id` is
refused rather than ignored, that the upload endpoint returns 202 and not 200. Those are the
things a consumer depends on, and the React app of Phase 6 will depend on them harder.

Runs against `httpx.ASGITransport`, which drives the app in-process without a server and
**without running the lifespan** -- so no credentials and no database are needed for the cases
below that don't touch one. The authenticated cases use FastAPI's `dependency_overrides`, which
is only possible because `current_tenant` is a dependency rather than middleware (see
`api/deps.py`); middleware could not be swapped per-test like this.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.main import app
from app.api.routers import ask as ask_router, health
from app.auth.scopes import ALL_SCOPES, DOCUMENTS_READ, UNRESTRICTED
from app.auth.service import Principal
from app.config import get_settings
from app.retrieval.document_scope import DocumentScope

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

TENANT_A = "a" * 32
TENANT_B = "b" * 32


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def as_tenant_a() -> Iterator[None]:
    """Authenticate every request as TENANT_A without a database or a real key.

    Overrides `current_principal`, not `current_tenant`. It is the single seam every other
    piece of auth hangs off -- `current_tenant` derives from it, `require_scopes` reads its
    scopes, and `rate_limited` buckets on its `key_id`. Overriding the narrower dependency
    would leave those two resolving a real key and returning 401.
    """
    app.dependency_overrides[deps.current_principal] = lambda: Principal(
        tenant_id=TENANT_A, key_id="key-for-tenant-a", scopes=UNRESTRICTED
    )
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def as_a_key_holding() -> Iterator[Callable[[list[str]], None]]:
    """Authenticate as TENANT_A with an exact scope list, for the authorization cases.

    Separate from `as_tenant_a` because that fixture is deliberately unrestricted: every test
    written before scopes existed must keep passing unchanged, which is the same
    back-compatibility rule `UNRESTRICTED` encodes.
    """

    def _authenticate(scopes: list[str]) -> None:
        app.dependency_overrides[deps.current_principal] = lambda: Principal(
            tenant_id=TENANT_A, key_id="key-for-tenant-a", scopes=scopes
        )

    yield _authenticate
    app.dependency_overrides.clear()


async def test_ask_requires_a_key(client: AsyncClient) -> None:
    response = await client.post("/v1/ask", json={"question": "what is this?"})

    assert response.status_code == 401


async def test_upload_requires_a_key(client: AsyncClient) -> None:
    """Checked separately from /ask rather than assumed: the dependency is declared per-route,
    so a route added without it is unauthenticated and nothing else would notice.
    """
    response = await client.post("/v1/documents", files={"file": ("x.pdf", b"data", "application/pdf")})

    assert response.status_code == 401


async def test_document_status_requires_a_key(client: AsyncClient) -> None:
    response = await client.get("/v1/documents/abc")

    assert response.status_code == 401


async def test_a_garbage_key_is_401_not_500(client: AsyncClient) -> None:
    """`resolve_tenant` rejects anything that doesn't look like a key before it reaches the
    database, so this stays a 401 even with no Postgres running.
    """
    response = await client.post("/v1/ask", json={"question": "hi"}, headers={"x-api-key": "not-a-key"})

    assert response.status_code == 401


@pytest.mark.usefixtures("as_tenant_a")
async def test_a_smuggled_tenant_field_is_refused(client: AsyncClient) -> None:
    """`AskRequest` sets `extra="forbid"`, so a client still sending the old client-supplied
    scope gets a 422 rather than being silently downgraded to corpus-only results. That silence
    was the original vulnerability: passing another tenant's id read their documents.
    """
    response = await client.post("/v1/ask", json={"question": "hi", "session_id": TENANT_B})

    assert response.status_code == 422


@pytest.mark.usefixtures("as_tenant_a")
async def test_a_smuggled_tenant_id_is_also_refused(client: AsyncClient) -> None:
    response = await client.post("/v1/ask", json={"question": "hi", "tenant_id": TENANT_B})

    assert response.status_code == 422


@pytest.mark.usefixtures("as_tenant_a")
async def test_naming_an_unowned_document_is_404_through_http(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserted at the HTTP layer, not just on `resolve_scope`, because the wiring is what
    broke once: a helper added above `async def ask` took the route decorator with it, and the
    endpoint started returning the helper's type. Unit tests on the resolver all still passed.

    Also pins 404 rather than 403 -- distinguishing "not yours" from "does not exist" would
    confirm to any caller that a given file had been uploaded by somebody.
    """

    async def _no_documents(_question: str, _tenant_id: str) -> DocumentScope:
        return DocumentScope(unknown=["MISSING.pdf"])

    monkeypatch.setattr(ask_router, "_document_scope", _no_documents)
    response = await client.post("/v1/ask", json={"question": "tell me about MISSING.pdf"})

    assert response.status_code == 404
    assert "MISSING.pdf" in response.json()["detail"]


@pytest.mark.usefixtures("as_tenant_a")
async def test_a_question_naming_nothing_never_reads_the_registry(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/ask` is the hot path, so the registry read is gated on a regex. If that gate is lost
    every question pays a query, which shows up as latency rather than as a failure.
    """
    called = False

    async def _tripwire(*_args: object, **_kwargs: object) -> list:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(ask_router, "list_scope_candidates", _tripwire)
    # The answer itself needs Voyage/Anthropic, so this asserts only on the pre-check by
    # letting the call fail afterwards -- the tripwire is what is under test.
    with contextlib.suppress(Exception):
        await client.post("/v1/ask", json={"question": "what cathode materials cycle best?"})

    assert not called, "a question naming no filename must not hit the registry"


@pytest.mark.usefixtures("as_tenant_a")
async def test_an_unsupported_extension_is_rejected_before_any_work(client: AsyncClient) -> None:
    """Rejected on the extension allowlist, so no file is written and no job is queued."""
    response = await client.post("/v1/documents", files={"file": ("archive.zip", b"PK\x03\x04", "application/zip")})

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


@pytest.mark.usefixtures("as_tenant_a")
async def test_an_oversized_upload_is_413(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings  # noqa: PLC0415

    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 0)

    response = await client.post("/v1/documents", files={"file": ("x.pdf", b"bigger than zero", "application/pdf")})

    assert response.status_code == 413


async def test_every_key_route_requires_a_key(client: AsyncClient) -> None:
    """Key management is the highest-value route in the API -- an open one mints credentials."""
    assert (await client.get("/v1/keys")).status_code == 401
    assert (await client.post("/v1/keys", json={"name": "ci"})).status_code == 401
    assert (await client.delete("/v1/keys/abc")).status_code == 401


async def test_a_key_lacking_the_scope_is_403_and_told_which(
    client: AsyncClient, as_a_key_holding: Callable[[list[str]], None]
) -> None:
    """403 rather than 404, and the missing scope is named.

    Everywhere else an authorization failure is a 404 to avoid confirming that someone else's
    resource exists. Here the caller is entitled to the tenant and merely holds the wrong
    capability, so there is nothing to hide -- and hiding it produces a client that retries
    forever against a 404 it cannot fix.
    """
    as_a_key_holding([DOCUMENTS_READ])

    response = await client.post("/v1/keys", json={"name": "ci"})

    assert response.status_code == 403
    assert "keys:write" in response.json()["detail"]


async def test_scopes_gate_ask_too(client: AsyncClient, as_a_key_holding: Callable[[list[str]], None]) -> None:
    """Asserted per route, not just on `require_scopes`: the dependency is declared per route,
    so one added without it is reachable by any key and no existing test notices.
    """
    as_a_key_holding([DOCUMENTS_READ])

    response = await client.post("/v1/ask", json={"question": "hi"})

    assert response.status_code == 403


async def test_an_unrestricted_key_passes_every_scope_check(
    client: AsyncClient, as_a_key_holding: Callable[[list[str]], None]
) -> None:
    """The empty list means *every* scope. Pinned at the HTTP layer because reading
    `if not key.scopes` as "denies everything" is the natural misreading, and it would revoke
    every key minted before the column existed.
    """
    as_a_key_holding(UNRESTRICTED)

    response = await client.post("/v1/keys", json={"name": "ci", "scopes": ["nonsense"]})

    assert response.status_code == 400, "an unrestricted key must reach validation, not be denied"


async def test_an_unknown_scope_is_rejected_rather_than_stored(
    client: AsyncClient, as_a_key_holding: Callable[[list[str]], None]
) -> None:
    """A typo'd scope stored verbatim produces a key that authenticates fine and silently
    cannot do the one thing it was created for -- discovered as a 403 much later.
    """
    as_a_key_holding(list(ALL_SCOPES))

    response = await client.post("/v1/keys", json={"name": "ci", "scopes": ["documents:wrote"]})

    assert response.status_code == 400
    assert "documents:wrote" in response.json()["detail"]


async def test_a_key_cannot_grant_a_scope_it_lacks(
    client: AsyncClient, as_a_key_holding: Callable[[list[str]], None]
) -> None:
    """The privilege-escalation guard. Without it, `keys:write` is equivalent to every scope:
    a narrow key mints a wide one and the vocabulary is decorative.
    """
    as_a_key_holding(["keys:write"])

    response = await client.post("/v1/keys", json={"name": "escalated", "scopes": ["documents:write"]})

    assert response.status_code == 403
    assert "documents:write" in response.json()["detail"]


async def test_an_expiry_outside_the_menu_is_refused(
    client: AsyncClient, as_a_key_holding: Callable[[list[str]], None]
) -> None:
    """422 from the `Literal`, not a stored 4000-day key. An arbitrary integer is not a
    lifetime anyone chose; it is a typo that reads as a decision.
    """
    as_a_key_holding(list(ALL_SCOPES))

    response = await client.post("/v1/keys", json={"name": "ci", "expires_in_days": 4000})

    assert response.status_code == 422


async def test_a_successful_response_advertises_the_remaining_budget(
    client: AsyncClient, as_a_key_holding: Callable[[list[str]], None]
) -> None:
    """Headers on success, not only on the 429.

    This is the whole point of adding them: with headers only on rejection, a client discovers
    its budget by exceeding it. Asserted at the HTTP layer because `rate_limited` sets them on
    an injected sub-response and relies on FastAPI merging that into the real one -- unit tests
    on `Budget.headers()` would pass even if the merge never happened.
    """
    as_a_key_holding(list(ALL_SCOPES))

    response = await client.get("/v1/keys")

    # No assertion on the status: `rate_limited` runs as a dependency, before the handler, so
    # the headers are there whether or not the read itself succeeded. Asserting 200 here would
    # make this test also a Postgres-availability test.
    assert response.headers["x-ratelimit-limit"] == str(get_settings().rate_limit_keys)
    assert int(response.headers["x-ratelimit-remaining"]) >= 0
    assert int(response.headers["x-ratelimit-reset"]) > 0


async def test_exhausting_the_budget_returns_429_with_every_header(
    client: AsyncClient, as_a_key_holding: Callable[[list[str]], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Retry-After` plus `X-RateLimit-*` on the refusal, and `remaining: 0`.

    The limit is monkeypatched to 1 rather than sending 11 requests, so this stays fast and
    does not depend on the configured budget.
    """
    monkeypatch.setattr(get_settings(), "rate_limit_keys", 1)
    as_a_key_holding(list(ALL_SCOPES))

    await client.post("/v1/keys", json={"name": "first", "scopes": ["nonsense"]})
    refused = await client.post("/v1/keys", json={"name": "second", "scopes": ["nonsense"]})

    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1
    assert refused.headers["x-ratelimit-limit"] == "1"
    assert refused.headers["x-ratelimit-remaining"] == "0"


async def test_liveness_needs_no_auth_and_no_dependencies(client: AsyncClient) -> None:
    """An orchestrator can't send an API key, and a liveness probe that checked Postgres would
    restart the process over a database blip.
    """
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_readiness_is_503_when_a_required_dependency_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the endpoint. The `/` it replaced returned 200 here."""

    async def _broken() -> None:
        msg = "connection refused"
        raise ConnectionError(msg)

    async def _fine() -> None:
        return

    monkeypatch.setattr(health, "_probe_postgres", _broken)
    monkeypatch.setattr(health, "_probe_qdrant", _fine)
    monkeypatch.setattr(health, "_probe_redis", _fine)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["dependencies"]["postgres"]["status"] == "down"
    assert "ConnectionError" in body["dependencies"]["postgres"]["detail"]


async def test_readiness_tolerates_redis_being_down(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rate limiting fails open, so a Redis outage degrades a guardrail rather than the API.
    Reporting it as `down` while staying ready is the distinction -- treating it as required
    would take the API out of rotation over a limiter that is designed to be optional.
    """

    async def _broken() -> None:
        msg = "connection refused"
        raise ConnectionError(msg)

    async def _fine() -> None:
        return

    monkeypatch.setattr(health, "_probe_postgres", _fine)
    monkeypatch.setattr(health, "_probe_qdrant", _fine)
    monkeypatch.setattr(health, "_probe_redis", _broken)

    response = await client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["dependencies"]["redis"]["status"] == "down"
    assert body["dependencies"]["redis"]["required"] is False


async def test_readiness_reports_every_dependency_by_name(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A probe that only says yes/no forces whoever is paged to go looking. Naming the failing
    dependency is the difference between a useful alert and a starting point.
    """

    async def _fine() -> None:
        return

    for name in ("_probe_postgres", "_probe_qdrant", "_probe_redis"):
        monkeypatch.setattr(health, name, _fine)

    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert set(response.json()["dependencies"]) == {"postgres", "qdrant", "redis"}


def test_the_api_key_is_declared_as_a_security_scheme() -> None:
    """Not merely accepted as a header.

    A plain `Header()` parameter authenticates identically, so nothing at runtime would catch
    a regression here -- but the two describe themselves very differently. A `securitySchemes`
    entry becomes a client-level credential in a generated client and an Authorize button in
    `/docs`; a bare header becomes a parameter every call site has to remember to pass. The
    Phase 6 React client is generated from this schema, so the distinction is the contract.
    """
    schema = app.openapi()

    scheme = schema["components"]["securitySchemes"]["ApiKeyAuth"]
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "x-api-key"


def test_every_tenant_scoped_route_requires_the_scheme_and_probes_do_not() -> None:
    """Authorization is declared per route here, so a new route that forgets `CurrentTenant`
    is simply open and nothing raises. This asserts on the generated schema, which is the one
    artefact that sees all the routes at once.

    Health endpoints are asserted *unauthenticated* on purpose -- an orchestrator cannot send
    an API key, so putting a probe behind auth takes the service out of rotation.
    """
    paths = app.openapi()["paths"]

    def security(path: str, verb: str) -> object:
        return paths[path][verb].get("security")

    assert security("/v1/ask", "post") == [{"ApiKeyAuth": []}]
    assert security("/v1/documents", "post") == [{"ApiKeyAuth": []}]
    assert security("/v1/documents", "get") == [{"ApiKeyAuth": []}]
    assert security("/v1/documents/{doc_id}", "get") == [{"ApiKeyAuth": []}]
    assert security("/v1/keys", "post") == [{"ApiKeyAuth": []}]
    assert security("/v1/keys", "get") == [{"ApiKeyAuth": []}]
    assert security("/v1/keys/{key_id}", "delete") == [{"ApiKeyAuth": []}]
    assert security("/health/live", "get") is None
    assert security("/health/ready", "get") is None


def test_the_key_header_is_not_also_a_bare_parameter() -> None:
    """Declaring it both ways would make a generated client send it twice -- once as the
    configured credential and once as an explicit argument.
    """
    ask = app.openapi()["paths"]["/v1/ask"]["post"]

    assert "x-api-key" not in [parameter["name"] for parameter in ask.get("parameters", [])]
