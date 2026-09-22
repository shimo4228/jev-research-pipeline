"""query_selection — Score each Qwen query candidate's expected yield; code keeps top-k.

Subjects: (QueryCandidate,). The keep/drop decision is relative (top-k among candidates
above a floor), so rank() decides over the whole candidate set at once.
"""

from typing import Final

from pydantic import AwareDatetime, BaseModel, JsonValue

from jev_research_pipeline.model import Decision, Judgment, QueryCandidate, Threshold

from .context import LineContext, line_state
from .core import Bundle, JevClient, JevFailure, Level, ScoreQ, decide, score, threshold

BUNDLE: Final = Bundle(
    function="query_selection",
    version="v1",
    questions=(
        ScoreQ(
            key="expected_yield",
            instructions=(
                "Running `search.query` against `search.adapter` today: how much of what comes "
                "back would be about the research line described by `line`?"
            ),
            levels=(
                Level(
                    key="none",
                    description="Nothing returned would mention any term in `line.vocabulary`.",
                ),
                Level(
                    key="tangential",
                    description="Mostly off-topic results; at most one touches a term in `line.vocabulary`.",
                ),
                Level(
                    key="some",
                    description="Several results directly discuss a term in `line.vocabulary`.",
                ),
                Level(
                    key="high",
                    description="Most results are recent work directly about terms in `line.vocabulary`.",
                ),
            ),
        ),
    ),
)

# Initial values = vendor rounding (0.5 midpoint); refit on the author's labels (decision 6①).
THRESHOLDS: Final = (Threshold(name="min_yield", value=0.5), Threshold(name="top_k", value=3.0))


class Answers(BaseModel):
    expected_yield: float
    """Expected level position in [0, 1]."""

    @classmethod
    def of(cls, j: Judgment) -> "Answers":
        return cls(expected_yield=score(j, "expected_yield").expected_position)


def state(ctx: LineContext, candidate: QueryCandidate) -> dict[str, JsonValue]:
    return {
        "line": line_state(ctx),
        "search": {"adapter": candidate.adapter, "query": candidate.text},
    }


async def judge(
    jev: JevClient, ctx: LineContext, candidate: QueryCandidate, *, now: AwareDatetime
) -> Judgment | JevFailure:
    return await jev.judge(BUNDLE, (candidate.id,), state(ctx, candidate), now=now)


def rank(results: list[Judgment | JevFailure]) -> list[Decision]:
    """Accept the top_k judged candidates whose yield clears min_yield; ties by @id."""
    floor = threshold(THRESHOLDS, "min_yield")
    top_k = int(threshold(THRESHOLDS, "top_k"))
    judged = [r for r in results if isinstance(r, Judgment)]
    eligible = sorted(
        (r for r in judged if Answers.of(r).expected_yield >= floor),
        key=lambda r: (-Answers.of(r).expected_yield, r.subjects[0]),
    )
    kept = {r.id for r in eligible[:top_k]}
    return [
        decide(
            r,
            policy=BUNDLE.policy,
            thresholds=THRESHOLDS,
            rule=lambda j: (j.id in kept, Answers.of(j).expected_yield),
        )
        for r in results
    ]
