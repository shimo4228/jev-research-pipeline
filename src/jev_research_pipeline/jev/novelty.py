"""novelty — is a new claim new relative to the store? (vendor entity_alignment recipe)

Code pre-pass: FTS5 top-k over the line's stored claims → candidate pairs (new, stored).
Jev per pair: Score{unrelated / related_or_extends / same_claim} + Noul{contradicts} +
Noul{same_source}. Subjects: (new claim, stored claim), in that order.
A pair Decision accepts when the new claim is NOT the same claim as the stored one.
A claim is novel iff every pair accepts; no candidate pair at all means novel with no
Jev call; any unjudged pair makes the claim unjudged (never fail-open into "novel").
"""

from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, JsonValue

from jev_research_pipeline.model import Claim, Decision, Judgment, Threshold
from jev_research_pipeline.store import ClaimIndex

from .core import (
    Bundle,
    JevClient,
    JevFailure,
    Level,
    NoulQ,
    ScoreQ,
    decide,
    noul,
    score,
    threshold,
)

BUNDLE: Final = Bundle(
    function="novelty",
    version="v1",
    questions=(
        ScoreQ(
            key="relation",
            instructions="How does `new_claim` relate to `stored_claim`?",
            levels=(
                Level(key="unrelated", description="They are about different things."),
                Level(
                    key="related_or_extends",
                    description="Same topic, but `new_claim` adds a result, condition or detail "
                    "that `stored_claim` does not state.",
                ),
                Level(
                    key="same_claim",
                    description="`new_claim` says what `stored_claim` already says, possibly in other words.",
                ),
            ),
        ),
        NoulQ(
            key="contradicts",
            instructions="Do `new_claim` and `stored_claim` contradict each other?",
        ),
        NoulQ(
            key="same_source",
            instructions="Do both claims appear to report the same underlying work — the same paper, "
            "repository, release or announcement?",
        ),
    ),
)

THRESHOLDS: Final = (
    Threshold(name="same_claim", value=0.5),
    Threshold(name="candidates_k", value=5.0),
)


class Answers(BaseModel):
    p_same_claim: float
    relation_position: float
    contradicts: float
    same_source: float

    @classmethod
    def of(cls, j: Judgment) -> "Answers":
        rel = score(j, "relation")
        return cls(
            p_same_claim=rel.probabilities[rel.levels.index("same_claim")],
            relation_position=rel.expected_position,
            contradicts=noul(j, "contradicts"),
            same_source=noul(j, "same_source"),
        )


def candidate_pairs(index: ClaimIndex, new: Claim) -> list[str]:
    """Stored claim @ids most similar to `new` (excluding itself), best first."""
    k = int(threshold(THRESHOLDS, "candidates_k"))
    return [i for i in index.search(new.text, limit=k + 1) if i != new.id][:k]


def state(new: Claim, stored: Claim) -> dict[str, JsonValue]:
    return {"new_claim": new.text, "stored_claim": stored.text}


async def judge(
    jev: JevClient, new: Claim, stored: Claim, *, now: AwareDatetime
) -> Judgment | JevFailure:
    return await jev.judge(BUNDLE, (new.id, stored.id), state(new, stored), now=now)


def rule(j: Judgment) -> tuple[bool, float]:
    p_same = Answers.of(j).p_same_claim
    return p_same < threshold(THRESHOLDS, "same_claim"), 1.0 - p_same


def decision(result: Judgment | JevFailure) -> Decision:
    return decide(result, policy=BUNDLE.policy, thresholds=THRESHOLDS, rule=rule)


def verdict(pair_decisions: list[Decision]) -> Literal["novel", "duplicate", "unjudged"]:
    if any(d.outcome == "reject" for d in pair_decisions):
        return "duplicate"
    if any(d.outcome == "unjudged" for d in pair_decisions):
        return "unjudged"
    return "novel"
