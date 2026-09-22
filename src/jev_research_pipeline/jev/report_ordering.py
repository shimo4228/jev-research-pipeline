"""report_ordering — Score importance per accepted claim; code sorts the report by it.

Subjects: (Claim,). Every judged claim is accepted (ordering never drops a claim);
order() puts judged claims by descending importance and unjudged ones last.
"""

from enum import IntEnum
from typing import Final

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue
from pydantic_ai import UseEnumMemberDocstrings

from jev_research_pipeline.model import Claim, Decision

from .context import LineContext, line_state
from .core import Ask, JevClient, JevFailure, Judged, decide, position


class Importance(UseEnumMemberDocstrings, IntEnum):
    known = 0
    """It restates something people working on `line.vocabulary` already take for granted."""
    minor = 1
    """A small detail or an incremental result on an existing method."""
    notable = 2
    """A new result or method a practitioner of this line would likely read in full."""
    shift = 3
    """It changes how a core term in `line.vocabulary` should be understood or practiced."""


class Answers(BaseModel):
    """Place one claim on a ladder of how much it matters to one research line."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    importance: Importance = Field(
        description="For someone following the research line `line`, how much does `claim` matter?"
    )


ASK: Final = Ask(
    function="report_ordering",
    version="v1",
    output=Answers,
    instructions="You order claims for a research report.",
)

THRESHOLDS: Final = ()
"""Ordering has no cut-off: every claim stays, only its position depends on the score."""


def importance(judged: Judged[Answers]) -> float:
    return position(judged, "importance")


def state(ctx: LineContext, claim: Claim) -> dict[str, JsonValue]:
    return {"line": line_state(ctx), "claim": claim.text}


async def judge(
    jev: JevClient, ctx: LineContext, claim: Claim, *, now: AwareDatetime
) -> Judged[Answers] | JevFailure:
    return await jev.judge(ASK, (claim.id,), state(ctx, claim), now=now)


def decision(result: Judged[Answers] | JevFailure) -> Decision:
    return decide(result, ask=ASK, thresholds=THRESHOLDS, rule=lambda j: (True, importance(j)))


def order(decisions: list[Decision]) -> list[str]:
    """Claim @ids: judged by descending score, then unjudged; ties broken by @id."""
    judged = sorted(
        (d for d in decisions if d.score is not None),
        key=lambda d: (-(d.score or 0.0), d.subjects[0]),
    )
    unjudged = sorted(d.subjects[0] for d in decisions if d.score is None)
    return [d.subjects[0] for d in judged] + unjudged
