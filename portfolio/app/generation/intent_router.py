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
from pydantic import BaseModel, Field, ValidationError

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

_MAX_ROUTER_TOKENS = 128
"""Structured output is a **tool call**, so this has to fit `{"intent": "..."}` as tool
arguments, not just the word `factual`.

It was 16, on the reasoning that this classifier only pays off if it stays sub-second and
fractions of a cent, so a generous ceiling would erode that. The reasoning was wrong twice
over. `max_tokens` is a *ceiling*, not a charge -- the completion here is ~25 tokens whatever
this says, so raising it costs nothing -- and 16 was below what the mechanism needs, which made
**every `/ask` call a 500**: generation stopped mid-tool-call, the arguments arrived as `{}`, and
`_IntentLabel` failed validation with `intent: Field required`. The unit suite could not see it,
because a test that reaches `ask()` stubs `classify_intent` (see `CLAUDE.md` § Intent routing) --
so it was found by calling the running API, not by the gate.

Measured 2026-09-17 against `claude-haiku-4-5-20251001`, three questions each: 16, 24 and 32 all
fail identically; 64 and 128 both succeed in 0.55-0.68 s. 128 rather than the measured floor of
64, because a ceiling sitting exactly on the floor breaks on the first slightly longer schema.
LangChain does say so when it happens -- "Output parser received a `max_tokens` stop reason" --
but it says it as a warning beside a `ValidationError` traceback, which reads as a schema bug.
"""


class IntentUnavailableError(RuntimeError):
    """The classifier did not return a usable label, so no intent is known.

    There is deliberately **no fallback to `factual`**. That is the tempting degradation and it
    is the exact defect Phase 2.0 exists to fix: a metadata or out-of-scope question routed into
    retrieval gets a confident answer grounded in whatever chunk happened to be nearest in
    embedding space (`CLAUDE.md` § Intent routing). Rule 9's "fail open" applies to guardrails
    whose outage must not become the service's outage; this one decides *what the system does at
    all*, so failing open means answering from the wrong material -- rule 11's failure, which is
    worse than a 503.

    Raised rather than swallowed because the alternative was observed: a truncated tool call
    surfaced as `ValidationError: 1 validation error for _IntentLabel`, reaching the client as an
    opaque 500 and reading as a schema bug rather than a ceiling that was too low.
    """


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
    messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=question)]
    try:
        result = await _classifier().ainvoke(messages)
    except ValidationError as exc:
        # What a truncated or empty tool call looks like from here: the parser builds
        # `_IntentLabel(**{})` and pydantic reports `intent: Field required`. Labelled rather
        # than propagated, so the caller can answer 503 instead of the generic 500 this produced
        # on every single `/ask` call while `_MAX_ROUTER_TOKENS` was 16.
        msg = f"the intent classifier returned no usable label ({exc.error_count()} validation error(s))"
        raise IntentUnavailableError(msg) from exc
    # `with_structured_output`'s return type is `dict | BaseModel` because a plain JSON-schema
    # dict is also a valid `schema` argument there; passing a `BaseModel` subclass (as above)
    # always yields an instance of it back, never a dict.
    return cast("_IntentLabel", result).intent
