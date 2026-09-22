"""claim_detection — per code-cut Unit: does it state a checkable claim, relevant to the line?

Subjects: (Unit,). Claim = the unit verbatim (Claim.from_unit), so an accepted unit needs
no quote matching later.
"""

from typing import Final

from pydantic import AwareDatetime, BaseModel, JsonValue

from jev_research_pipeline.model import Decision, Judgment, SourceItem, Threshold, Unit

from .context import LineContext, line_state
from .core import Bundle, JevClient, JevFailure, NoulQ, decide, noul, threshold

BUNDLE: Final = Bundle(
    function="claim_detection",
    version="v1",
    questions=(
        NoulQ(
            key="checkable_claim",
            instructions="Does `unit.text` on its own state a claim that could be checked against "
            "evidence (a result, a measurement, a property of a method or system), not a heading, "
            "question, greeting or pure opinion?",
        ),
        NoulQ(
            key="relevant",
            instructions="Is the claim in `unit.text` about a term in `line.vocabulary` or work "
            "that directly bears on one?",
        ),
    ),
)

THRESHOLDS: Final = (
    Threshold(name="checkable_claim", value=0.5),
    Threshold(name="relevant", value=0.5),
)


class Answers(BaseModel):
    checkable_claim: float
    relevant: float

    @classmethod
    def of(cls, j: Judgment) -> "Answers":
        return cls(checkable_claim=noul(j, "checkable_claim"), relevant=noul(j, "relevant"))


def state(ctx: LineContext, unit: Unit, source: SourceItem) -> dict[str, JsonValue]:
    return {"line": line_state(ctx), "unit": {"text": unit.text, "source_title": source.title}}


async def judge(
    jev: JevClient, ctx: LineContext, unit: Unit, source: SourceItem, *, now: AwareDatetime
) -> Judgment | JevFailure:
    return await jev.judge(BUNDLE, (unit.id,), state(ctx, unit, source), now=now)


def rule(j: Judgment) -> tuple[bool, float]:
    a = Answers.of(j)
    accept = a.checkable_claim >= threshold(
        THRESHOLDS, "checkable_claim"
    ) and a.relevant >= threshold(THRESHOLDS, "relevant")
    return accept, min(a.checkable_claim, a.relevant)


def decision(result: Judgment | JevFailure) -> Decision:
    return decide(result, policy=BUNDLE.policy, thresholds=THRESHOLDS, rule=rule)
