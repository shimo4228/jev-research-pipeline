"""Step 8: rubric ladder wired to Report.rendering, and rubric-vs-gold agreement per axis."""

import json
from enum import IntEnum

import httpx2
import pytest

from jev_research_pipeline.jev import rubric_claim, rubric_report
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.jev.core import score_levels
from jev_research_pipeline.model import (
    Claim,
    Judgment,
    Label,
    RubricAxis,
    ScoreAnswer,
    SourceItem,
    Unit,
)
from jev_research_pipeline.quality import (
    AGREEMENT_FLOOR,
    AxisAgreement,
    agreement,
    axis_meters,
    build_report,
    rubric_ladder,
    trusted_axes,
)
from jev_research_pipeline.qwen import MAX, GenerationMeter, qwen_model

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_jev, fake_qwen

CTX = LineContext(line=b.line(), vocabulary=("agent memory",))


def _claim(i: int) -> Claim:
    text = f"Claim number {i} about agent memory."
    src = SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url=f"https://arxiv.org/abs/{i}",
        title="t",
        text=text,
        fetched_at=b.T0,
    )
    return Claim.from_unit(
        Unit.cut(src, start=0, end=len(text), granularity="sentence"), line=b.LINE_IRI
    )


def _rubric(claim: Claim, positions: dict[str, float]) -> Judgment:
    """A rubric_claim judgment whose expected position per axis is `positions` (3 levels)."""
    answers: list[ScoreAnswer] = []
    for axis in rubric_claim.AXES:
        p = positions.get(axis, 1.0)
        # 3 levels: position p ∈ {0, 0.5, 1} → put all mass on that level.
        dist = tuple(1.0 if abs(i / 2 - p) < 1e-9 else 0.0 for i in range(3))
        annotation = rubric_claim.ASK.output.model_fields[axis].annotation
        assert isinstance(annotation, type) and issubclass(annotation, IntEnum)
        answers.append(ScoreAnswer(key=axis, levels=score_levels(annotation), probabilities=dist))
    return Judgment.new(
        function="rubric_claim",
        subjects=(claim.id, b.report().id),
        model="jev-1.13.0",
        state_sha256="a" * 64,
        bundle_sha256=rubric_claim.ASK.sha256,
        answers=tuple(answers),
        judged_at=b.T0,
    )


def _label(claim: Claim, verdict: str) -> Label:
    return Label.new(
        subject=claim.id,
        report=b.report().id,
        verdict=verdict,  # pyright: ignore[reportArgumentType]
        provenance="claim",
        harvested_at=b.T0,
    )


# --- agreement -----------------------------------------------------------------------------


def test_agreement_counts_matches_per_axis():
    c1, c2, c3 = _claim(1), _claim(2), _claim(3)
    judgments = [
        _rubric(c1, {"grounded": 1.0}),  # predicts correct
        _rubric(c2, {"grounded": 0.0}),  # predicts incorrect
        _rubric(c3, {"grounded": 1.0}),  # predicts correct
    ]
    labels = [_label(c1, "correct"), _label(c2, "incorrect"), _label(c3, "incorrect")]
    result = agreement(judgments, labels)
    assert result["grounded"] == AxisAgreement(axis="grounded", n=3, agreed=2)
    assert result["grounded"].rate == pytest.approx(2 / 3)
    # Every other axis predicted "correct" for all three: 1 of 3 labels agrees.
    assert result["novel"].agreed == 1


def test_agreement_ignores_unlabeled_and_unmatched():
    c1, c2 = _claim(1), _claim(2)
    result = agreement([_rubric(c1, {})], [_label(c2, "correct")])
    assert all(a.n == 0 and a.rate is None for a in result.values())


