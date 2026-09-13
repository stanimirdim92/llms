"""`GET /v1/documents/{doc_id}/content`: viewing a document reconstructed from its own chunks.

The point this route exists for -- see `docs/EPIC_4_PLAN.md` 5.5 -- is that it needs no prior
`/ask` call and no search to have run: today the only way to see what is inside a document is
indirectly, through a retrieved-chunks list that only exists once a question has been asked.
These tests exercise the routing -- ownership, ingestion status, wiring the store's chunks into
the response -- not the reconstruction itself (`tests/unit/test_document_view.py`) or the real
Qdrant scroll (`tests/unit/test_qdrant_filtering.py`, next to the rest of `QdrantStore`).
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.documents import Document

from app.api import deps
from app.api.main import app
from app.api.routers import documents as documents_router
from app.auth.scopes import UNRESTRICTED
from app.auth.service import Principal
from app.registry.models import STATUS_INGESTED, STATUS_PENDING, DocumentRecord

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

TENANT_A = "a" * 32


async def _skip_init_db() -> None:
    return None


@contextlib.asynccontextmanager
async def _no_db_session():  # noqa: ANN202
    """Stands in for `app.db.get_session`. Every test in this file stubs `get_document_record`
    too, so the session this yields is never actually queried -- see
    `test_intent_routing.py`'s copy of this same stand-in.
    """
    yield None


def _fresh_key_id() -> str:
    """See `test_api_contract.py`'s copy of this fixture: a fixed id would 429 later tests
    against the real Redis they share.
    """
    return f"key-{uuid.uuid4().hex}"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def as_tenant_a() -> Iterator[None]:
    key_id = _fresh_key_id()
    app.dependency_overrides[deps.current_principal] = lambda: Principal(
        tenant_id=TENANT_A, key_id=key_id, scopes=UNRESTRICTED
    )
    yield
    app.dependency_overrides.clear()


def _record(*, ingestion_version: str | None, status: str = STATUS_INGESTED) -> DocumentRecord:
    return DocumentRecord(
        doc_id="doc-a",
        tenant_id=TENANT_A,
        filename="report.pdf",
        content_hash="hash",
        file_extension=".pdf",
        file_size_bytes=100,
        status=status,
        ingestion_version=ingestion_version,
    )


async def test_viewing_a_document_requires_a_key(client: AsyncClient) -> None:
    response = await client.get("/v1/documents/doc-a/content")

    assert response.status_code == 401


@pytest.mark.usefixtures("as_tenant_a")
async def test_an_unowned_document_is_404(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _not_found(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(documents_router, "init_db", _skip_init_db)
    monkeypatch.setattr(documents_router, "get_session", _no_db_session)
    monkeypatch.setattr(documents_router, "get_document_record", _not_found)

    response = await client.get("/v1/documents/doc-a/content")

    assert response.status_code == 404


@pytest.mark.usefixtures("as_tenant_a")
async def test_a_still_ingesting_document_is_409_not_an_empty_view(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 11: refuse rather than answer from the wrong material.

    A `pending` or `failed` document has no active generation, so there is nothing indexed to
    reconstruct -- this must not answer from an empty view that could be mistaken for "this
    document really has no content".
    """

    async def _pending(*_args: object, **_kwargs: object) -> DocumentRecord:
        return _record(ingestion_version=None, status=STATUS_PENDING)

    monkeypatch.setattr(documents_router, "init_db", _skip_init_db)
    monkeypatch.setattr(documents_router, "get_session", _no_db_session)
    monkeypatch.setattr(documents_router, "get_document_record", _pending)

    response = await client.get("/v1/documents/doc-a/content")

    assert response.status_code == 409
    assert "report.pdf" in response.json()["detail"]


@pytest.mark.usefixtures("as_tenant_a")
async def test_the_document_is_reconstructed_in_the_order_the_store_returns(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`QdrantStore.get_document_chunks` already sorts by `order_index` -- this route must not
    re-sort or otherwise second-guess that order, just render it.
    """

    async def _ingested(*_args: object, **_kwargs: object) -> DocumentRecord:
        return _record(ingestion_version="v" * 32)

    class _Store:
        def get_document_chunks(self, doc_id: str, tenant_id: str, versions: list[str]) -> list[Document]:
            assert doc_id == "doc-a"
            assert tenant_id == TENANT_A
            assert versions == ["v" * 32]
            return [
                Document(page_content="Intro paragraph.", metadata={"chunk_type": "text"}),
                Document(page_content="ignored", metadata={"chunk_type": "table", "markdown": "| a | b |"}),
                Document(page_content="Conclusion paragraph.", metadata={"chunk_type": "text"}),
            ]

    monkeypatch.setattr(documents_router, "init_db", _skip_init_db)
    monkeypatch.setattr(documents_router, "get_session", _no_db_session)
    monkeypatch.setattr(documents_router, "get_document_record", _ingested)
    monkeypatch.setattr(documents_router, "_store", _Store)

    response = await client.get("/v1/documents/doc-a/content")

    assert response.status_code == 200
    body = response.json()
    assert body["doc_id"] == "doc-a"
    assert body["filename"] == "report.pdf"
    content = body["content"]
    assert content.index("Intro paragraph.") < content.index("| a | b |") < content.index("Conclusion paragraph.")


@pytest.mark.usefixtures("as_tenant_a")
async def test_a_table_renders_its_markdown_not_its_possibly_captioned_text(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A table chunk's `page_content` may carry a caption prepended onto it for embedding
    quality (see `chunker.py`); the view must render the stored `markdown` field instead, or a
    captioned table would show the caption glued directly onto the grid with no separation.
    """

    async def _ingested(*_args: object, **_kwargs: object) -> DocumentRecord:
        return _record(ingestion_version="v" * 32)

    class _Store:
        def get_document_chunks(self, *_args: object, **_kwargs: object) -> list[Document]:
            return [
                Document(
                    page_content="Table 1: results.\n\n| a | b |",
                    metadata={"chunk_type": "table", "markdown": "| a | b |"},
                )
            ]

    monkeypatch.setattr(documents_router, "init_db", _skip_init_db)
    monkeypatch.setattr(documents_router, "get_session", _no_db_session)
    monkeypatch.setattr(documents_router, "get_document_record", _ingested)
    monkeypatch.setattr(documents_router, "_store", _Store)

    response = await client.get("/v1/documents/doc-a/content")

    assert response.json()["content"] == "| a | b |"
