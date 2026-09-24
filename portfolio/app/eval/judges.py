"""Answer-quality judges: an LLM grades what the retrieval metrics can't.

LangSmith's own guidance is to define LLM-as-judge evaluators locally and pass them to
`evaluate()`; uploading a judge through its CLI isn't supported. So the judge is code here, run
on Claude, and LangSmith stores and shows the scores. Chosen over `ragas` on 2026-09-24: `ragas`
0.4.3 downgrades `fsspec`, `jiter` and `rich` and adds `nest-asyncio`, a monkey-patch.

Two judges, each with one question to answer:
- **correctness**: does the answer say what the accepted answer says? For a pair the corpus can't
  answer, the accepted answer is a refusal, so a confident answer there scores 0.
- **groundedness**: is every claim supported by the chunks the answer was built from? This is
  the check that catches a fluent answer from the wrong material (root `CLAUDE.md` rule 11).

The judge is a different model from the one answering (Opus grades Sonnet by default), so it
isn't grading its own writing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, cast

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field

from app.config import get_settings

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable

    from app.eval.golden import GoldenPair
    from app.eval.target import TargetOutput


class Verdict(BaseModel):
    reasoning: str = Field(description="One or two sentences: what matched or what was wrong.")
    passed: bool = Field(description="True only if the answer meets the criterion in full.")


_CORRECTNESS_PROMPT = """You grade a question-answering system against an accepted answer.

Question: {question}

Accepted answer: {reference}

System answer: {answer}

Pass only if the system answer states the same facts as the accepted answer. Wording may
differ; numbers, names and conclusions may not. If the accepted answer is a refusal, pass only
if the system also declines to answer rather than guessing. Extra correct detail is fine;
anything contradicting the accepted answer fails."""

_GROUNDEDNESS_PROMPT = """You check whether an answer is supported by its sources.

Question: {question}

Sources the answer was written from:
{sources}

Answer: {answer}

Pass only if every factual claim in the answer is stated in, or directly follows from, the
sources. A claim that is plausible but absent from the sources fails. An answer that correctly
says the sources don't contain the answer passes."""


@lru_cache
def _judge() -> Runnable:
    # Structured outputs (`json_schema`), not a forced tool call: thinking stays on, which the
    # default Opus model wants, and forced `tool_choice` isn't allowed alongside thinking.
    llm = ChatAnthropic(
        model=get_settings().eval_judge_model,
        api_key=get_settings().anthropic_api_key,
        max_tokens=4096,
    )
    return llm.with_structured_output(Verdict, method="json_schema")


async def _ask(prompt: str) -> Verdict:
    return cast("Verdict", await _judge().ainvoke(prompt))


async def judge_correctness(pair: GoldenPair, output: TargetOutput) -> Verdict | None:
    """Factual pairs only. The other intents are refusals or registry reads that routing
    accuracy already covers.
    """
    if pair.intent != "factual":
        return None
    if output.error_code is not None:
        # An error is a wrong answer, not a missing one -- skipping it would let an outage
        # raise the correctness score.
        return Verdict(reasoning=f"/ask answered {output.error_code}", passed=False)
    return await _ask(_CORRECTNESS_PROMPT.format(question=pair.question, reference=pair.answer, answer=output.answer))


async def judge_groundedness(pair: GoldenPair, output: TargetOutput) -> Verdict | None:
    if pair.intent != "factual" or output.error_code is not None or not output.retrieved_texts:
        return None
    sources = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(output.retrieved_texts, start=1))
    return await _ask(_GROUNDEDNESS_PROMPT.format(question=pair.question, sources=sources, answer=output.answer))


async def judge_scores(pair: GoldenPair, output: TargetOutput) -> dict[str, float | None]:
    """Same shape as `metrics.score`, so the gate aggregates judges and metrics alike."""
    correct = await judge_correctness(pair, output)
    grounded = await judge_groundedness(pair, output)
    return {
        "correctness": None if correct is None else float(correct.passed),
        "groundedness": None if grounded is None else float(grounded.passed),
    }