def test_trusted_axes_need_the_floor_and_enough_labels():
    agreements: dict[RubricAxis, AxisAgreement] = {
        "grounded": AxisAgreement(axis="grounded", n=40, agreed=36),
        "relevant": AxisAgreement(axis="relevant", n=40, agreed=20),
        "novel": AxisAgreement(axis="novel", n=3, agreed=3),
        "actionable": AxisAgreement(axis="actionable", n=0, agreed=0),
    }
    assert trusted_axes(agreements, floor=AGREEMENT_FLOOR, min_labels=10) == ("grounded",)


def test_axis_meters_feed_operations():
    c1 = _claim(1)
    meters = axis_meters(
        [_rubric(c1, {"grounded": 0.5})], agreement([_rubric(c1, {})], [_label(c1, "correct")])
    )
    grounded = next(m for m in meters if m.axis == "grounded")
    assert grounded.mean_score == pytest.approx(0.5)
    assert grounded.gold_agreement == 1.0
    assert {m.axis for m in meters} == set(rubric_claim.AXES)


# --- ladder wired to Report ------------------------------------------------------------------


async def test_rubric_ladder_accepts_first_draft(cassette: ClientFactory):
    client = cassette(fake_qwen("レポート本文 [1]。"))
    from jev_research_pipeline.jev import JevClient

    jev = JevClient(
        cassette(fake_jev({"unsupported_statement": 0.1, "exceeds_claims": 0.1})),
        api_key="replay",
    )
    rendering, _ = await rubric_ladder(
        jev=jev,
        model=qwen_model(MAX, client, api_key="replay"),
        ctx=CTX,
        question=b.question(),
        report_id=b.report().id,
        claims=[b.claim().text],
        meter=GenerationMeter(),
        now=b.T0,
        check=None,  # the ladder's own logic; the self-check pass has its own test
    )
    assert (rendering.rendering, rendering.prose) == ("prose", "レポート本文 [1]。")
    assert [d.function for d in rendering.rubric] == ["rubric_report"]
    assert rendering.rubric[0].bundle_sha256 == rubric_report.ASK.sha256


async def test_a_paragraph_that_restates_a_claim_in_the_questions_terms_is_sent_back(
    cassette: ClientFactory,
):
    """claim_fidelity (author mandate 2026-09-23): the judge read general LLM-calibration
    papers written up as findings about Jev. One evidence paragraph over the bar sends the
    draft back with the fidelity feedback; still over → template."""
    from jev_research_pipeline.jev import JevClient
    from jev_research_pipeline.qwen.prose import FIDELITY_FEEDBACK

    seen: list[str] = []
    qwen = fake_qwen("Jev の較正が崩れる [1]。", "一般の LLM で較正が崩れる [1]。")

    async def recording(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.content.decode())
        return await qwen(request)

    jev = JevClient(
        cassette(fake_jev({"unsupported_statement": 0.1, "exceeds_claims": 0.9})),
        api_key="replay",
    )
    rendering, judged = await rubric_ladder(
        jev=jev,
        model=qwen_model(MAX, cassette(recording), api_key="replay"),
        ctx=CTX,
        question=b.question(),
        report_id=b.report().id,
        claims=[b.claim().text],
        meter=GenerationMeter(),
        now=b.T0,
        check=None,  # the ladder's own logic; the self-check pass has its own test
    )
    assert rendering.rendering == "template"
    assert [d.policy for d in rendering.rubric] == ["rubric_report@fidelity_v1"] * 2
    assert any(j.bundle_sha256 == rubric_report.FIDELITY_ASK.sha256 for j in judged)
    if seen:  # synthesized: the rewrite request carries the fidelity feedback
        assert json.dumps(FIDELITY_FEEDBACK, ensure_ascii=False)[1:-1][:20] in seen[1]


