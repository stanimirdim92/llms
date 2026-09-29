"""Query expansion and decomposition (Epic 2 Phase 2.5 #2 and #3), behind `QUERY_EXPANSION` and
`QUERY_DECOMPOSITION`. Rewriting a question is a judgment call, so a model does it (rule 5); what
is done with the rewrites -- retrieve each, union, rerank -- is plain code in `answer_service`.

- **Expansion** is for vocabulary mismatch, which is constant in scientific text: "does NMC
  degrade?" and "capacity fade in LiNi0.8Mn0.1Co0.1O2" share no words. Paraphrases in the
  corpus's register are searched alongside the original, never instead of it.
- **Decomposition** is for a compound question: "compare X and Y" embeds to a vector between
  the two that matches neither. Each part is retrieved on its own. Only `factual` questions reach
  it, because only they reach `AnswerService` -- that is the intent-classifier gate the plan asks
  for, so a metadata or out-of-scope question never pays for it.

Both fail open. A rewrite is an optimisation on top of a path that already works on the original
question, so a rewriter outage degrades to exactly that path, loudly (root rule 9), rather than
failing the answer.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, cast

import anthropic
import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable

log = structlog.get_logger(__name__)

MAX_REWRITES = 3
"""Per question, for both. Each rewrite is one more embedding and one more vector search, so this
is the cap on how much wider retrieval gets."""

_MAX_REWRITE_TOKENS = 512
"""Structured output is a tool call carrying a list of strings, so this has to hold three
sentences as tool arguments. `intent_router._MAX_ROUTER_TOKENS` is the record of what a ceiling
too low for the tool call does: every call fails validation."""

_EXPANSION_PROMPT = f"""You help search a collection of scientific papers. Rewrite the user's \
question as up to {MAX_REWRITES} alternative search queries that a passage answering it might \
use: the technical terms, synonyms, abbreviations spelled out (or abbreviated), and phrasing a \
paper would use. Each must ask for the same thing as the original. Do not answer the question, \
and do not add facts it doesn't state."""

_DECOMPOSITION_PROMPT = f"""You help search a collection of scientific papers. If the user's \
question asks about two or more separate things -- a comparison, or several distinct facts -- \
split it into up to {MAX_REWRITES} self-contained questions, one per thing, each answerable on \
its own. If it asks about one thing, return it unchanged as the only item. Do not answer it."""


class _Rewrites(BaseModel):
    queries: list[str] = Field(description="The rewritten queries, one per item.")


@lru_cache
def _rewriter() -> Runnable:
    settings = get_settings()
    llm = ChatAnthropic(
        model=settings.intent_router_model,
        api_key=settings.anthropic_api_key,
        max_tokens=_MAX_REWRITE_TOKENS,
        thinking={"type": "disabled"},
    )
    return llm.with_structured_output(_Rewrites)


def _clean(queries: list[str], question: str) -> list[str]:
    """Stripped, deduplicated, capped, and without the original question."""
    seen = {question.strip().casefold()}
    kept: list[str] = []
    for query in queries:
        text = query.strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            kept.append(text)
    return kept[:MAX_REWRITES]


async def _rewrite(prompt: str, question: str, kind: str) -> list[str] | None:
    """None when the rewriter produced nothing usable; the caller then uses the question alone."""
    try:
        result = await _rewriter().ainvoke([SystemMessage(content=prompt), HumanMessage(content=question)])
    except (ValidationError, anthropic.APIError) as exc:
        log.warning("query_rewrite.unavailable", kind=kind, error=type(exc).__name__)
        return None
    return cast("_Rewrites", result).queries


async def expand_query(question: str) -> list[str]:
    """Alternative phrasings to search alongside `question`; never includes `question` itself."""
    queries = await _rewrite(_EXPANSION_PROMPT, question, "expansion")
    return [] if queries is None else _clean(queries, question)


async def decompose_query(question: str) -> list[str]:
    """The questions to retrieve for: the parts of a compound question, else `[question]`."""
    queries = await _rewrite(_DECOMPOSITION_PROMPT, question, "decomposition")
    if queries is None:
        return [question]
    # Cleaned without dropping the original: a one-part question comes back as itself, and that
    # is the answer "don't split", not a duplicate.
    parts = _clean(queries, "")
    return parts if len(parts) > 1 else [question]
