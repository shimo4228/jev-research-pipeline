"""query_selection — Score each Qwen query candidate's expected yield; code keeps top-k.

Subjects: (QueryCandidate,). Candidates are generated and scored per open Question, so
"yield" means what the query would bring back *for that question*, not for the line at
large (a query that matches the line's vocabulary and none of its questions is the way
the first live run filled a report with nothing to answer). The keep/drop decision is relative (top-k among candidates
above a floor, per adapter — every adapter gets its own k), so rank() decides over the
whole candidate set at once.
"""

from enum import IntEnum
from typing import Final

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue
from pydantic_ai import UseEnumMemberDocstrings

from jev_research_pipeline.model import Decision, QueryCandidate, Question, Threshold

from .context import LineContext, line_state
from .core import Ask, JevClient, JevFailure, Judged, decide, position, threshold


class Yield(UseEnumMemberDocstrings, IntEnum):
    none = 0
    """Nothing returned would have anything to do with `question`."""
    tangential = 1
    """Mostly results about something else; at most one touches `question`."""
    some = 2
    """Several results work on the problem `question` asks about."""
    high = 3
    """Most results are recent work on the problem `question` asks about."""


class Answers(BaseModel):
    """Judge what one search query would bring back for one research line."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    expected_yield: Yield = Field(
        description="Running `search.query` against `search.adapter` today: how much of what "
        "comes back would bear on `question`, for the line described by `line`?"
    )


ASK: Final = Ask(
    function="query_selection",
    version="v2",
    output=Answers,
    instructions="You rank candidate search queries for a research pipeline.",
)

# Initial values = vendor rounding (0.5 midpoint); refit on the author's labels (decision 6①).
THRESHOLDS: Final = (Threshold(name="min_yield", value=0.5), Threshold(name="top_k", value=3.0))
FLOOR_FALLBACK_POLICY: Final = "query_selection@v2+floor_fallback"
"""Policy name recorded when top-k was taken although nothing cleared min_yield."""


def expected_yield(judged: Judged[Answers]) -> float:
    """Probability-weighted level position in [0, 1] — not the level Jev rounded to."""
    return position(judged, "expected_yield")


def state(ctx: LineContext, candidate: QueryCandidate, question: Question) -> dict[str, JsonValue]:
    return {
        "line": line_state(ctx),
        "question": {"title": question.title, "brief": question.brief},
        "search": {"adapter": candidate.adapter, "query": candidate.text},
    }


async def judge(
    jev: JevClient,
    ctx: LineContext,
    candidate: QueryCandidate,
    question: Question,
    *,
    now: AwareDatetime,
) -> Judged[Answers] | JevFailure:
    return await jev.judge(ASK, (candidate.id,), state(ctx, candidate, question), now=now)


def rank(pairs: list[tuple[QueryCandidate, Judged[Answers] | JevFailure]]) -> list[Decision]:
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
            (r for c, r in pairs if c.adapter == adapter and isinstance(r, Judged)),
            key=lambda r: (-expected_yield(r), r.subjects[0]),
        )
        above = [r for r in judged if expected_yield(r) >= floor]
        chosen = above[:top_k] if above else judged[:top_k]
        kept.update(r.judgment.id for r in chosen)
        if not above:
            fallback.update(r.judgment.id for r in chosen)
    return [
        decide(
            r,
            ask=ASK,
            thresholds=THRESHOLDS,
            rule=lambda j: (j.judgment.id in kept, expected_yield(j)),
            policy=FLOOR_FALLBACK_POLICY
            if isinstance(r, Judged) and r.judgment.id in fallback
            else None,
        )
        for _, r in pairs
    ]
