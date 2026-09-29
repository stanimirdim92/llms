"""Epic 2 Phase 2.4: corpus-level answers (`corpus_answer_service`) and whole-document scope.

Both ship behind flags that default off, so the committed eval baseline still describes `/ask`
as it shipped. What these pin is the part the eval can't see: which documents survive the
selection, that a drop or a cut is logged rather than silent, that nothing weak is synthesised
into an answer, and that each flag off leaves the old path in place.

No network: the retriever, reranker and model are fakes; nothing constructs a `ChatAnthropic`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from structlog.testing import capture_logs

from app.api.routers import ask as ask_router
from app.generation import answer_service as answer_module, corpus_answer_service as corpus_module
from app.generation.answer_service import WHOLE_DOCUMENT_CHAR_BUDGET, AnswerService
from app.generation.corpus_answer_service import (
    CHUNKS_PER_DOCUMENT,
    MAX_DOCUMENTS,
    SCORE_FLOOR,
    AggregateAnswerService,
    _select,
)
from app.generation.prompts import AGGREGATE_NO_DATA_ANSWER

if TYPE_CHECKING:
    import pytest
    from langchain_anthropic import ChatAnthropic

    from app.retrieval.retriever import Retriever

TENANT = "t" * 32


def _chunk(doc_id: str, score: float | None, text: str = "x") -> Document:
    metadata: dict[str, Any] = {"doc_id": doc_id, "chunk_id": f"{doc_id}-{text}"}
    if score is not None:
        metadata["relevance_score"] = score
    return Document(page_content=text, metadata=metadata)


class _FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def ainvoke(self, messages: list) -> AIMessage:
        self.calls.append(messages)
        return AIMessage(content="answer", response_metadata={"stop_reason": "end_turn"})


class _FakeRetriever:
    def __init__(self, *, retrieved: list[Document], whole: list[Document] | None = None) -> None:
        self.retrieved = retrieved
        self.whole = whole or []
        self.retrieve_calls: list[dict] = []
        self.whole_calls: list[tuple[str, str]] = []

    async def retrieve(self, _question: str, **kwargs: object) -> list[Document]:
        self.retrieve_calls.append(kwargs)
        return self.retrieved

    async def whole_document(self, doc_id: str, tenant_id: str) -> list[Document]:
        self.whole_calls.append((doc_id, tenant_id))
        return self.whole


async def _passthrough_rerank(_question: str, documents: list[Document], **_kwargs: object) -> list[Document]:
    return documents


# --- _select ---------------------------------------------------------------------------------


def test_select_groups_by_document_in_score_order_and_caps_chunks_per_document() -> None:
    reranked = [_chunk("a", 0.9, "1"), _chunk("b", 0.8, "1"), *(_chunk("a", 0.7, str(i)) for i in range(2, 6))]
    sources, dropped = _select(reranked)
    assert [s.metadata["doc_id"] for s in sources] == ["a"] * CHUNKS_PER_DOCUMENT + ["b"]
    assert dropped == 0


def test_select_skips_chunks_below_the_floor_but_keeps_unscored_ones() -> None:
    """Unscored means the reranker was down and `rerank` fell back: refusing then would make the
    reranker's outage an answer outage (root rule 9).
    """
    sources, _ = _select([_chunk("a", SCORE_FLOOR - 0.01), _chunk("b", None), _chunk("c", SCORE_FLOOR)])
    assert [s.metadata["doc_id"] for s in sources] == ["b", "c"]


def test_select_reports_how_many_relevant_documents_did_not_fit() -> None:
    reranked = [_chunk(f"d{i}", 0.9) for i in range(MAX_DOCUMENTS + 2)]
    sources, dropped = _select(reranked)
    assert len({s.metadata["doc_id"] for s in sources}) == MAX_DOCUMENTS
    assert dropped == 2


# --- AggregateAnswerService ------------------------------------------------------------------


def _aggregate_service(retriever: _FakeRetriever, llm: _FakeLLM) -> AggregateAnswerService:
    service = object.__new__(AggregateAnswerService)
    service._retriever = cast("Retriever", retriever)
    service._llm = cast("ChatAnthropic", llm)
    return service


async def test_nothing_above_the_floor_is_a_canned_answer_not_a_synthesis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus_module, "rerank", _passthrough_rerank)
    llm = _FakeLLM()
    service = _aggregate_service(_FakeRetriever(retrieved=[_chunk("a", 0.01), _chunk("b", 0.02)]), llm)

    with capture_logs() as logs:
        result = await service.answer("what themes?", TENANT)

    assert result.text == AGGREGATE_NO_DATA_ANSWER
    assert result.retrieved_chunks == []
    assert llm.calls == []
    assert any(entry["event"] == "aggregate.nothing_above_floor" for entry in logs)


async def test_documents_that_did_not_fit_are_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus_module, "rerank", _passthrough_rerank)
    retriever = _FakeRetriever(retrieved=[_chunk(f"d{i}", 0.9) for i in range(MAX_DOCUMENTS + 1)])
    service = _aggregate_service(retriever, _FakeLLM())

    with capture_logs() as logs:
        result = await service.answer("what themes?", TENANT)

    assert result.text == "answer"
    assert retriever.retrieve_calls == [{"tenant_id": TENANT, "top_k": corpus_module.CANDIDATE_CHUNKS}]
    dropped = [entry for entry in logs if entry["event"] == "aggregate.documents_dropped"]
    assert len(dropped) == 1
    assert dropped[0]["dropped"] == 1


# --- /ask's aggregate branch -----------------------------------------------------------------


async def _classify_aggregate(_question: str) -> str:
    return "aggregate"


async def test_aggregate_flag_off_refuses_without_touching_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    def _tripwire() -> object:
        raise AssertionError("the aggregate service ran with AGGREGATE_ANSWERING off")

    monkeypatch.setattr(ask_router, "classify_intent", _classify_aggregate)
    monkeypatch.setattr(ask_router, "get_settings", lambda: SimpleNamespace(aggregate_answering=False))
    monkeypatch.setattr(ask_router, "_aggregate_service", _tripwire)

    intent, response = await ask_router.answer_question("what themes?", TENANT)
    assert intent == "aggregate"
    assert response.answer == ask_router._AGGREGATE_NOT_SUPPORTED_ANSWER
    assert response.retrieved_chunks == []


async def test_aggregate_flag_on_answers_from_the_corpus_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus_module, "rerank", _passthrough_rerank)
    service = _aggregate_service(_FakeRetriever(retrieved=[_chunk("a", 0.9)]), _FakeLLM())
    monkeypatch.setattr(ask_router, "classify_intent", _classify_aggregate)
    monkeypatch.setattr(ask_router, "get_settings", lambda: SimpleNamespace(aggregate_answering=True))
    monkeypatch.setattr(ask_router, "_aggregate_service", lambda: service)

    _, response = await ask_router.answer_question("what themes?", TENANT)
    assert response.answer == "answer"
    assert [chunk.doc_id for chunk in response.retrieved_chunks] == ["a"]


# --- whole-document scope --------------------------------------------------------------------


def _answer_service(retriever: _FakeRetriever) -> AnswerService:
    service = object.__new__(AnswerService)
    service._retriever = cast("Retriever", retriever)
    service._llm = cast("ChatAnthropic", _FakeLLM())
    return service


def _settings(*, whole_document_scope: bool) -> SimpleNamespace:
    return SimpleNamespace(dynamic_prompt=False, whole_document_scope=whole_document_scope)


async def test_one_named_document_is_sent_whole_when_the_flag_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_rerank(*_args: object, **_kwargs: object) -> list[Document]:
        raise AssertionError("a whole-document answer was reranked down to top-n")

    monkeypatch.setattr(answer_module, "get_settings", lambda: _settings(whole_document_scope=True))
    monkeypatch.setattr(answer_module, "rerank", _no_rerank)
    whole = [_chunk("a", None, str(i)) for i in range(12)]
    retriever = _FakeRetriever(retrieved=[], whole=whole)

    result = await _answer_service(retriever).answer("summarise it", TENANT, doc_ids=["a"])

    assert retriever.whole_calls == [("a", TENANT)]
    assert retriever.retrieve_calls == []
    assert result.retrieved_chunks == whole


async def test_whole_document_scope_off_keeps_retrieve_and_rerank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(answer_module, "get_settings", lambda: _settings(whole_document_scope=False))
    monkeypatch.setattr(answer_module, "rerank", _passthrough_rerank)
    retriever = _FakeRetriever(retrieved=[_chunk("a", 0.9)], whole=[_chunk("a", None)])

    await _answer_service(retriever).answer("summarise it", TENANT, doc_ids=["a"])

    assert retriever.whole_calls == []
    assert len(retriever.retrieve_calls) == 1


async def test_two_named_documents_still_go_through_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(answer_module, "get_settings", lambda: _settings(whole_document_scope=True))
    monkeypatch.setattr(answer_module, "rerank", _passthrough_rerank)
    retriever = _FakeRetriever(retrieved=[_chunk("a", 0.9)])

    await _answer_service(retriever).answer("compare them", TENANT, doc_ids=["a", "b"])

    assert retriever.whole_calls == []


async def test_a_document_over_budget_is_cut_in_reading_order_and_the_cut_is_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(answer_module, "get_settings", lambda: _settings(whole_document_scope=True))
    piece = WHOLE_DOCUMENT_CHAR_BUDGET // 4
    whole = [_chunk("a", None, str(i) * piece) for i in range(6)]
    retriever = _FakeRetriever(retrieved=[], whole=whole)

    with capture_logs() as logs:
        result = await _answer_service(retriever).answer("summarise it", TENANT, doc_ids=["a"])

    assert result.retrieved_chunks == whole[:4]
    cut = [entry for entry in logs if entry["event"] == "answer_service.document_cut"]
    assert len(cut) == 1
    assert (cut[0]["kept_chunks"], cut[0]["total_chunks"]) == (4, 6)
