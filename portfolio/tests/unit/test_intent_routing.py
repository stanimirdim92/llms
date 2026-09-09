"""Epic 2 Phase 2.0 (`docs/EPIC_2_PLAN.md`): three of a question's four possible intents must
never reach retrieval at all. Two layers, deliberately kept apart.

- The HTTP-level tests below exercise `/ask`'s routing -- which collaborator gets called for
  which intent -- through the real ASGI app, like `test_api_contract.py`, because the wiring
  between a classified intent and the response it produces is exactly what broke once for a
  helper placed above `async def ask` (see that file's docstring). `_document_summary` is
  monkeypatched wholesale there, the same way those tests monkeypatch `_document_scope` --
  this file's other half tests what it actually does.
- `_document_summary`'s own registry-read-and-format logic is tested directly, with `init_db`/
  `get_session`/`list_document_records` all stubbed, so it needs no live Postgres -- unlike this
  project's six DB-backed suites, which skip when one is unreachable, this one never needs one.

No network: `classify_intent` is monkeypatched to a fixed label throughout, the same way
`test_api_contract.py` monkeypatches `_service`/`_document_scope` rather than exercising
Anthropic. What each intent actually gets classified as is a model judgment call (rule 5) and
belongs to Phase 2.1's golden set, not here.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.main import app
from app.api.routers import ask as ask_router
from app.auth.scopes import UNRESTRICTED
from app.auth.service import Principal
from app.generation.answer_service import Answer
from app.registry.models import STATUS_INGESTED, DocumentRecord

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Iterator

TENANT_A = "a" * 32


def _fresh_key_id() -> str:
    """A distinct rate-limit subject per authentication -- see `test_api_contract.py`'s copy of
    this fixture for why a fixed id would 429 later tests against the real Redis they share.
    """
    return f"key-{uuid.uuid4().hex}"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def as_tenant_a() -> Iterator[None]:
    """Overrides `current_principal`, not `current_tenant` -- see `test_api_contract.py` for why
    the narrower dependency leaves `require_scopes`/`rate_limited` resolving a real key.
    """
    key_id = _fresh_key_id()
    app.dependency_overrides[deps.current_principal] = lambda: Principal(
        tenant_id=TENANT_A, key_id=key_id, scopes=UNRESTRICTED
    )
    yield
    app.dependency_overrides.clear()


def _record(filename: str, *, chunk_count: int = 3) -> DocumentRecord:
    return DocumentRecord(
        doc_id=f"doc-{filename}",
        tenant_id=TENANT_A,
        filename=filename,
        content_hash="hash",
        file_extension=".pdf",
        file_size_bytes=100,
        status=STATUS_INGESTED,
        chunk_count=chunk_count,
    )


def _stub_intent(intent: str) -> Callable[[str], Coroutine[object, object, str]]:
    async def _classify(_question: str) -> str:
        return intent

    return _classify


def _spy_answer_service(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Patches `ask_router._service` with a spy recording whether `AnswerService.answer` ran.

    Records rather than raises: the default `ASGITransport` here re-raises app exceptions (see
    `test_api_contract.py::test_an_unhandled_exception_becomes_a_structured_500`), so a raising
    spy would surface as an opaque crash instead of a clean assertion on `called`.
    """
    called: list[bool] = []

    class _Spy:
        async def answer(self, *_args: object, **_kwargs: object) -> Answer:
            called.append(True)
            return Answer(text="retrieval ran when it must not have", citations=[], retrieved_chunks=[])

    monkeypatch.setattr(ask_router, "_service", _Spy)
    return called


async def _no_scope(_question: str, _tenant_id: str) -> object:
    from app.retrieval.document_scope import DocumentScope  # noqa: PLC0415

    return DocumentScope()


# -------------------------------------------------------------------------------------------
# /ask routing, by classified intent
# -------------------------------------------------------------------------------------------


