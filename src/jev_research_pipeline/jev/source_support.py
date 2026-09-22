"""source_support — does a source support a claim? (vendor citation_check recipe)

Code first: if the claim text occurs in the source text (whitespace-normalized), the
source supports it and Jev is not asked. Otherwise Jev: Choice{supports, contradicts,
says_nothing}. Subjects: (Claim, SourceItem), in that order.
"""

from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, JsonValue

from jev_research_pipeline.model import Claim, Decision, Judgment, SourceItem, Threshold
from jev_research_pipeline.model.jsonld import Value

from .context import best_match_span, source_state
from .core import Bundle, ChoiceQ, JevClient, JevFailure, Level, choice, decide, threshold

BUNDLE: Final = Bundle(
    function="source_support",
    version="v1",
    questions=(
        ChoiceQ(
            key="support",
            instructions="What does `source.excerpt` say about `claim`?",
            options=(
                Level(
                    key="supports",
                    description="The source states or directly shows what the claim says.",
                ),
                Level(
                    key="contradicts",
                    description="The source states or shows the opposite of the claim.",
                ),
                Level(
                    key="says_nothing",
                    description="The source neither supports nor contradicts the claim.",
                ),
            ),
        ),
    ),
)

THRESHOLDS: Final = (Threshold(name="supports", value=0.5),)

type Verdict = Literal["supports", "contradicts", "says_nothing", "unjudged"]


class Answers(BaseModel):
    p_supports: float
    p_contradicts: float
    p_says_nothing: float

    @classmethod
    def of(cls, j: Judgment) -> "Answers":
        c = choice(j, "support")
        p = dict(zip(c.options, c.probabilities, strict=True))
        return cls(
            p_supports=p["supports"],
            p_contradicts=p["contradicts"],
            p_says_nothing=p["says_nothing"],
        )


class SupportResult(Value):
    verdict: Verdict
    via: Literal["string_match", "jev"]
    decision: Decision | None
    """None when code decided by string match (no Jev call, no Judgment to cite)."""


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def string_match(claim: Claim, source: SourceItem) -> bool:
    return _normalized(claim.text) in _normalized(source.text)


def state(claim: Claim, source: SourceItem) -> dict[str, JsonValue]:
    """Excerpt centred where the claim's longest words first occur in the source."""
    return {
        "claim": claim.text,
        "source": source_state(source, around=best_match_span(source.text, claim.text)),
    }


def rule(j: Judgment) -> tuple[bool, float]:
    p = Answers.of(j).p_supports
    return p >= threshold(THRESHOLDS, "supports"), p


async def check(
    jev: JevClient, claim: Claim, source: SourceItem, *, now: AwareDatetime
) -> SupportResult:
    if string_match(claim, source):
        return SupportResult(verdict="supports", via="string_match", decision=None)
    result = await jev.judge(BUNDLE, (claim.id, source.id), state(claim, source), now=now)
    d = decide(result, bundle=BUNDLE, thresholds=THRESHOLDS, rule=rule)
    if not isinstance(result, Judgment):
        return SupportResult(verdict="unjudged", via="jev", decision=d)
    top = choice(result, "support").argmax
    verdict: Verdict
    if d.outcome == "accept":
        verdict = "supports"
    elif top == "contradicts":
        verdict = "contradicts"
    else:
        verdict = "says_nothing"
    return SupportResult(verdict=verdict, via="jev", decision=d)


__all__ = [
    "BUNDLE",
    "THRESHOLDS",
    "Answers",
    "JevFailure",
    "SupportResult",
    "check",
    "rule",
    "string_match",
]
