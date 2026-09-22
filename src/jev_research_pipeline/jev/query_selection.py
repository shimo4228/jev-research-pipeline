"""query_selection — Score each Qwen query candidate's expected yield; code keeps top-k.

Subjects: (QueryCandidate,). The keep/drop decision is relative (top-k among candidates
above a floor, per adapter — every adapter gets its own k), so rank() decides over the
whole candidate set at once.
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
FLOOR_FALLBACK_POLICY: Final = "query_selection@v1+floor_fallback"
"""Policy name recorded when top-k was taken although nothing cleared min_yield."""


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


def rank(pairs: list[tuple[QueryCandidate, Judgment | JevFailure]]) -> list[Decision]:
    """Per adapter, accept the top_k judged candidates whose yield clears min_yield (ties
    by @id). When nothing clears the floor, accept the top_k anyway under
    FLOOR_FALLBACK_POLICY: the floor is a vendor rounding value that only labels can
    refit, and a line that fetches nothing never produces the labels (first live run,
    2026-09-22: 9 candidates scored 0.16-0.38, zero sources). Decisions come back in the
    order of `pairs`."""
    floor = threshold(THRESHOLDS, "min_yield")
    top_k = int(threshold(THRESHOLDS, "top_k"))
    kept: set[str] = set()
    fallback: set[str] = set()
    for adapter in {c.adapter for c, _ in pairs}:
        judged = sorted(
            (r for c, r in pairs if c.adapter == adapter and isinstance(r, Judgment)),
            key=lambda r: (-Answers.of(r).expected_yield, r.subjects[0]),
        )
        above = [r for r in judged if Answers.of(r).expected_yield >= floor]
        chosen = above[:top_k] if above else judged[:top_k]
        kept.update(r.id for r in chosen)
        if not above:
            fallback.update(r.id for r in chosen)
    return [
        decide(
            r,
            bundle=BUNDLE,
            thresholds=THRESHOLDS,
            rule=lambda j: (j.id in kept, Answers.of(j).expected_yield),
            policy=FLOOR_FALLBACK_POLICY if isinstance(r, Judgment) and r.id in fallback else None,
        )
        for _, r in pairs
    ]