@pytest.mark.usefixtures("as_tenant_a")
async def test_a_metadata_question_never_touches_retrieval(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Phase 2.0 "Done when": a metadata question returns registry data with no Qdrant call
    at all, asserted on a spy rather than the answer text -- the point is that retrieval never
    runs, which no amount of reading the text alone could prove.
    """

    async def _summary(_tenant_id: str) -> str:
        return "You have 1 document:\n- report.pdf (ingested, 12 chunks)"

    monkeypatch.setattr(ask_router, "classify_intent", _stub_intent("metadata"))
    monkeypatch.setattr(ask_router, "_document_summary", _summary)
    called = _spy_answer_service(monkeypatch)

    response = await client.post("/v1/ask", json={"question": "list my documents"})

    assert response.status_code == 200
    assert not called, "a metadata question must never build an answer through retrieval"
    body = response.json()
    assert body["citations"] == []
    assert body["retrieved_chunks"] == []
    assert body["answer"] == "You have 1 document:\n- report.pdf (ingested, 12 chunks)"


@pytest.mark.usefixtures("as_tenant_a")
async def test_an_out_of_scope_question_is_refused_without_reading_anything(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Docs/EPIC_2_PLAN.md Phase 2.0's other "Done when" clause: out-of-scope is refused, not
    retrieved. Also spies on the registry read -- an out-of-scope question has no reason to touch
    Postgres either.
    """
    registry_called: list[bool] = []

    async def _tripwire(*_args: object, **_kwargs: object) -> list[DocumentRecord]:
        registry_called.append(True)
        return []

    monkeypatch.setattr(ask_router, "classify_intent", _stub_intent("out_of_scope"))
    monkeypatch.setattr(ask_router, "list_document_records", _tripwire)
    answer_called = _spy_answer_service(monkeypatch)

    response = await client.post("/v1/ask", json={"question": "what's the weather today?"})

    assert response.status_code == 200
    assert not answer_called
    assert not registry_called
    body = response.json()
    assert body["citations"] == []
    assert body["retrieved_chunks"] == []


@pytest.mark.usefixtures("as_tenant_a")
async def test_an_aggregate_question_is_refused_as_not_yet_supported(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `aggregate` branch is Phase 2.4, unbuilt -- refusing honestly here beats silently
    routing it through the factual pipeline, which would answer a whole-collection question from
    a handful of chunks and give no sign that is what happened.
    """
    monkeypatch.setattr(ask_router, "classify_intent", _stub_intent("aggregate"))
    called = _spy_answer_service(monkeypatch)

    response = await client.post("/v1/ask", json={"question": "what themes run through my uploads?"})

    assert response.status_code == 200
    assert not called
    assert "aren't supported yet" in response.json()["answer"]


@pytest.mark.usefixtures("as_tenant_a")
async def test_a_factual_question_is_unchanged_from_before_intent_routing_existed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third "Done when" clause: the factual path is byte-identical to today's behaviour.
    Same shape as `test_api_contract.py`'s truncation tests -- `_service` and `_document_scope`
    stubbed, because a real answer needs Voyage and Anthropic.
    """

    class _Stub:
        async def answer(self, _question: str, **_kwargs: object) -> Answer:
            return Answer(text="a real answer", citations=[], retrieved_chunks=[])

    monkeypatch.setattr(ask_router, "classify_intent", _stub_intent("factual"))
    monkeypatch.setattr(ask_router, "_service", _Stub)
    monkeypatch.setattr(ask_router, "_document_scope", _no_scope)

    response = await client.post("/v1/ask", json={"question": "what electrolyte did they use?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "a real answer"


# -------------------------------------------------------------------------------------------
# `_document_summary` itself -- no HTTP layer, no live Postgres
# -------------------------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _no_db_session():  # noqa: ANN202
    """Stands in for `app.db.get_session`. `_document_summary` never uses the yielded session
    itself -- it only passes it through to the also-stubbed `list_document_records` -- so `None`
    is enough, and no real Postgres connection is opened.
    """
    yield None


async def _skip_init_db() -> None:
    return None


async def test_document_summary_reports_every_document_with_status_and_chunk_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _records(*_args: object, **_kwargs: object) -> list[DocumentRecord]:
        return [_record("report.pdf", chunk_count=12), _record("notes.pdf", chunk_count=0)]

    monkeypatch.setattr(ask_router, "init_db", _skip_init_db)
    monkeypatch.setattr(ask_router, "get_session", _no_db_session)
    monkeypatch.setattr(ask_router, "list_document_records", _records)

    summary = await ask_router._document_summary(TENANT_A)

    assert "You have 2 documents:" in summary
    assert "report.pdf (ingested, 12 chunks)" in summary
    assert "notes.pdf (ingested, 0 chunks)" in summary


async def test_document_summary_with_no_documents_says_so_rather_than_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent data must mean the pre-existing behaviour (rule 8's spirit applied to a response,
    not a column): a tenant with nothing uploaded gets told that plainly, not an empty string
    that a client could mistake for a failed request.
    """

    async def _empty(*_args: object, **_kwargs: object) -> list[DocumentRecord]:
        return []

    monkeypatch.setattr(ask_router, "init_db", _skip_init_db)
    monkeypatch.setattr(ask_router, "get_session", _no_db_session)
    monkeypatch.setattr(ask_router, "list_document_records", _empty)

    summary = await ask_router._document_summary(TENANT_A)

    assert "haven't uploaded" in summary


async def test_document_summary_uses_the_singular_for_exactly_one_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _one(*_args: object, **_kwargs: object) -> list[DocumentRecord]:
        return [_record("solo.pdf")]

    monkeypatch.setattr(ask_router, "init_db", _skip_init_db)
    monkeypatch.setattr(ask_router, "get_session", _no_db_session)
    monkeypatch.setattr(ask_router, "list_document_records", _one)

    summary = await ask_router._document_summary(TENANT_A)

    assert summary.startswith("You have 1 document:")
    assert "1 documents" not in summary
