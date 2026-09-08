"""Classifies a question into one of four intents before `/ask` decides how to answer it --
Epic 2 Phase 2.0 (`docs/EPIC_2_PLAN.md`). A judgment call, so a model is right here per rule 5;
the routing it feeds stays plain `if`/`else` in `app/api/routers/ask.py`.

The observed defect this exists to fix: a user asked "list my documents" and got a confident
answer grounded in five retrieved chunks, four of which were figure-caption vision-model
refusals. Retrieval cannot answer a metadata question -- the embedding of "list my documents"
lands nearest whatever chunk happens to be semantically adjacent, regardless of how many
documents exist. Adding documents does not fix it; the question is not answerable from chunk
content at all, which is why this has to happen *before* retrieval rather than by improving it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Literal, cast

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import get_settings

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable

Intent = Literal["metadata", "factual", "aggregate", "out_of_scope"]

_SYSTEM_PROMPT = """Classify a question about a user's uploaded documents into exactly one \
intent:

- metadata: about the document collection itself, not what any document says -- "list my \
documents", "how many did I upload?", "what's the status of report.pdf?". Answerable from a \
document registry (filenames, status, chunk counts), never from document content.
- factual: a specific question whose answer sits in a handful of passages -- "what electrolyte \
did they use?", "summarise report.pdf". The default for an ordinary question about content.
- aggregate: asks about themes, patterns, or a comparison spanning many or all of the user's \
documents -- "what themes run through my uploads?", "compare every paper's methodology".
- out_of_scope: not answerable from anything a person could plausibly have uploaded here -- \
small talk, general knowledge, or a request unrelated to the user's own documents.

Respond with exactly one label."""

_MAX_ROUTER_TOKENS = 16
"""One label, via structured output. Named so the ceiling is visible: this classifier only pays
off against the retrieval it lets a metadata question skip (docs/EPIC_2_PLAN.md Phase 2.0) if it
stays sub-second and fractions of a cent -- a generous ceiling here would erode that."""


class _IntentLabel(BaseModel):
    intent: Intent = Field(description="Exactly one of metadata, factual, aggregate, out_of_scope.")


@lru_cache
def _classifier() -> Runnable:
    settings = get_settings()
    llm = ChatAnthropic(
        model=settings.intent_router_model,
        api_key=settings.anthropic_api_key,
        max_tokens=_MAX_ROUTER_TOKENS,
        thinking={"type": "disabled"},
    )
    return llm.with_structured_output(_IntentLabel)


async def classify_intent(question: str) -> Intent:
    result = await _classifier().ainvoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=question)])
    # `with_structured_output`'s return type is `dict | BaseModel` because a plain JSON-schema
    # dict is also a valid `schema` argument there; passing a `BaseModel` subclass (as above)
    # always yields an instance of it back, never a dict.
    return cast("_IntentLabel", result).intent
