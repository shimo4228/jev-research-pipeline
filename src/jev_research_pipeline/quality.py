"""Step 8: the rubric ladder wired to Report.rendering, and rubric-vs-gold agreement.

Ladder (decision 8): qwen.prose.render drives draft → rubric_report → one rewrite →
template; rubric_ladder() supplies the real writer (Qwen max) and grader (Jev
rubric_report), and build_report() maps the result onto Report.

Agreement (decision 5): per rubric axis, a rubric_claim judgment "predicts correct" when
the axis' expected position clears its threshold; the author's Label is the gold. An
axis is trusted (may act as a silver label in fits) only with at least `min_labels`
labeled pairs and agreement ≥ AGREEMENT_FLOOR.
"""

from datetime import date
from typing import Final

from pydantic import AwareDatetime, computed_field
from pydantic_ai.models.openai import OpenAIChatModel

from .jev import JevClient, Judged, rubric_claim, rubric_report
from .jev.context import LineContext
from .jev.core import score, threshold
from .model import AxisMeter, Decision, Judgment, Label, Operations, Report, RubricAxis
from .model.jsonld import Value
from .qwen import GenerationMeter, ProseResult, Rendering, render, write_prose
from .qwen.prose import PROSE_TIMEOUT_S

AGREEMENT_FLOOR: Final = 0.7
"""Initial floor for trusting a rubric axis as silver labels; refit with the labels."""
MIN_LABELS: Final = 10


class AxisAgreement(Value):
    axis: RubricAxis
    n: int
    agreed: int

    @computed_field
    @property
    def rate(self) -> float | None:
        return self.agreed / self.n if self.n else None


def _position(j: Judgment, axis: RubricAxis) -> float:
    return score(j, axis).expected_position


def _current_rubric(judgments: list[Judgment]) -> dict[tuple[str, str], Judgment]:
    """One rubric_claim judgment per (claim, report): current bundle wording, latest judged.
    Re-runs and rewordings must not count one labeled pair more than once."""
    latest: dict[tuple[str, str], Judgment] = {}
    for j in sorted(judgments, key=lambda j: (j.judged_at, j.id)):
        if j.function == "rubric_claim" and j.bundle_sha256 == rubric_claim.ASK.sha256:
            latest[(j.subjects[0], j.subjects[1])] = j
    return latest


def agreement(judgments: list[Judgment], labels: list[Label]) -> dict[RubricAxis, AxisAgreement]:
    """Pairs = labeled (claim, report) with a current rubric_claim judgment, counted once."""
    gold = {(lb.claim, lb.report): lb.verdict == "correct" for lb in labels}
    counts: dict[RubricAxis, list[int]] = {axis: [0, 0] for axis in rubric_claim.AXES}
    for key, j in _current_rubric(judgments).items():
        if key not in gold:
            continue
        for axis in rubric_claim.AXES:
            predicted = _position(j, axis) >= threshold(rubric_claim.THRESHOLDS, axis)
            counts[axis][0] += 1
            counts[axis][1] += int(predicted == gold[key])
    return {axis: AxisAgreement(axis=axis, n=n, agreed=a) for axis, (n, a) in counts.items()}


def trusted_axes(
    agreements: dict[RubricAxis, AxisAgreement],
    *,
    floor: float = AGREEMENT_FLOOR,
    min_labels: int = MIN_LABELS,
) -> tuple[RubricAxis, ...]:
    return tuple(
        axis
        for axis in rubric_claim.AXES
        if (a := agreements[axis]).n >= min_labels and (a.rate or 0.0) >= floor
    )


def axis_meters(
    today: list[Judgment], agreements: dict[RubricAxis, AxisAgreement]
) -> tuple[AxisMeter, ...]:
    """Operations rubric line: today's mean score per axis + cumulative gold agreement."""
    rubric = list(_current_rubric(today).values())
    meters: list[AxisMeter] = []
    for axis in rubric_claim.AXES:
        values = [_position(j, axis) for j in rubric]
        mean = sum(values) / len(values) if values else None  # no data ≠ worst score
        meters.append(AxisMeter(axis=axis, mean_score=mean, gold_agreement=agreements[axis].rate))
    return tuple(meters)


async def rubric_ladder(
    *,
    jev: JevClient,
    model: OpenAIChatModel,
    ctx: LineContext,
    report_id: str,
    claims: list[str],
    meter: GenerationMeter,
    now: AwareDatetime,
    timeout_s: float = PROSE_TIMEOUT_S,
) -> tuple[Rendering, list[Judgment]]:
    """`claims` = accepted claim texts in report_ordering order.

    Returns the rendering and every draft's rubric_report Judgment (dense labels; each
    draft's prose differs, so each Judgment has its own @id). The Decisions of both drafts
    share one @id (same report, bundle, policy): storing them keeps the final draft's
    decision, which is the report's — the per-draft evidence lives in the Judgments."""
    judged: list[Judgment] = []

    async def write(feedback: str | None) -> ProseResult:
        return await write_prose(
            model, ctx, claims, feedback=feedback, meter=meter, timeout_s=timeout_s
        )

    async def evaluate(prose: str) -> Decision:
        result = await rubric_report.judge(
            jev, report_id, rubric_report.state(ctx, prose, claims), now=now
        )
        if isinstance(result, Judged):
            judged.append(result.judgment)
        return rubric_report.decision(result)

    return await render(write, evaluate), judged


def build_report(
    *,
    line: str,
    run_date: date,
    rendering: Rendering,
    claims: tuple[str, ...],
    unjudged: tuple[str, ...],
    partial: bool,
    operations: Operations,
) -> Report:
    return Report.new(
        line=line,
        run_date=run_date,
        rendering=rendering.rendering,
        prose=rendering.prose,
        claims=claims,
        unjudged=unjudged,
        partial=partial,
        operations=operations,
    )