async def test_rubric_ladder_template_when_both_drafts_fail(cassette: ClientFactory):
    from jev_research_pipeline.jev import JevClient

    jev = JevClient(cassette(fake_jev({"unsupported_statement": 0.9})), api_key="replay")
    rendering, _ = await rubric_ladder(
        jev=jev,
        model=qwen_model(MAX, cassette(fake_qwen("一稿。", "二稿。")), api_key="replay"),
        ctx=CTX,
        question=b.question(),
        report_id=b.report().id,
        claims=[b.claim().text],
        meter=GenerationMeter(),
        now=b.T0,
        check=None,  # the ladder's own logic; the self-check pass has its own test
    )
    assert (rendering.rendering, rendering.prose) == ("template", None)
    assert len(rendering.rubric) == 2


def test_build_report_maps_rendering_and_operations():
    from jev_research_pipeline.qwen import Rendering

    report = build_report(
        line=b.LINE_IRI,
        run_date=b.T0.date(),
        rendering=Rendering(rendering="rewritten", prose="本文", rubric=()),
        claims=(b.claim().id,),
        unjudged=(),
        partial=False,
        operations=b.report().operations,
    )
    assert (report.rendering, report.prose, report.id) == ("rewritten", "本文", b.report().id)


# --- review fixes (96b0d22) ------------------------------------------------------------------


def test_agreement_counts_one_judgment_per_labeled_pair():
    c1 = _claim(1)
    first = _rubric(c1, {"grounded": 0.0})
    later = _rubric(c1, {"grounded": 1.0}).model_copy(update={"judged_at": b.T0.replace(hour=9)})
    # Different state → a second Judgment for the same (claim, report); only the latest counts.
    later = later.model_copy(update={"id": later.id.replace(later.id[-4:], "ffff")})
    result = agreement([first, later], [_label(c1, "correct")])
    assert result["grounded"] == AxisAgreement(axis="grounded", n=1, agreed=1)


def test_agreement_ignores_judgments_from_other_bundle_wording():
    c1 = _claim(1)
    stale = _rubric(c1, {}).model_copy(update={"bundle_sha256": "c" * 64})
    assert agreement([stale], [_label(c1, "correct")])["grounded"].n == 0


def test_axis_meters_without_rubric_data_report_none():
    meters = axis_meters([], agreement([], []))
    assert all(m.mean_score is None and m.gold_agreement is None for m in meters)


async def test_rubric_ladder_returns_every_draft_judgment(cassette: ClientFactory):
    from jev_research_pipeline.jev import JevClient

    jev = JevClient(cassette(fake_jev({"unsupported_statement": 0.9})), api_key="replay")
    rendering, judgments = await rubric_ladder(
        jev=jev,
        model=qwen_model(MAX, cassette(fake_qwen("一稿。", "二稿。")), api_key="replay"),
        ctx=CTX,
        question=b.question(),
        report_id=b.report().id,
        claims=[b.claim().text],
        meter=GenerationMeter(),
        now=b.T0,
        check=None,  # the ladder's own logic; the self-check pass has its own test
    )
    assert rendering.rendering == "template"
    assert len({j.id for j in judgments}) == 2  # one per draft, both kept


async def test_the_self_check_pass_replaces_the_draft_and_sees_it(cassette: ClientFactory):
    """Draft, then the same model re-reads it (the check prompt, the draft in <draft>) and
    its text is the one the ladder evaluates."""
    seen: list[str] = []
    fake = fake_qwen("一稿 [1]。", "点検後 [1]。")

    async def recording(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.content.decode())
        return await fake(request)

    from jev_research_pipeline.jev import JevClient

    jev = JevClient(
        cassette(fake_jev({"unsupported_statement": 0.1, "exceeds_claims": 0.1})),
        api_key="replay",
    )
    rendering, _ = await rubric_ladder(
        jev=jev,
        model=qwen_model(MAX, cassette(recording), api_key="replay"),
        ctx=CTX,
        question=b.question(),
        report_id=b.report().id,
        claims=[b.claim().text],
        meter=GenerationMeter(),
        now=b.T0,
    )
    assert rendering.prose == "点検後 [1]。"
    if seen:  # synthesized: the second request is the check, carrying the first draft
        assert "<draft>" in seen[1] and "一稿" in seen[1]
