"""rubric_report — per report: readability, coherence, unsupported statements.

Subjects: (Report,). A failing decision drives the rendering ladder (qwen.prose):
prose → one rewrite → template. The state holds the prose and the accepted claims it
may rest on, so "unsupported" means "not backed by any of `claims`".
"""

from typing import Final

from pydantic import AwareDatetime, BaseModel, JsonValue

from jev_research_pipeline.model import Decision, Judgment, Threshold

from .context import LineContext, line_state
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
    function="rubric_report",
    version="v1",
    questions=(
        ScoreQ(
            key="readability",
            instructions="How easily can a Japanese-reading practitioner follow `prose`?",
            levels=(
                Level(
                    key="hard",
                    description="Sentences are broken, run on, or mix languages mid-sentence.",
                ),
                Level(
                    key="effortful",
                    description="Readable, but the reader has to re-read to get the point.",
                ),
                Level(key="clear", description="Each paragraph makes its point on the first read."),
            ),
        ),
        ScoreQ(
            key="coherence",
            instructions="How well do the paragraphs of `prose` hang together as one report on `line`?",
            levels=(
                Level(
                    key="list", description="Disconnected paragraphs with no thread between them."
                ),
                Level(
                    key="loose",
                    description="A loose sequence; connections are implied but not stated.",
                ),
                Level(
                    key="report",
                    description="The paragraphs build on each other toward a point about `line`.",
                ),
            ),
        ),
        NoulQ(
            key="unsupported_statement",
            instructions="Does `prose` state a fact that none of `claims` supports?",
        ),
    ),
)

THRESHOLDS: Final = (
    Threshold(name="readability", value=0.5),
    Threshold(name="coherence", value=0.5),
    Threshold(name="unsupported_statement", value=0.5),
)


class Answers(BaseModel):
    readability: float
    coherence: float
    unsupported_statement: float

    @classmethod
    def of(cls, j: Judgment) -> "Answers":
        return cls(
            readability=score(j, "readability").expected_position,
            coherence=score(j, "coherence").expected_position,
            unsupported_statement=noul(j, "unsupported_statement"),
        )


def state(ctx: LineContext, prose: str, claims: list[str]) -> dict[str, JsonValue]:
    return {"line": line_state(ctx), "prose": prose, "claims": list(claims)}


async def judge(
    jev: JevClient, report_id: str, report_state: dict[str, JsonValue], *, now: AwareDatetime
) -> Judgment | JevFailure:
    return await jev.judge(BUNDLE, (report_id,), report_state, now=now)


def rule(j: Judgment) -> tuple[bool, float]:
    a = Answers.of(j)
    passed = (
        a.readability >= threshold(THRESHOLDS, "readability")
        and a.coherence >= threshold(THRESHOLDS, "coherence")
        and a.unsupported_statement < threshold(THRESHOLDS, "unsupported_statement")
    )
    return passed, min(a.readability, a.coherence, 1.0 - a.unsupported_statement)


def decision(result: Judgment | JevFailure) -> Decision:
    return decide(result, policy=BUNDLE.policy, thresholds=THRESHOLDS, rule=rule)
