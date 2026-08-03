"""`rerank` -- backend selection and the top-n cut. No network, no model.

Untested until now, and the interesting part is not the ranking (that is the provider's job)
but the three decisions made around it: which backend, whether to call at all, and how many
documents survive. Each fails silently. The wrong backend bills an API the operator thought
they had turned off; a call on an empty list is a paid round trip that cannot change anything;
and a missing cut sends every retrieved chunk to the model, which is the entire cost of the
`/ask` path and the reason `rerank_top_n` exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langchain_core.documents import Document

from app.config import get_settings
from app.retrieval import reranker as reranker_module
from app.retrieval.reranker import rerank

if TYPE_CHECKING:
    from collections.abc import Callable


def _documents(count: int) -> list[Document]:
    return [
        Document(page_content=f"chunk {index}", metadata={"doc_id": "d", "chunk_id": f"d-{index}"})
        for index in range(count)
    ]


class _StubCompressor:
    """Stands in for a `BaseDocumentCompressor`, recording what it was asked to compress.

    Returns the documents unchanged and in order. A real reranker reorders them; that is
    exactly what these tests must not depend on, or they would be asserting the provider's
    behaviour rather than ours.
    """

    def __init__(self, name: str, calls: list[tuple[str, int]]) -> None:
        self.name = name
        self._calls = calls

    async def acompress_documents(self, documents: list[Document], query: str) -> list[Document]:
        self._calls.append((self.name, len(documents)))
        assert query, "the query must reach the compressor -- reranking without it is a no-op"
        return documents


@pytest.fixture
def backends(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Both compressor factories replaced, recording which one was chosen."""
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(reranker_module, "_voyage_compressor", _factory("voyage", calls))
    monkeypatch.setattr(reranker_module, "_local_compressor", _factory("local", calls))
    return calls


def _factory(name: str, calls: list[tuple[str, int]]) -> Callable[[], _StubCompressor]:
    return lambda: _StubCompressor(name, calls)


async def test_the_default_backend_is_voyage(backends: list[tuple[str, int]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "reranker_backend", "voyage")

    await rerank("why?", _documents(3))

    assert [name for name, _ in backends] == ["voyage"]


async def test_the_local_backend_is_used_when_selected(
    backends: list[tuple[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-API-key fallback documented in the README. It is also the backend whose extra no
    image installs -- `config.require_reranker_backend` refuses to boot in that case, and
    `test_scopes.py` pins that; here it only has to be reachable.
    """
    monkeypatch.setattr(get_settings(), "reranker_backend", "local")

    await rerank("why?", _documents(3))

    assert [name for name, _ in backends] == ["local"]


async def test_an_empty_candidate_list_never_reaches_a_backend(backends: list[tuple[str, int]]) -> None:
    """A retrieval that found nothing must not be billed for reranking nothing. This also keeps
    the local path from loading torch and a cross-encoder model to answer a question with no
    candidates -- seconds of CPU and hundreds of MB, to return `[]`.
    """
    assert await rerank("why?", []) == []
    assert backends == []


async def test_the_result_is_cut_to_rerank_top_n(
    backends: list[tuple[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cut is ours, not the provider's, and it has to stay: `top_n`/`top_k` is passed to the
    compressor too, but a backend that ignores or exceeds it would otherwise put every retrieved
    chunk into the prompt. That is silent -- the answer is still correct, the bill is not.
    """
    monkeypatch.setattr(get_settings(), "reranker_backend", "voyage")
    monkeypatch.setattr(get_settings(), "rerank_top_n", 2)

    result = await rerank("why?", _documents(6))

    assert len(result) == 2
    assert [document.metadata["chunk_id"] for document in result] == ["d-0", "d-1"]


async def test_an_explicit_top_n_overrides_the_setting(
    backends: list[tuple[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The parameter exists for an eval harness sweeping k. It must win over the setting, or the
    sweep silently measures one value repeatedly.
    """
    monkeypatch.setattr(get_settings(), "reranker_backend", "voyage")
    monkeypatch.setattr(get_settings(), "rerank_top_n", 5)

    assert len(await rerank("why?", _documents(6), top_n=1)) == 1


async def test_every_candidate_is_sent_to_the_backend_not_just_the_first_n(
    backends: list[tuple[str, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cut happens *after* reranking, and that ordering is the whole point of the stage.
    Cutting first would hand the model the top n by embedding similarity -- the ranking the
    reranker exists to correct -- and reranking would become an expensive no-op that still
    looked like it was working.
    """
    monkeypatch.setattr(get_settings(), "reranker_backend", "voyage")
    monkeypatch.setattr(get_settings(), "rerank_top_n", 2)

    await rerank("why?", _documents(9))

    assert backends == [("voyage", 9)]
