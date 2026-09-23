"""Qwen site 1: N query candidates per adapter from the line vocabulary (the FLASH model, qwen.client).

Query strings are validated strictly (query_text.clean_query): a leaked chat-template
token fails validation, is retried, and then counted in GenerationMeter.output_violations
— that rate decides whether to move from NativeOutput to PromptedOutput later.

Output = the FLASH output mode over a Pydantic model (client.flash_output); the field name `queries` is also spelled
out in the instructions (packet decision 10). Validation retried up to OUTPUT_RETRIES;
if it still fails — or the request fails — the adapter runs on code-built fallback
queries (the line's concept names), flagged in QueryResult.fallback (decision 8).
The candidates are then scored by Jev (jev.query_selection); Qwen never picks sources.
"""

from typing import Annotated, Final

from pydantic import AfterValidator, BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.usage import RunUsage

from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import AdapterKind, QueryCandidate, Question
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.query_text import clean_query

from .client import GenerationMeter, flash_output

OUTPUT_RETRIES: Final = 2
"""Validation retries after the first attempt (pydantic-ai retries={'output': N})."""


def _validate_query(text: str) -> str:
    cleaned = clean_query(text)
    if cleaned is None:
        raise ValueError(f"not a searchable query: {text!r}")
    return cleaned


type SearchQuery = Annotated[str, AfterValidator(_validate_query)]


class QueryList(BaseModel):
    """Search queries for one source adapter. Every string must survive clean_query, so a
    leaked chat-template token fails validation and is retried."""

    queries: list[SearchQuery] = Field(min_length=1)


class QueryResult(Value):
    candidates: tuple[QueryCandidate, ...]
    fallback: bool
    """True when the candidates were built by code, not generated."""
    failure: str | None


def instructions(adapter: AdapterKind, n: int) -> str:
    return (
        f"You write search queries for the `{adapter}` source. Return JSON with one field, "
        f"`queries`: a list of {n} short queries (2-6 words each, English) that would find "
        "recent work bearing on the research question in the user message. Use the line's "
        "vocabulary where it fits the question; do not add commentary."
    )


def user_prompt(ctx: LineContext, question: Question) -> str:
    vocab = "\n".join(f"- {term}" for term in ctx.vocabulary)
    parts = [f"Research line: {ctx.line.name}", f"Question: {question.title}"]
    if question.brief:
        parts.append(f"Background: {question.brief}")
    if question.negative_topics:
        parts.append("Not this: " + "; ".join(question.negative_topics))
    return "\n".join(parts) + f"\nVocabulary:\n{vocab}"


def _candidates(
    ctx: LineContext, adapter: AdapterKind, texts: list[str], n: int
) -> tuple[QueryCandidate, ...]:
    cleaned = [c for t in texts if (c := clean_query(t)) is not None]
    unique = list(dict.fromkeys(cleaned))[:n]
    return tuple(QueryCandidate.new(line=ctx.line.id, adapter=adapter, text=t) for t in unique)


def fallback(
    ctx: LineContext, adapter: AdapterKind, question: Question, n: int
) -> tuple[QueryCandidate, ...]:
    """Code-built queries: the question's own words first, then the line vocabulary."""
    words = [question.title, *question.method_constraints, *ctx.vocabulary]
    return _candidates(ctx, adapter, words, n)


async def query_candidates(
    model: OpenAIChatModel,
    ctx: LineContext,
    adapter: AdapterKind,
    question: Question,
    *,
    n: int,
    meter: GenerationMeter,
) -> QueryResult:
    agent = Agent(
        model,
        output_type=flash_output(QueryList),
        instructions=instructions(adapter, n),
        retries={"output": OUTPUT_RETRIES},
    )
    usage = RunUsage()  # filled as the run goes, so exhausted retries are metered too
    try:
        result = await agent.run(user_prompt(ctx, question), usage=usage)
    except AgentRunError as e:
        if isinstance(e, UnexpectedModelBehavior):
            meter.output_violations += 1  # the model kept returning unusable strings
        return QueryResult(
            candidates=fallback(ctx, adapter, question, n),
            fallback=True,
            failure=type(e).__name__,
        )
    finally:
        meter.add(usage)
    candidates = _candidates(ctx, adapter, result.output.queries, n)
    if not candidates:
        return QueryResult(
            candidates=fallback(ctx, adapter, question, n), fallback=True, failure="empty"
        )
    return QueryResult(candidates=candidates, fallback=False, failure=None)
