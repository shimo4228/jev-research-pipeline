"""question_seeding — is a proposed question worth opening for this line?

Subjects: (Question,). The candidates come from code (the line's description and its ADR
Review-when lines) phrased by Qwen flash; Jev scores them and the author adopts by ticking
the proposal in the note. Nothing here opens a question on its own.
"""

from enum import IntEnum
from typing import Final

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue
from pydantic_ai import UseEnumMemberDocstrings

from jev_research_pipeline.model import Decision, Question, Threshold
from jev_research_pipeline.model.nodes import Probability

from .context import LineContext, line_state
from .core import Ask, JevClient, JevFailure, Judged, decide, position, threshold


class Impact(UseEnumMemberDocstrings, IntEnum):
    none = 0
    """Whatever the answer turns out to be, the author would work the same way."""
    detail = 1
    """The answer would change a detail of how the author works, not the direction."""
    direction = 2
    """The answer would decide which of two directions the author takes next."""
    stance = 3
    """The answer would overturn a position the line currently rests on."""


class Answers(BaseModel):
    """Judge one proposed research question against the line it would be opened for."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    open_for_line: Probability = Field(
        description="Is `question` a question this research line can actually work on — "
        "about `line.vocabulary`, and still open? No if it is already settled, or if it is "
        "about something this line does not do."
    )
    answerable_by_evidence: Probability = Field(
        description="Could published work move the answer to `question` — is there evidence "
        "to find? No if it is a matter of taste or of the author's own preference."
    )
    impact_on_stance: Impact = Field(
        description="If `question` were answered tomorrow, how much would it change what the "
        "author does?"
    )


ASK: Final = Ask(
    function="question_seeding",
    version="v1",
    output=Answers,
    instructions="You judge proposed research questions for a research pipeline.",
)

THRESHOLDS: Final = (
    Threshold(name="open_for_line", value=0.6),
    Threshold(name="answerable_by_evidence", value=0.5),
    Threshold(name="min_impact", value=0.34),
)
"""Initial values: a proposal has to be clearly for this line (0.6) and to move something
above the lowest rubric level. Refit on the author's adoptions (decision 6①)."""


def state(ctx: LineContext, question: Question, seeds: list[str]) -> dict[str, JsonValue]:
    return {
        "line": line_state(ctx),
        "question": {"title": question.title, "brief": question.brief},
        "line_notes": list(seeds),
    }


async def judge(
    jev: JevClient, ctx: LineContext, question: Question, seeds: list[str], *, now: AwareDatetime
) -> Judged[Answers] | JevFailure:
    return await jev.judge(ASK, (question.id,), state(ctx, question, seeds), now=now)


def rule(judged: Judged[Answers]) -> tuple[bool, float]:
    a = judged.output
    impact = position(judged, "impact_on_stance")
    accept = (
        a.open_for_line >= threshold(THRESHOLDS, "open_for_line")
        and a.answerable_by_evidence >= threshold(THRESHOLDS, "answerable_by_evidence")
        and impact >= threshold(THRESHOLDS, "min_impact")
    )
    return accept, min(a.open_for_line, a.answerable_by_evidence, impact)


def decision(result: Judged[Answers] | JevFailure) -> Decision:
    return decide(result, ask=ASK, thresholds=THRESHOLDS, rule=rule)
