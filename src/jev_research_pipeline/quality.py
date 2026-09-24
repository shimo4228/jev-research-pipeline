"""Step 8: the rubric ladder wired to Report.rendering, and rubric-vs-gold agreement.

Ladder (decision 8): generation.prose.render drives draft → rubric_report → one rewrite →
template; rubric_ladder() supplies the real writer (the prose model, generation.client) and
grader (Jev rubric_report), and build_report() maps the result onto Report.

Agreement (decision 5): per rubric axis, a rubric_claim judgment "predicts correct" when
the axis' expected position clears its threshold; the author's Label is the gold. An
axis is trusted (may act as a silver label in fits) only with at least `min_labels`
labeled pairs and agreement ≥ AGREEMENT_FLOOR.
"""

import asyncio
import re
from datetime import date
from typing import Final

from pydantic import AwareDatetime, computed_field
from pydantic_ai.models import Model

from .generation import GenerationMeter, ProseResult, Rendering, render, write_prose
from .generation.prose import (
    CHECK_INSTRUCTIONS,
    NO_DIRECT_EVIDENCE,
    PROSE_TIMEOUT_S,
    evidence_text,
)
from .jev import JevClient, Judged, rubric_claim, rubric_report
from .jev.context import LineContext
from .jev.core import score, threshold
from .model import (
    AxisMeter,
    Decision,
    Judgment,
    Label,
    Operations,
    Question,
    Report,
    RubricAxis,
    kind_of,
)
from .model.jsonld import Value

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
    gold = {
        (lb.subject, lb.report): lb.verdict == "correct"
        for lb in labels
        if kind_of(lb.subject) == "claim"
    }
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
    model: Model,
    ctx: LineContext,
    question: Question,
    report_id: str,
    claims: list[str],
    meter: GenerationMeter,
    now: AwareDatetime,
    timeout_s: float = PROSE_TIMEOUT_S,
    evidence_set: list[str] | None = None,
    rewrite_model: Model | None = None,
    sources: list[dict[str, object]] | None = None,
    claim_sources: list[int] | None = None,
    check: str | None = CHECK_INSTRUCTIONS,
) -> tuple[Rendering, list[Judgment]]:
    """One question's section: `claims` = its accepted claim texts, in reading order.

    Returns the rendering and every draft's rubric_report Judgment (dense labels; each
    draft's prose differs, so each Judgment has its own @id). The Decisions of both drafts
    share one @id (same report, bundle, policy): storing them keeps the final draft's
    decision, which is the report's — the per-draft evidence lives in the Judgments."""
    judged: list[Judgment] = []

    async def write(feedback: str | None) -> ProseResult:
        # A rewrite (feedback given) may go to another model setting — prose thinking
        # policy "rewrite" spends the slow thinking draft only where the fast one failed.
        writer = rewrite_model if feedback is not None and rewrite_model is not None else model
        drafted = await write_prose(
            writer,
            ctx,
            question,
            claims,
            feedback=feedback,
            meter=meter,
            timeout_s=timeout_s,
            evidence_set=evidence_set,
            sources=sources,
            claim_sources=claim_sources,
        )
        if check is None or drafted.prose is None:
            return drafted
        # The self-check pass (prose bench): the same model re-reads the draft against the
        # claims and excerpts and fixes factual slips only; a failed check keeps the draft.
        checked = await write_prose(
            writer,
            ctx,
            question,
            claims,
            feedback=None,
            meter=meter,
            timeout_s=timeout_s,
            evidence_set=evidence_set,
            instructions=check,
            sources=sources,
            claim_sources=claim_sources,
            draft=drafted.prose,
        )
        return drafted.model_copy(
            update={
                "prose": checked.prose or drafted.prose,
                "seconds": round(drafted.seconds + checked.seconds, 3),
                "invalid_citations": checked.invalid_citations or drafted.invalid_citations,
            }
        )

    excerpts = [str(s.get("excerpt", "")) for s in sources or []]

    async def evaluate(prose: str) -> Decision:
        # `grounded` is judged on the evidence paragraphs only: the marked inference
        # paragraph is allowed to go beyond the claims, that is what marking it is for.
        evidence = evidence_text(prose)
        # The excerpts the writer was given count as grounding too (a fact cited (S1) is
        # not unsupported), next to the question's evidence set.
        known = [*(evidence_set or []), *excerpts]
        result = await rubric_report.judge(
            jev, report_id, rubric_report.state(ctx, evidence, claims, known or None), now=now
        )
        if isinstance(result, Judged):
            judged.append(result.judgment)
        base = rubric_report.decision(result)
        if base.outcome != "accept":
            return base
        # claim_fidelity, one request per evidence paragraph: a single paragraph that
        # restates a claim in the question's terms sends the draft back.
        checks = await asyncio.gather(
            *(
                rubric_report.judge_fidelity(
                    jev,
                    report_id,
                    rubric_report.fidelity_state(
                        question.title,
                        p.replace(NO_DIRECT_EVIDENCE, "").strip(),
                        cited_claims(p, claims) + cited_excerpts(p, excerpts),
                    ),
                    now=now,
                )
                for p in evidence.split("\n\n")
                if p.replace(NO_DIRECT_EVIDENCE, "").strip()
            )
        )
        for check in checks:
            if isinstance(check, Judged):
                judged.append(check.judgment)
        verdicts = [rubric_report.fidelity_decision(c) for c in checks]
        return next((d for d in verdicts if d.outcome != "accept"), base)

    return await render(write, evaluate), judged


def cited_claims(paragraph: str, claims: list[str]) -> list[str]:
    """The claims a paragraph cites by [n]; all of them when it cites none."""
    cited = [
        claims[n - 1]
        for n in dict.fromkeys(int(m) for m in re.findall(r"\[(\d+)\]", paragraph))
        if 1 <= n <= len(claims)
    ]
    return cited or list(claims)


def cited_excerpts(paragraph: str, excerpts: list[str]) -> list[str]:
    """The source excerpts a paragraph cites as (S1), (S2) …"""
    return [
        excerpts[n - 1]
        for n in dict.fromkeys(int(m) for m in re.findall(r"\(S(\d+)\)", paragraph))
        if 1 <= n <= len(excerpts)
    ]


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
