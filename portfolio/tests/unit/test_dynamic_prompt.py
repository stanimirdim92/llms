"""Epic 2 Phase 2.5 #1, dynamic prompt assembly (`answer_service._messages`).

Two properties matter more than the guidance wording. Off must be the shipped prompt byte for byte,
because that's what the committed eval baseline measured. On, the system prompt must not vary with
what was retrieved, because a variable prefix silently defeats prompt caching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.documents import Document

from app.generation.answer_service import _messages
from app.generation.prompts import BASE_SYSTEM_PROMPT, FIGURE_GUIDANCE, SYSTEM_PROMPT, TABLE_GUIDANCE

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


def _doc(chunk_type: str) -> Document:
    return Document(page_content=f"a {chunk_type}", metadata={"chunk_type": chunk_type, "doc_id": "d1"})


def _blocks(message: BaseMessage) -> list[dict]:
    assert isinstance(message.content, list)
    return [block for block in message.content if isinstance(block, dict)]


def _texts(message: BaseMessage) -> list[str]:
    return [block["text"] for block in _blocks(message) if block.get("type") == "text"]


def test_off_is_the_shipped_prompt() -> None:
    system, human = _messages("q?", [_doc("table"), _doc("figure")], dynamic=False)
    assert system.content == SYSTEM_PROMPT
    assert _texts(human) == ["q?"]


def test_on_adds_guidance_only_for_the_kinds_retrieved() -> None:
    _, human = _messages("q?", [_doc("text"), _doc("table")], dynamic=True)
    assert _texts(human) == [TABLE_GUIDANCE, "q?"]

    _, human = _messages("q?", [_doc("figure"), _doc("table")], dynamic=True)
    assert _texts(human) == [f"{TABLE_GUIDANCE}\n\n{FIGURE_GUIDANCE}", "q?"]

    _, human = _messages("q?", [_doc("text")], dynamic=True)
    assert _texts(human) == ["q?"]


def test_on_keeps_the_system_prompt_identical_whatever_was_retrieved() -> None:
    """The cache-prefix trap `docs/EPIC_2_PLAN.md` names: variable content must come after the documents."""
    systems = {
        _messages("q?", docs, dynamic=True)[0].content
        for docs in ([_doc("text")], [_doc("table")], [_doc("figure"), _doc("table")])
    }
    assert systems == {BASE_SYSTEM_PROMPT}


def test_guidance_comes_after_the_documents_and_before_the_question() -> None:
    _, human = _messages("q?", [_doc("table")], dynamic=True)
    kinds = [block["type"] for block in _blocks(human)]
    assert kinds == ["document", "text", "text"]
