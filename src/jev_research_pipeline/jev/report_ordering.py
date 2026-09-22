"""report_ordering — Score importance per accepted claim; code sorts the report by it.

Subjects: (Claim,). Every judged claim is accepted (ordering never drops a claim);
order() puts judged claims by descending importance and unjudged ones last.
"""

from typing import Final

from pydantic import AwareDatetime, BaseModel, JsonValue

from jev_research_pipeline.model import Claim, Decision, Judgment

from .context import LineContext, line_state
from .core import Bundle, JevClient, JevFailure, Level, ScoreQ, decide, score

BUNDLE: Final = Bundle(
    function="report_ordering",
    version="v1",
    questions=(
        ScoreQ(
            key="importance",
            instructions="For someone following the research line `line`, how much does `claim` matter?",
            levels=(
                Level(
                    key="known",
                    description="It restates something people working on `line.vocabulary` already take for granted.",
                ),
                Level(
                    key="minor",
                    description="A small detail or an incremental result on an existing method.",
                ),
                Level(
                    key="notable",
                    description="A new result or method a practitioner of this line would likely read in full.",
                ),
                Level(
                    key="shift",
                    description="It changes how a core term in `line.vocabulary` should be understood or practiced.",
                ),
            ),
        ),
    ),
)

THRESHOLDS: Final = ()
"""Ordering has no cut-off: every claim stays, only its position depends on the score."""


class Answers(BaseModel):
    importance: float

    @classmethod
    def of(cls, j: Judgment) -> "Answers":
        return cls(importance=score(j, "importance").expected_position)


def state(ctx: LineContext, claim: Claim) -> dict[str, JsonValue]:
    return {"line": line_state(ctx), "claim": claim.text}


async def judge(
    jev: JevClient, ctx: LineContext, claim: Claim, *, now: AwareDatetime
) -> Judgment | JevFailure:
    return await jev.judge(BUNDLE, (claim.id,), state(ctx, claim), now=now)


def decision(result: Judgment | JevFailure) -> Decision:
    return decide(
        result,
        policy=BUNDLE.policy,
        thresholds=THRESHOLDS,
        rule=lambda j: (True, Answers.of(j).importance),
    )


def order(decisions: list[Decision]) -> list[str]:
    """Claim @ids: judged by descending score, then unjudged; ties broken by @id."""
    judged = sorted(
        (d for d in decisions if d.score is not None),
        key=lambda d: (-(d.score or 0.0), d.subjects[0]),
    )
    unjudged = sorted(d.subjects[0] for d in decisions if d.score is None)
    return [d.subjects[0] for d in judged] + unjudged
