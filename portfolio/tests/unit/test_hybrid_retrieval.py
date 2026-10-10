"""Hybrid retrieval (`HYBRID_SEARCH`): BM25 sparse search fused with dense, through Qdrant's own
engine in process -- the same approach as `test_qdrant_filtering.py`, for the same reason: a
filter that looks right and leaks only shows up when a query actually runs.

The sparse half is a second read of tenant data, so it has to honour every condition the dense
half does (tenant, document, live version). It is also the half that may fail open, and the half
that must reach every delete.

Dense embeddings are faked so that the exact-term chunk is the one dense search ranks last: any
appearance of it in the top results got there through BM25.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from app.ingestion.models import Chunk
from app.retrieval.bm25 import document_vector, query_vector, tokens
from app.vectorstore.qdrant_store import (
    SPARSE_VECTOR,
    QdrantStore,
    _build_filter,
    _ensure_sparse_collection,
    _fuse,
    sparse_collection_name,
)

if TYPE_CHECKING:
    import pytest

TENANT_A = "a" * 32
TENANT_B = "b" * 32
LIVE = "l" * 32
OLD = "o" * 32


class _NeedleLastEmbeddings(Embeddings):
    """Puts any text mentioning AdaMem orthogonal to every query, so dense search ranks the needle
    dead last. Anything that brings it into the top results did so through BM25.
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 1.0, 0.0, 0.0] if "AdaMem" in text else [1.0, 0.0, 0.0, 0.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


def _store(*, hybrid: bool) -> QdrantStore:
    client = QdrantClient(location=":memory:")
    client.create_collection("kb", vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE))
    store = QdrantStore.__new__(QdrantStore)  # no __init__: it calls Voyage for a probe embedding
    store._store = QdrantVectorStore(client=client, collection_name="kb", embedding=_NeedleLastEmbeddings())
    store._sparse_name = None
    if hybrid:
        store._sparse_name = sparse_collection_name("kb")
        _ensure_sparse_collection(client, store._sparse_name)
    return store


def _chunk(doc_id: str, index: int, text: str, tenant_id: str = TENANT_A) -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}-text-{index:04d}", doc_id=doc_id, chunk_type="text", text=text, tenant_id=tenant_id
    )


_FILLER = [_chunk("d1", i, f"general discussion of retrieval evaluation part {i}") for i in range(6)]
_NEEDLE = _chunk("d1", 99, "AdaMem uses bge-large-en-v1.5 over KILT-100w passages")


def _ids(documents: list[Document]) -> list[str]:
    return [document.metadata["chunk_id"] for document in documents]


async def _query(
    store: QdrantStore, question: str, tenant_id: str = TENANT_A, versions: list[str] | None = None
) -> list[str]:
    return _ids(await store.query(question, top_k=3, tenant_id=tenant_id, versions=versions or [LIVE]))


# --- bm25 ------------------------------------------------------------------------------------


def test_identifiers_survive_tokenising_whole_and_in_parts() -> None:
    assert {"bge-large-en-v1.5", "bge", "large", "v1", "kilt-100w", "100w"} <= set(
        tokens("bge-large-en-v1.5 KILT-100w")
    )


def test_question_words_are_not_terms() -> None:
    """Rare in papers, so with IDF they would outscore the actual subject of the question."""
    assert tokens("What does it use?") == ["use"]


def test_term_ids_are_stable_across_processes() -> None:
    """`hash()` is salted per process; a vector written by the worker must match the api's query."""
    assert document_vector("KILT-100w").indices == document_vector("KILT-100w").indices
    assert query_vector("kilt-100w").indices[0] in document_vector("KILT-100w").indices


def test_term_frequency_saturates() -> None:
    once = document_vector("kilt").values[0]
    fifty = document_vector("kilt " * 50).values[0]
    assert once < fifty < 50 * once


# --- fusion ----------------------------------------------------------------------------------


def test_fusion_ranks_by_position_in_both_lists() -> None:
    def doc(chunk_id: str) -> Document:
        return Document(page_content=chunk_id, metadata={"chunk_id": chunk_id})

    fused = _ids(_fuse([doc("a"), doc("b"), doc("c")], [doc("c"), doc("d")], top_k=3))
    assert fused[0] == "c", "in both lists beats first in one"
    assert len(fused) == 3


# --- the store -------------------------------------------------------------------------------


async def test_an_exact_identifier_is_found_that_dense_alone_ranks_nowhere() -> None:
    for hybrid, expected in ((False, False), (True, True)):
        store = _store(hybrid=hybrid)
        store.upsert([*_FILLER, _NEEDLE], LIVE)
        found = _NEEDLE.chunk_id in await _query(store, "Which corpus is KILT-100w?")
        assert found is expected, f"hybrid={hybrid}"


async def test_the_sparse_half_never_returns_another_tenants_chunk() -> None:
    store = _store(hybrid=True)
    store.upsert(_FILLER, LIVE)
    store.upsert([_chunk("d2", 0, "KILT-100w KILT-100w KILT-100w", tenant_id=TENANT_B)], LIVE)
    assert all(not chunk_id.startswith("d2") for chunk_id in await _query(store, "KILT-100w"))


async def test_the_sparse_half_never_returns_a_superseded_generation() -> None:
    store = _store(hybrid=True)
    store.upsert(_FILLER, LIVE)
    store.upsert([_chunk("d3", 0, "KILT-100w only in the old generation")], OLD)
    assert all(not chunk_id.startswith("d3") for chunk_id in await _query(store, "KILT-100w"))


async def test_a_failed_sparse_search_falls_back_to_dense(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(hybrid=True)
    store.upsert([*_FILLER, _NEEDLE], LIVE)

    def _broken(*_args: object) -> list[Document]:
        raise ConnectionError("sparse collection unreachable")

    monkeypatch.setattr(store, "_sparse_search", _broken)
    assert len(await _query(store, "KILT-100w")) == 3


async def test_pruning_reaches_the_sparse_copy() -> None:
    store = _store(hybrid=True)
    store.upsert([_chunk("d4", 0, "KILT-100w first generation")], OLD)
    store.upsert([_chunk("d4", 0, "second generation")], LIVE)
    store.delete_superseded("d4", TENANT_A, keep_version=LIVE)
    client = store._store.client
    sparse_name = cast("str", store._sparse_name)
    assert client.count(sparse_name, exact=True).count == 1


async def test_flag_off_writes_and_reads_no_sparse_collection() -> None:
    store = _store(hybrid=False)
    store.upsert(_FILLER, LIVE)
    client = store._store.client
    assert not client.collection_exists(sparse_collection_name("kb"))
    assert SPARSE_VECTOR == "bm25"
    _build_filter(None, TENANT_A, versions=[LIVE])  # the dense path still builds its usual filter
