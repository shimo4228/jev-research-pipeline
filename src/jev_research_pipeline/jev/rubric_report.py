"""rubric_report — per report: readability, coherence, unsupported statements.

Subjects: (Report,). A failing decision drives the rendering ladder (qwen.prose):
prose → one rewrite → template. The state holds the prose and the accepted claims it
may rest on, so "unsupported" means "not backed by any of `claims`".
"""

from enum import IntEnum
from typing import Final

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue
from pydantic_ai import UseEnumMemberDocstrings

from jev_research_pipeline.model import Decision, Threshold
from jev_research_pipeline.model.nodes import Probability

from .context import LineContext, line_state
from .core import Ask, JevClient, JevFailure, Judged, decide, position, threshold


class Readability(UseEnumMemberDocstrings, IntEnum):
    hard = 0
    """Sentences are broken, run on, or mix languages mid-sentence."""
    effortful = 1
    """Readable, but the reader has to re-read to get the point."""
    clear = 2
    """Each paragraph makes its point on the first read."""


class Coherence(UseEnumMemberDocstrings, IntEnum):
    list_of_items = 0
    """Disconnected paragraphs with no thread between them."""
    loose = 1
    """A loose sequence; connections are implied but not stated."""
    report = 2
    """The paragraphs build on each other toward a point about `line`."""


class Answers(BaseModel):
    """Judge the day's prose for one research line."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    readability: Readability = Field(
        description="How easily can a Japanese-reading practitioner follow `prose`?"
    )
    coherence: Coherence = Field(
        description="How well do the paragraphs of `prose` hang together as one report on `line`?"
    )
    unsupported_statement: Probability = Field(
        description="Does `prose` state a fact that none of `claims` supports? No if every "
        "factual sentence traces to one of them."
    )


ASK: Final = Ask(
    function="rubric_report",
    version="v1",
    output=Answers,
    instructions="You judge generated prose for a research pipeline.",
)

THRESHOLDS: Final = (
    Threshold(name="readability", value=0.5),
    Threshold(name="coherence", value=0.5),
    Threshold(name="unsupported_statement", value=0.5),
)


def state(ctx: LineContext, prose: str, claims: list[str]) -> dict[str, JsonValue]:
    return {"line": line_state(ctx), "prose": prose, "claims": list(claims)}


async def judge(
    jev: JevClient, report_id: str, report_state: dict[str, JsonValue], *, now: AwareDatetime
) -> Judged[Answers] | JevFailure:
    return await jev.judge(ASK, (report_id,), report_state, now=now)


def rule(judged: Judged[Answers]) -> tuple[bool, float]:
    readability = position(judged, "readability")
    coherence = position(judged, "coherence")
    unsupported = judged.output.unsupported_statement
    passed = (
        readability >= threshold(THRESHOLDS, "readability")
        and coherence >= threshold(THRESHOLDS, "coherence")
        and unsupported < threshold(THRESHOLDS, "unsupported_statement")
    )
    return passed, min(readability, coherence, 1.0 - unsupported)


def decision(result: Judged[Answers] | JevFailure) -> Decision:
    return decide(result, ask=ASK, thresholds=THRESHOLDS, rule=rule)
