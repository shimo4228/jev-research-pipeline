"""Step 8: rubric ladder wired to Report.rendering, and the rubric meters per axis."""

import json
from enum import IntEnum

import httpx2
import pytest

from jev_research_pipeline.generation import GenerationMeter
from jev_research_pipeline.jev import rubric_claim, rubric_report
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.jev.core import score_levels
from jev_research_pipeline.model import Claim, Judgment, ScoreAnswer, SourceItem, Unit
from jev_research_pipeline.quality import axis_meters, build_report, rubric_ladder

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_jev, fake_qwen, qwen_model

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


# --- meters ----------------------------------------------------------------------------------


def test_axis_meters_feed_operations():
    c1, c2 = _claim(1), _claim(2)
    meters = axis_meters([_rubric(c1, {"grounded": 0.5}), _rubric(c2, {"grounded": 1.0})])
    grounded = next(m for m in meters if m.axis == "grounded")
    assert grounded.mean_score == pytest.approx(0.75)
    assert {m.axis for m in meters} == set(rubric_claim.AXES)
    # The gold-agreement meter is retired: the field stays for old Reports, never filled.
    assert all(m.gold_agreement is None for m in meters)


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
        model=qwen_model(client),
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


async def test_claim_fidelity_is_recorded_but_sends_no_draft_back(cassette: ClientFactory):
    """claim_fidelity is a label, not a gate (author 2026-10-02): a paragraph Jev reads as
    going beyond its claims is recorded as a Judgment and the draft is published; the
    rubric_report decision alone accepts or rejects it."""
    from jev_research_pipeline.jev import JevClient

    jev = JevClient(
        cassette(fake_jev({"unsupported_statement": 0.1, "exceeds_claims": 0.9})),
        api_key="replay",
    )
    rendering, judged = await rubric_ladder(
        jev=jev,
        model=qwen_model(cassette(fake_qwen("一般の LLM で較正が崩れる [1]。"))),
        ctx=CTX,
        question=b.question(),
        report_id=b.report().id,
        claims=[b.claim().text],
        meter=GenerationMeter(),
        now=b.T0,
        check=None,  # the ladder's own logic; the self-check pass has its own test
    )
    assert rendering.rendering == "prose"
    assert [d.policy for d in rendering.rubric] == [rubric_report.ASK.policy]
    assert any(j.bundle_sha256 == rubric_report.FIDELITY_ASK.sha256 for j in judged)


async def test_a_study_name_line_is_not_a_paragraph_to_check(cassette: ClientFactory):
    """v10-v15 put each study under a bold name line of its own. Checked alone it cites
    nothing, so it was judged against every claim and could send a whole draft back
    (2026-10-01: "**Guard Models …**" at 0.83). Only the paragraphs under it are checked."""
    from jev_research_pipeline.jev import JevClient

    prose = "今日の研究 [1]。\n\n**Mnemon**\n\nMnemon は記録を判定する [1]。"

    async def jev_handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if "exceeds_claims" in body["questions"]:
            # the name line alone would be judged as going beyond the claims
            p = 0.9 if "**Mnemon**" in json.dumps(body, ensure_ascii=False) else 0.1
            return await fake_jev({"exceeds_claims": p})(request)
        return await fake_jev({"unsupported_statement": 0.1})(request)

    rendering, judged = await rubric_ladder(
        jev=JevClient(cassette(jev_handler), api_key="replay"),
        model=qwen_model(cassette(fake_qwen(prose))),
        ctx=CTX,
        question=b.question(),
        report_id=b.report().id,
        claims=[b.claim().text],
        meter=GenerationMeter(),
        now=b.T0,
        check=None,
    )
    assert rendering.rendering == "prose"
    fidelity = [j for j in judged if j.bundle_sha256 == rubric_report.FIDELITY_ASK.sha256]
    assert len(fidelity) == 2  # the lead and Mnemon's paragraph, not the name line


def test_a_paragraph_below_the_fidelity_bar_is_accepted():
    """0.7 (2026-10-01): at 0.6 the check templated 25 of 28 v15 drafts the bench judge
    passed, and its accepted drafts were no more faithful (design "Production check")."""
    assert rubric_report.FIDELITY_THRESHOLDS[0].value == 0.7


async def test_rubric_ladder_template_when_both_drafts_fail(cassette: ClientFactory):
    from jev_research_pipeline.jev import JevClient

    jev = JevClient(cassette(fake_jev({"unsupported_statement": 0.9})), api_key="replay")
    rendering, _ = await rubric_ladder(
        jev=jev,
        model=qwen_model(cassette(fake_qwen("一稿。", "二稿。"))),
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
    from jev_research_pipeline.generation import Rendering

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


def test_axis_meters_count_one_judgment_per_claim():
    c1 = _claim(1)
    first = _rubric(c1, {"grounded": 0.0})
    later = _rubric(c1, {"grounded": 1.0}).model_copy(update={"judged_at": b.T0.replace(hour=9)})
    # Different state → a second Judgment for the same (claim, report); only the latest counts.
    later = later.model_copy(update={"id": later.id.replace(later.id[-4:], "ffff")})
    grounded = next(m for m in axis_meters([first, later]) if m.axis == "grounded")
    assert grounded.mean_score == pytest.approx(1.0)


def test_axis_meters_ignore_judgments_from_other_bundle_wording():
    stale = _rubric(_claim(1), {}).model_copy(update={"bundle_sha256": "c" * 64})
    assert all(m.mean_score is None for m in axis_meters([stale]))


def test_axis_meters_without_rubric_data_report_none():
    meters = axis_meters([])
    assert all(m.mean_score is None and m.gold_agreement is None for m in meters)


async def test_rubric_ladder_returns_every_draft_judgment(cassette: ClientFactory):
    from jev_research_pipeline.jev import JevClient

    jev = JevClient(cassette(fake_jev({"unsupported_statement": 0.9})), api_key="replay")
    rendering, judgments = await rubric_ladder(
        jev=jev,
        model=qwen_model(cassette(fake_qwen("一稿。", "二稿。"))),
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
        model=qwen_model(cassette(recording)),
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


async def test_an_english_ladder_drafts_and_checks_in_english(cassette: ClientFactory):
    """lang=en: the English prompt drafts, the English self-check re-reads (not ja's check9),
    and the rubric asks are the English ones."""
    seen: list[str] = []
    fake = fake_qwen("Draft [1].", "Checked [1].")

    async def recording(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.content.decode())
        return await fake(request)

    from jev_research_pipeline.jev import JevClient

    jev = JevClient(
        cassette(fake_jev({"unsupported_statement": 0.1, "exceeds_claims": 0.1})),
        api_key="replay",
    )
    rendering, judged = await rubric_ladder(
        jev=jev,
        model=qwen_model(cassette(recording)),
        ctx=CTX,
        question=b.question(),
        report_id=b.report().id,
        claims=[b.claim().text],
        meter=GenerationMeter(),
        now=b.T0,
        lang="en",
    )
    assert rendering.prose == "Checked [1]."
    assert {j.bundle_sha256 for j in judged} == {
        rubric_report.ASKS["en"].sha256,
        rubric_report.FIDELITY_ASKS["en"].sha256,
    }
    if seen:  # synthesized: the draft and the check went out with the English prompts
        assert "You explain the research" in seen[0]
        assert "You are a copy editor" in seen[1]
