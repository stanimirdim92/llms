"""Epic 2 Phase 2.5 #2 and #3: query expansion and decomposition.

Whether a rewrite *helps* is the eval's question (recall@5 with the flag on versus the baseline).
These pin what the eval can't: both flags off is one search and one rerank of the question, as
shipped; each part is reranked against itself, never against a paraphrase; duplicates across
searches reach the model once; and a rewriter outage degrades to the plain question.

No network: the rewriter, retriever, reranker and model are fakes.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import anthropic
import httpx
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.generation import answer_service as answer_module, query_rewrite
from app.generation.answer_service import AnswerService
from app.generation.query_rewrite import MAX_REWRITES, _clean, _Rewrites, decompose_query, expand_query

if TYPE_CHECKING:
    import pytest
    from langchain_anthropic import ChatAnthropic

    from app.retrieval.retriever import Retriever

TENANT = "t" * 32


def _chunk(chunk_id: str) -> Document:
    return Document(page_content=chunk_id, metadata={"chunk_id": chunk_id, "doc_id": "d"})


class _FakeLLM:
    async def ainvoke(self, _messages: list) -> AIMessage:
        return AIMessage(content="answer", response_metadata={"stop_reason": "end_turn"})


class _FakeRetriever:
    """Returns a chunk named after the query plus one chunk every query finds."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def retrieve(self, query: str, **_kwargs: object) -> list[Document]:
        self.queries.append(query)
        return [_chunk(f"hit:{query}"), _chunk("shared")]


def _service(retriever: _FakeRetriever) -> AnswerService:
    service = object.__new__(AnswerService)
    service._retriever = cast("Retriever", retriever)
    service._llm = cast("ChatAnthropic", _FakeLLM())
    return service


def _flags(monkeypatch: pytest.MonkeyPatch, *, expansion: bool, decomposition: bool) -> list[str]:
    """Sets the flags and records which question each rerank ranked against."""
    monkeypatch.setattr(
        answer_module,
        "get_settings",
        lambda: SimpleNamespace(
            dynamic_prompt=False,
            whole_document_scope=False,
            query_expansion=expansion,
            query_decomposition=decomposition,
        ),
    )
    ranked_against: list[str] = []

    async def _rerank(question: str, documents: list[Document], **_kwargs: object) -> list[Document]:
        ranked_against.append(question)
        return documents

    monkeypatch.setattr(answer_module, "rerank", _rerank)
    return ranked_against


def _no_rewriter_call(*_args: object) -> object:
    raise AssertionError("the rewriter ran with its flag off")


async def test_both_flags_off_is_one_search_and_one_rerank_of_the_question(monkeypatch: pytest.MonkeyPatch) -> None:
    ranked_against = _flags(monkeypatch, expansion=False, decomposition=False)
    monkeypatch.setattr(answer_module, "expand_query", _no_rewriter_call)
    monkeypatch.setattr(answer_module, "decompose_query", _no_rewriter_call)
    retriever = _FakeRetriever()

    await _service(retriever).answer("q?", TENANT)

    assert retriever.queries == ["q?"]
    assert ranked_against == ["q?"]


async def test_expansion_searches_every_paraphrase_but_reranks_against_the_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranked_against = _flags(monkeypatch, expansion=True, decomposition=False)

    async def _expand(_question: str) -> list[str]:
        return ["p1", "p2"]

    monkeypatch.setattr(answer_module, "expand_query", _expand)
    retriever = _FakeRetriever()

    result = await _service(retriever).answer("q?", TENANT)

    assert retriever.queries == ["q?", "p1", "p2"]
    assert ranked_against == ["q?"]
    ids = [chunk.metadata["chunk_id"] for chunk in result.retrieved_chunks]
    assert ids == ["hit:q?", "shared", "hit:p1", "hit:p2"]


async def test_decomposition_reranks_each_part_against_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    ranked_against = _flags(monkeypatch, expansion=False, decomposition=True)

    async def _decompose(_question: str) -> list[str]:
        return ["about X?", "about Y?"]

    monkeypatch.setattr(answer_module, "decompose_query", _decompose)
    retriever = _FakeRetriever()

    result = await _service(retriever).answer("compare X and Y", TENANT)

    assert sorted(ranked_against) == ["about X?", "about Y?"]
    ids = [chunk.metadata["chunk_id"] for chunk in result.retrieved_chunks]
    assert ids == ["hit:about X?", "hit:about Y?", "shared"], "each part's best chunk must lead"


def test_clean_drops_the_original_blanks_and_duplicates_and_caps() -> None:
    queries = ["  Q?  ", "", "a", "A", "b", "c", "d"]
    assert _clean(queries, "q?") == ["a", "b", "c"][:MAX_REWRITES]


class _BrokenRewriter:
    async def ainvoke(self, _messages: list) -> object:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.APIConnectionError(request=request)


class _FixedRewriter:
    def __init__(self, queries: list[str]) -> None:
        self._queries = queries

    async def ainvoke(self, _messages: list) -> _Rewrites:
        return _Rewrites(queries=self._queries)


async def test_a_rewriter_outage_falls_back_to_the_question(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail open (root rule 9): the rewrite is an optimisation, so its outage is not the answer's."""
    monkeypatch.setattr(query_rewrite, "_rewriter", _BrokenRewriter)
    assert await expand_query("q?") == []
    assert await decompose_query("q?") == ["q?"]


async def test_a_single_part_decomposition_is_the_question_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(query_rewrite, "_rewriter", lambda: _FixedRewriter(["What is X, restated?"]))
    assert await decompose_query("What is X?") == ["What is X?"]

    monkeypatch.setattr(query_rewrite, "_rewriter", lambda: _FixedRewriter(["About X?", "About Y?"]))
    assert await decompose_query("compare X and Y") == ["About X?", "About Y?"]
