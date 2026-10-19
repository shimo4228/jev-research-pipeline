"""Step 8: the rubric ladder wired to Report.rendering, and the rubric meters.

Ladder (decision 8): generation.prose.render drives draft → rubric_report → one rewrite →
template; rubric_ladder() supplies the real writer (the prose model, generation.client) and
grader (Jev rubric_report), and build_report() maps the result onto Report.

Meters: axis_meters() is today's mean rubric_claim score per axis, stored on the Report's
Operations. No agreement with the author's gold ticks is computed: the claim gold is the
question-day ticks propagated to claims, all correct as of 2026-10-20, so a rate only
restated each axis' pass rate (design decision 5, note of 2026-10-20).
"""

import asyncio
import re
from datetime import date
from typing import Final

from pydantic import AwareDatetime
from pydantic_ai.models import Model

from .generation import GenerationMeter, ProseResult, Rendering, render, write_prose
from .generation.prose import (
    CHECK_PROMPTS,
    NO_DIRECT_EVIDENCE,
    PROSE_PROMPTS,
    PROSE_TIMEOUT_S,
    STUDY_NAME_LINE,
    evidence_text,
)
from .jev import JevClient, Judged, rubric_claim, rubric_report
from .jev.context import LineContext
from .jev.core import score
from .model import AxisMeter, Decision, Judgment, Operations, Question, Report, RubricAxis
from .note_text import DEFAULT_LANG, Lang


def _position(j: Judgment, axis: RubricAxis) -> float:
    return score(j, axis).expected_position


def _current_rubric(judgments: list[Judgment]) -> dict[tuple[str, str], Judgment]:
    """One rubric_claim judgment per (claim, report): current bundle wording, latest judged.
    Re-runs and rewordings must not count one claim more than once."""
    latest: dict[tuple[str, str], Judgment] = {}
    for j in sorted(judgments, key=lambda j: (j.judged_at, j.id)):
        if j.function == "rubric_claim" and j.bundle_sha256 == rubric_claim.ASK.sha256:
            latest[(j.subjects[0], j.subjects[1])] = j
    return latest


def axis_meters(today: list[Judgment]) -> tuple[AxisMeter, ...]:
    """Operations rubric meters: today's mean score per axis (gold_agreement stays None)."""
    rubric = list(_current_rubric(today).values())
    meters: list[AxisMeter] = []
    for axis in rubric_claim.AXES:
        values = [_position(j, axis) for j in rubric]
        mean = sum(values) / len(values) if values else None  # no data ≠ worst score
        meters.append(AxisMeter(axis=axis, mean_score=mean))
    return tuple(meters)


class _LangCheck:
    """The default self-check of rubric_ladder: CHECK_PROMPTS of the ladder's language."""


LANG_CHECK: Final = _LangCheck()


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
    check: str | _LangCheck | None = LANG_CHECK,
    lang: Lang = DEFAULT_LANG,
) -> tuple[Rendering, list[Judgment]]:
    """One question's section: `claims` = its accepted claim texts, in reading order.
    `lang` = the note language: the prompt (PROSE_PROMPTS), the rewrite feedback and the
    rubric's asks follow it, and so does the self-check unless `check` names one (None = no
    self-check pass).

    Returns the rendering and every draft's rubric_report Judgment (dense labels; each
    draft's prose differs, so each Judgment has its own @id). The Decisions of both drafts
    share one @id (same report, bundle, policy): storing them keeps the final draft's
    decision, which is the report's — the per-draft evidence lives in the Judgments."""
    judged: list[Judgment] = []
    check_text = CHECK_PROMPTS[lang] if isinstance(check, _LangCheck) else check

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
            instructions=PROSE_PROMPTS[lang],
            lang=lang,
        )
        if check_text is None or drafted.prose is None:
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
            instructions=check_text,
            sources=sources,
            claim_sources=claim_sources,
            draft=drafted.prose,
            lang=lang,
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
            jev,
            report_id,
            rubric_report.state(ctx, evidence, claims, known or None),
            now=now,
            lang=lang,
        )
        if isinstance(result, Judged):
            judged.append(result.judgment)
        base = rubric_report.decision(result)
        if base.outcome != "accept":
            return base
        # claim_fidelity, one request per evidence paragraph: recorded as Judgments (labels
        # for a later refit), never a gate. As a gate it rejected faithful sections that
        # explain background from the excerpts (author 2026-10-02; design "Production check
        # vs the prose bench"); fidelity is the self-check's and the prompt's job.
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
                    lang=lang,
                )
                for p in evidence.split("\n\n")
                # a study's bold name line says nothing to check, and citing nothing it
                # would be judged against every claim
                if p.replace(NO_DIRECT_EVIDENCE, "").strip() and not STUDY_NAME_LINE.match(p)
            )
        )
        for check in checks:
            if isinstance(check, Judged):
                judged.append(check.judgment)
        return base

    return await render(write, evaluate, lang), judged


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
