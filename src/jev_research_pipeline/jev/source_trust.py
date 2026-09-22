"""source_trust — how much weight a source deserves, on concrete-situation levels.

Subjects: (SourceItem,). Levels describe what the source *is*, not an abstract degree.
"""

from typing import Final

from pydantic import AwareDatetime, BaseModel, JsonValue

from jev_research_pipeline.model import Decision, Judgment, SourceItem, Threshold

from .context import source_state
from .core import Bundle, JevClient, JevFailure, Level, ScoreQ, decide, score, threshold

BUNDLE: Final = Bundle(
    function="source_trust",
    version="v1",
    questions=(
        ScoreQ(
            key="trust",
            instructions="Judging from `source` (its URL, title and excerpt), which describes it best?",
            levels=(
                Level(
                    key="anonymous",
                    description="An anonymous or promotional page with no author, no date and no references.",
                ),
                Level(
                    key="personal",
                    description="A personal blog, newsletter or forum post by a named author, "
                    "with few or no references to evidence.",
                ),
                Level(
                    key="report",
                    description="A preprint, technical report or repository that describes its method "
                    "and reports results someone could reproduce.",
                ),
                Level(
                    key="established",
                    description="A peer-reviewed paper, or official documentation or release notes from "
                    "the organization that built the system it describes.",
                ),
            ),
        ),
    ),
)

THRESHOLDS: Final = (Threshold(name="min_trust", value=0.5),)


class Answers(BaseModel):
    trust: float
    """Expected level position in [0, 1]."""

    @classmethod
    def of(cls, j: Judgment) -> "Answers":
        return cls(trust=score(j, "trust").expected_position)


def state(source: SourceItem) -> dict[str, JsonValue]:
    return {"source": source_state(source)}


async def judge(jev: JevClient, source: SourceItem, *, now: AwareDatetime) -> Judgment | JevFailure:
    return await jev.judge(BUNDLE, (source.id,), state(source), now=now)


def rule(j: Judgment) -> tuple[bool, float]:
    t = Answers.of(j).trust
    return t >= threshold(THRESHOLDS, "min_trust"), t


def decision(result: Judgment | JevFailure) -> Decision:
    return decide(result, policy=BUNDLE.policy, thresholds=THRESHOLDS, rule=rule)
