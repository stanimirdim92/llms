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
from app.retrieval.document_scope import DocumentScope

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

TENANT_A = "a" * 32
TENANT_B = "b" * 32


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def as_tenant_a() -> Iterator[None]:
    """Authenticate every request as TENANT_A without a database or a real key."""
    app.dependency_overrides[deps.current_tenant] = lambda: TENANT_A
    yield
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

    monkeypatch.setattr(ask_router, "list_document_records", _tripwire)
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
