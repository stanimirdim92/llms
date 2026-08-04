"""Turning Anthropic's response into an `Answer`: text, citations, and truncation.

Untested until now, and this is the layer that decides what a caller is *told* about an answer.
Every failure here is silent by construction -- a dropped citation still returns fluent prose, a
mis-indexed one attributes a real quote to the wrong document, and a truncated answer looks
exactly like a complete one. None of it raises.

No network. The Anthropic response is constructed as an `AIMessage`, which is what
`ChatAnthropic.ainvoke` returns, so the shapes here are the real ones: `.content` is a string
*or* a list of blocks, and citations arrive nested inside text blocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.generation import answer_service
from app.generation.answer_service import _TRUNCATED_STOP_REASON, AnthropicContent, _extract_citations, _extract_text

if TYPE_CHECKING:
    from langchain_anthropic import ChatAnthropic

    from app.retrieval.retriever import Retriever


TENANT = "a" * 32
"""Any tenant: these assert on how an Anthropic response is parsed, not on scoping."""


def _document(doc_id: str, chunk_id: str = "", page_no: int | None = None) -> Document:
    metadata: dict = {"doc_id": doc_id}
    if chunk_id:
        metadata["chunk_id"] = chunk_id
    if page_no is not None:
        metadata["page_no"] = page_no
    return Document(page_content="...", metadata=metadata)


def _cited_block(text: str, *, document_index: int, cited_text: str) -> dict:
    return {
        "type": "text",
        "text": text,
        "citations": [
            {
                "type": "char_location",
                "cited_text": cited_text,
                "document_index": document_index,
                "document_title": "whatever",
            }
        ],
    }


# ---------------------------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------------------------


def test_a_plain_string_response_is_the_answer() -> None:
    """Anthropic returns a bare string when no citations are involved, and the union type is not
    hypothetical -- `thinking` disabled plus zero documents produces exactly this.
    """
    assert _extract_text("just text") == "just text"


def test_text_blocks_are_joined_in_order() -> None:
    """Concatenated, not joined with a separator: the model emits one block per cited span, so
    inserting anything between them would put spaces or newlines mid-sentence.
    """
    blocks: AnthropicContent = [{"type": "text", "text": "LiFePO4 "}, {"type": "text", "text": "is stable."}]

    assert _extract_text(blocks) == "LiFePO4 is stable."


def test_non_text_blocks_contribute_nothing_to_the_answer() -> None:
    """A `thinking` or `tool_use` block reaching the user-visible answer would leak reasoning
    into the response body. Filtered on `type`, so anything new Anthropic adds is excluded by
    default rather than included by default.
    """
    blocks: AnthropicContent = [
        {"type": "thinking", "thinking": "the user wants..."},
        {"type": "text", "text": "The answer."},
    ]

    assert _extract_text(blocks) == "The answer."


def test_a_block_that_is_not_a_dict_is_skipped_rather_than_crashing() -> None:
    """`AnthropicContent` allows `list[str | dict]`. A bare string in the list would raise
    `AttributeError: 'str' object has no attribute 'get'` and turn a good answer into a 500.
    """
    blocks: AnthropicContent = ["stray", {"type": "text", "text": "kept"}]

    assert _extract_text(blocks) == "kept"


# ---------------------------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------------------------


def test_a_citation_resolves_to_the_document_it_indexes() -> None:
    """`document_index` is positional into the list passed to the model, so this mapping is the
    whole correctness of a citation. Off by one and every quote is attributed to its neighbour --
    a wrong source rendered with the right quote, which is worse than no citation at all.
    """
    documents = [
        _document("doc-a", chunk_id="doc-a-text-0000"),
        _document("doc-b", chunk_id="doc-b-text-0000", page_no=7),
    ]
    blocks: AnthropicContent = [_cited_block("...", document_index=1, cited_text="the quoted span")]

    citations = _extract_citations(blocks, documents)

    assert len(citations) == 1
    assert citations[0].doc_id == "doc-b"
    assert citations[0].chunk_id == "doc-b-text-0000"
    assert citations[0].page_no == 7
    assert citations[0].quoted_text == "the quoted span"


def test_an_out_of_range_document_index_is_dropped_not_raised() -> None:
    """The guard exists because the failure without it is an `IndexError` inside a request that
    had already produced a good answer -- the caller gets a 500 and loses the text as well as
    the citation. Dropping one citation degrades; raising destroys.
    """
    blocks: AnthropicContent = [_cited_block("...", document_index=5, cited_text="q")]

    assert _extract_citations(blocks, [_document("doc-a")]) == []


def test_a_negative_document_index_does_not_wrap_around_to_the_last_document() -> None:
    """Python's negative indexing makes this the one out-of-range value that *succeeds* and
    lies: `documents[-1]` is a real document, so the citation renders normally while pointing
    at whichever chunk happened to be reranked last.
    """
    blocks: AnthropicContent = [_cited_block("...", document_index=-1, cited_text="q")]

    citations = _extract_citations(blocks, [_document("doc-a"), _document("doc-b")])

    assert citations == [], "a negative index must be refused, not resolved to the tail"


def test_a_citation_with_no_index_is_dropped() -> None:
    blocks: AnthropicContent = [{"type": "text", "text": "...", "citations": [{"cited_text": "q"}]}]

    assert _extract_citations(blocks, [_document("doc-a")]) == []


def test_a_chunk_without_a_chunk_id_falls_back_to_its_doc_id() -> None:
    """Chunks ingested before `chunk_id` was stored in the payload have none. An empty string
    there would render as a citation to nothing; the doc_id at least stays traceable.
    """
    blocks: AnthropicContent = [_cited_block("...", document_index=0, cited_text="q")]

    citations = _extract_citations(blocks, [_document("doc-a")])

    assert citations[0].chunk_id == "doc-a"


def test_a_string_response_yields_no_citations() -> None:
    """Not an error -- it is what a question answered from no documents returns. The caller
    distinguishes "uncited" from "failed" by the text being present.
    """
    assert _extract_citations("plain text answer", [_document("doc-a")]) == []


def test_several_citations_across_several_blocks_are_all_collected() -> None:
    """One block per cited span, so a multi-source answer arrives as several blocks. Collecting
    only the first block's citations would quietly under-report the sources of exactly the
    answers that used the most of them.
    """
    documents = [_document("doc-a"), _document("doc-b")]
    blocks: AnthropicContent = [
        _cited_block("first claim ", document_index=0, cited_text="from a"),
        _cited_block("second claim.", document_index=1, cited_text="from b"),
    ]

    assert [citation.doc_id for citation in _extract_citations(blocks, documents)] == ["doc-a", "doc-b"]


# ---------------------------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------------------------


def _response(stop_reason: str | None, *, output_tokens: int = 100) -> AIMessage:
    return AIMessage(
        content=[{"type": "text", "text": "an answer"}],
        response_metadata={"stop_reason": stop_reason, "model": "claude-sonnet-5"},
        usage_metadata={"input_tokens": 900, "output_tokens": output_tokens, "total_tokens": 900 + output_tokens},
    )


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> answer_service.AnswerService:
    """An `AnswerService` whose retriever, reranker and model are all stubbed.

    Constructed through `__new__` rather than `__init__`: the constructor builds a
    `ChatAnthropic`, which requires an API key, and this module must run in CI with none.
    """
    instance = answer_service.AnswerService.__new__(answer_service.AnswerService)
    monkeypatch.setattr(answer_service, "rerank", _passthrough_rerank)
    return instance


async def _passthrough_rerank(_query: str, documents: list[Document]) -> list[Document]:
    return documents


class _StubRetriever:
    async def retrieve(self, _question: str, **_kwargs: object) -> list[Document]:
        return [Document(page_content="body", metadata={"doc_id": "doc-a"})]


class _StubLLM:
    def __init__(self, response: AIMessage) -> None:
        self._response = response

    async def ainvoke(self, _messages: object) -> AIMessage:
        return self._response


def _wire(service: answer_service.AnswerService, response: AIMessage) -> None:
    """Replace the two collaborators in place.

    `cast` rather than a protocol: these are the seams a real `AnswerService` builds in
    `__init__`, and giving them structural types in production code purely so a test can
    substitute them would be a design change made for the test's convenience.
    """
    service._retriever = cast("Retriever", _StubRetriever())
    service._llm = cast("ChatAnthropic", _StubLLM(response))


async def test_hitting_the_token_ceiling_is_reported_as_truncated(service: answer_service.AnswerService) -> None:
    """The finding this exists for. A `max_tokens` stop was indistinguishable from a finished
    answer: the text came back cut off mid-sentence with a short citation list, and every caller
    -- the API response, the Streamlit page, a future eval harness -- presented it as complete.
    """
    _wire(service, _response(_TRUNCATED_STOP_REASON))

    answer = await service.answer("why?", tenant_id=TENANT)

    assert answer.truncated is True


async def test_a_normal_stop_is_not_reported_as_truncated(service: answer_service.AnswerService) -> None:
    """The other half, and the one that matters for noise: flagging every answer would train
    the reader to ignore the warning, which is the same as not having it.
    """
    _wire(service, _response("end_turn"))

    answer = await service.answer("why?", tenant_id=TENANT)

    assert answer.truncated is False


async def test_a_missing_stop_reason_is_not_reported_as_truncated(service: answer_service.AnswerService) -> None:
    """`response_metadata` is provider-shaped and may not carry it at all. Absent must mean
    "no evidence of truncation", not truncated -- see rule 8: absent data reads as the
    pre-existing behaviour.
    """
    _wire(service, AIMessage(content="text only", response_metadata={}))

    answer = await service.answer("why?", tenant_id=TENANT)

    assert answer.truncated is False


async def test_an_answer_without_usage_metadata_still_returns(service: answer_service.AnswerService) -> None:
    """`usage_metadata` is None on a cached or non-Anthropic response. Indexing it would make
    the answer fail because its *cost* could not be reported, which is the wrong trade.
    """
    _wire(service, AIMessage(content="text only", response_metadata={"stop_reason": "end_turn"}))

    answer = await service.answer("why?", tenant_id=TENANT)

    assert answer.text == "text only"
