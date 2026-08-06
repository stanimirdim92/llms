"""Retrieval may only reach documents Postgres says are `ingested`.

Qdrant and Postgres are written in sequence -- `ingest_document` upserts points, then writes the
registry row -- so a failure between them leaves retrievable chunks behind a row that says
`processing` or `failed`. Qdrant cannot know that; only the registry does. Found in an external
review, 2026-08-05.

These are pure: the registry read is stubbed, because what changed is the retriever's *decision*,
not the SQL. `test_worker_enqueue.py` covers the query itself against a real Postgres.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest
from qdrant_client.models import FieldCondition

from app.retrieval import retriever as retriever_module
from app.retrieval.retriever import Retriever
from app.vectorstore.qdrant_store import _build_filter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

TENANT = "a" * 32


class _RecordingStore:
    """Records whether it was queried at all, and with which `doc_ids`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def query(self, query: str, top_k: int, tenant_id: str, doc_ids: list[str] | None) -> list[Any]:
        self.calls.append({"query": query, "top_k": top_k, "tenant_id": tenant_id, "doc_ids": doc_ids})
        return ["a chunk"]


@pytest.fixture
def stub_registry(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Stub the registry read so these stay pure, and return a setter for the ingested set."""

    @asynccontextmanager
    async def _session() -> AsyncIterator[None]:
        yield None

    async def _noop() -> None:
        return None

    monkeypatch.setattr(retriever_module, "init_db", _noop)
    monkeypatch.setattr(retriever_module, "get_session", _session)

    def _set(ingested: list[str]) -> None:
        async def _list(_session: object, *, tenant_id: str) -> list[str]:
            return ingested

        monkeypatch.setattr(retriever_module, "list_ingested_doc_ids", _list)

    return _set


async def test_a_tenant_with_nothing_ingested_searches_nothing(stub_registry) -> None:  # noqa: ANN001
    """The empty case must not widen into "everything".

    This is the failure the fix had to avoid while making it: passing an empty allow-list into
    `_build_filter` used to fall through to *no* document condition, so "nothing is ingested"
    would have meant "search every point this tenant owns".
    """
    stub_registry([])
    store = _RecordingStore()

    results = await Retriever(store=store).retrieve("anything", tenant_id=TENANT)  # ty: ignore[invalid-argument-type]

    assert results == []
    assert store.calls == [], "Qdrant must not be queried at all when nothing is searchable"


async def test_only_ingested_documents_reach_the_filter(stub_registry) -> None:  # noqa: ANN001
    """A document mid-ingest or failed has points in Qdrant and must stay out of the answer."""
    stub_registry(["doc-ingested"])
    store = _RecordingStore()

    await Retriever(store=store).retrieve("anything", tenant_id=TENANT)  # ty: ignore[invalid-argument-type]

    assert store.calls[0]["doc_ids"] == ["doc-ingested"]


async def test_a_caller_scope_is_intersected_not_trusted(stub_registry) -> None:  # noqa: ANN001
    """Defence in depth: the router 409s an unready document, but this must not depend on that."""
    stub_registry(["doc-a", "doc-b"])
    store = _RecordingStore()

    await Retriever(store=store).retrieve(  # ty: ignore[invalid-argument-type]
        "anything", tenant_id=TENANT, doc_ids=["doc-b", "doc-not-ingested"]
    )

    assert store.calls[0]["doc_ids"] == ["doc-b"]


async def test_a_scope_that_is_no_longer_ingested_refuses_rather_than_widening(stub_registry) -> None:  # noqa: ANN001
    """If the requested document failed since the scope was resolved, answer from nothing.

    Falling back to the tenant's other documents would answer a question about document X from
    document Y -- rule 11, and indistinguishable from a correct answer at the point of use.
    """
    stub_registry(["doc-a"])
    store = _RecordingStore()

    results = await Retriever(store=store).retrieve(  # ty: ignore[invalid-argument-type]
        "anything", tenant_id=TENANT, doc_ids=["doc-failed"]
    )

    assert results == []
    assert store.calls == []


def test_an_empty_doc_id_list_is_refused_by_the_filter_itself() -> None:
    """The last line of defence, in case a future caller skips the retriever.

    Change `is not None` back to a truthiness test in `_build_filter` and this goes red.
    """
    with pytest.raises(ValueError, match="every document"):
        _build_filter(chunk_types=None, tenant_id=TENANT, doc_ids=[])


def test_a_populated_doc_id_list_still_narrows() -> None:
    """The guard must not have broken ordinary scoping."""
    must = _build_filter(chunk_types=None, tenant_id=TENANT, doc_ids=["doc-a"]).must
    assert must is not None, "an unconditioned filter matches every tenant's chunks"
    conditions = must if isinstance(must, list) else [must]
    keys = [c.key for c in conditions if isinstance(c, FieldCondition)]
    assert keys == ["metadata.tenant_id", "metadata.doc_id"]
