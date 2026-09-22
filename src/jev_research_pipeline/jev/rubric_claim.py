"""rubric_claim — Score each accepted claim in its report context on four rubric axes.

Subjects: (Claim, Report). Axes = RubricAxis (grounded / relevant / novel / actionable),
each with concrete-situation levels (vendor guidance: not abstract degrees). These scores
are the dense labels of decision 5: recorded for every claim every day, validated per
axis against the author's gold ticks before they may act as silver labels in a fit.
"""

from typing import Final

from pydantic import AwareDatetime, BaseModel, JsonValue

from jev_research_pipeline.model import (
    Claim,
    Decision,
    Judgment,
    RubricAxis,
    SourceItem,
    Threshold,
)

from .context import LineContext, line_state, source_state
from .core import Bundle, JevClient, JevFailure, Level, ScoreQ, decide, score, threshold

AXES: Final[tuple[RubricAxis, ...]] = ("grounded", "relevant", "novel", "actionable")

BUNDLE: Final = Bundle(
    function="rubric_claim",
    version="v1",
    questions=(
        ScoreQ(
            key="grounded",
            instructions="How well does `source.excerpt` back `claim` as it is presented in `report_context`?",
            levels=(
                Level(key="absent", description="The source does not contain what the claim says."),
                Level(
                    key="partial",
                    description="The source says something close, but the report overstates it.",
                ),
                Level(
                    key="backed",
                    description="The source states the claim as the report presents it.",
                ),
            ),
        ),
        ScoreQ(
            key="relevant",
            instructions="How relevant is `claim` to the research line `line`?",
            levels=(
                Level(
                    key="off_topic",
                    description="It is about none of the terms in `line.vocabulary`.",
                ),
                Level(
                    key="adjacent",
                    description="It is about a neighbouring topic that touches `line.vocabulary`.",
                ),
                Level(key="core", description="It is directly about a term in `line.vocabulary`."),
            ),
        ),
        ScoreQ(
            key="novel",
            instructions="Compared with `stored_similar` (claims already in the store), how new is `claim`?",
            levels=(
                Level(key="repeat", description="One of `stored_similar` already says this."),
                Level(
                    key="extends",
                    description="It adds a condition, number or result to one of `stored_similar`.",
                ),
                Level(key="new", description="None of `stored_similar` covers it."),
            ),
        ),
        ScoreQ(
            key="actionable",
            instructions="Could the author of this line act on `claim` — try, change or check something?",
            levels=(
                Level(key="none", description="There is nothing to do with it beyond knowing it."),
                Level(
                    key="later",
                    description="It suggests something to look into once more is known.",
                ),
                Level(
                    key="now",
                    description="It names a method, tool or setting the author could try this week.",
                ),
            ),
        ),
    ),
)

THRESHOLDS: Final = tuple(Threshold(name=axis, value=0.5) for axis in AXES)


class Answers(BaseModel):
    """Expected level position in [0, 1] per axis."""

    grounded: float
    relevant: float
    novel: float
    actionable: float

    @classmethod
    def of(cls, j: Judgment) -> "Answers":
        return cls(**{axis: score(j, axis).expected_position for axis in AXES})


def state(
    ctx: LineContext,
    claim: Claim,
    source: SourceItem,
    report_context: str | None,
    stored_similar: list[str],
    *,
    span: tuple[int, int] | None,
) -> dict[str, JsonValue]:
    """`span` = the claim's unit [start, end) in `source` (its own source): the excerpt is
    centred there so `grounded` is judged on the passage the claim came from."""
    return {
        "line": line_state(ctx),
        "claim": claim.text,
        "source": source_state(source, around=span),
        "report_context": report_context,
        "stored_similar": list(stored_similar),
    }


async def judge(
    jev: JevClient,
    report_id: str,
    claim: Claim,
    claim_state: dict[str, JsonValue],
    *,
    now: AwareDatetime,
) -> Judgment | JevFailure:
    return await jev.judge(BUNDLE, (claim.id, report_id), claim_state, now=now)


def rule(j: Judgment) -> tuple[bool, float]:
    a = Answers.of(j)
    values = {axis: getattr(a, axis) for axis in AXES}
    passed = all(values[axis] >= threshold(THRESHOLDS, axis) for axis in AXES)
    return passed, min(values.values())


def decision(result: Judgment | JevFailure) -> Decision:
    return decide(result, bundle=BUNDLE, thresholds=THRESHOLDS, rule=rule)
