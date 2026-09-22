"""Per-type round-trip and invariant tests. Every invariant here is named in a model comment."""

from collections.abc import Callable
from datetime import datetime

import pytest
from pydantic import BaseModel, ValidationError

from jev_research_pipeline.model import (
    AxisMeter,
    ChoiceAnswer,
    Claim,
    Decision,
    Judgment,
    Label,
    Line,
    NoulAnswer,
    Operations,
    Report,
    RotationCursor,
    ScoreAnswer,
    SourceItem,
    StageRecord,
    StoreNode,
    Unit,
    content_id,
    kind_of,
)

from . import builders as b


def _round_trip[M: BaseModel](model: M) -> M:
    return type(model).model_validate_json(model.model_dump_json(by_alias=True))


@pytest.mark.parametrize("node", b.every_node_kind(), ids=lambda n: type(n).__name__)
def test_round_trip(node: BaseModel):
    assert _round_trip(node) == node


def test_round_trip_score_and_choice_answers():
    j = b.score_judgment()
    assert _round_trip(j) == j
    c = ChoiceAnswer(
        key="support",
        options=("supports", "contradicts", "says_nothing"),
        probabilities=(0.7, 0.1, 0.2),
    )
    assert _round_trip(c) == c


@pytest.mark.parametrize("node", b.every_node_kind(), ids=lambda n: type(n).__name__)
def test_nodes_are_frozen(node: BaseModel):
    with pytest.raises(ValidationError):
        node.id = "https://example.org/x"  # pyright: ignore[reportAttributeAccessIssue]


def test_unknown_fields_are_rejected():
    raw = b.claim().model_dump(by_alias=True)
    raw["paraphrase"] = "x"
    with pytest.raises(ValidationError):
        Claim.model_validate(raw)


# --- store @id is a function of content (idempotency) -------------------------------


@pytest.mark.parametrize(
    "node",
    [n for n in b.every_node_kind() if not isinstance(n, Line)],
    ids=lambda n: type(n).__name__,
)
def test_store_id_mismatch_is_rejected(node: BaseModel):
    raw = node.model_dump(by_alias=True)
    raw["@id"] = content_id(kind_of(raw["@id"]) or "x", "tampered")
    with pytest.raises(ValidationError, match="@id"):
        type(node).model_validate(raw)


def test_same_content_same_id():
    assert b.source().id == b.source().id
    assert b.claim().id == b.claim().id


# --- Line -----------------------------------------------------------------------------


def test_line_rejects_store_namespace_id():
    with pytest.raises(ValidationError, match="line graph"):
        Line(id=content_id("line", "x"), slug="akc", name="AKC", adapters=("arxiv",))


@pytest.mark.parametrize("adapters", [(), ("arxiv", "arxiv")])
def test_line_adapters_nonempty_unique(adapters: tuple[str, ...]):
    with pytest.raises(ValidationError):
        Line(id=b.LINE_IRI, slug="akc", name="AKC", adapters=adapters)  # pyright: ignore[reportArgumentType]


def test_line_rejects_x_adapter():
    # Non-goal in v1: X adapter.
    with pytest.raises(ValidationError):
        Line(id=b.LINE_IRI, slug="akc", name="AKC", adapters=("x",))  # pyright: ignore[reportArgumentType]


def test_line_slug_is_kebab():
    with pytest.raises(ValidationError):
        Line(id=b.LINE_IRI, slug="AKC Line", name="AKC", adapters=("arxiv",))


# --- SourceItem -----------------------------------------------------------------------


def test_source_content_hash_matches_text():
    raw = b.source().model_dump(by_alias=True)
    raw["text"] = raw["text"] + " edited"
    with pytest.raises(ValidationError, match="content_sha256"):
        SourceItem.model_validate(raw)


def test_source_requires_aware_datetime():
    with pytest.raises(ValidationError):
        SourceItem.new(
            line=b.LINE_IRI,
            adapter="arxiv",
            url="https://arxiv.org/abs/1",
            title="t",
            text="x",
            fetched_at=datetime(2026, 9, 22),  # naive on purpose
        )


# --- Unit: verbatim span of its source ------------------------------------------------


def test_unit_is_verbatim_slice():
    u = b.unit()
    assert u.text == b.SOURCE_TEXT[u.start : u.end]
    assert u.source == b.source().id
    assert u.source_sha256 == b.source().content_sha256


def test_unit_matches_source():
    assert b.unit().matches(b.source())


@pytest.mark.parametrize(("start", "end"), [(5, 5), (-1, 3), (0, 999), (10, 3)])
def test_unit_cut_rejects_bad_span(start: int, end: int):
    with pytest.raises(ValueError):
        Unit.cut(b.source(), start=start, end=end, granularity="sentence")


def test_unit_rejects_blank_span():
    src = SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url="https://arxiv.org/abs/2",
        title="t",
        text="a   b",
        fetched_at=b.T0,
    )
    with pytest.raises(ValueError):
        Unit.cut(src, start=1, end=4, granularity="sentence")


def test_unit_text_length_must_equal_span():
    raw = b.unit().model_dump(by_alias=True)
    raw["end"] = raw["end"] - 1
    raw["@id"] = content_id(
        "unit", raw["source"], raw["source_sha256"], str(raw["start"]), str(raw["end"])
    )
    with pytest.raises(ValidationError, match="span"):
        Unit.model_validate(raw)


# --- Claim: claim = unit verbatim -----------------------------------------------------


def test_claim_is_unit_verbatim():
    c = b.claim()
    assert c.text == b.unit().text
    assert c.unit == b.unit().id


def test_claim_matches_unit():
    assert b.claim().matches(b.unit())
    other = Unit.cut(b.source(), start=0, end=19, granularity="sentence")
    assert not b.claim().matches(other)


def test_claim_unit_must_be_unit_kind():
    with pytest.raises(ValidationError, match="unit"):
        Claim(
            id=content_id("claim", b.source().id),
            line=b.LINE_IRI,
            unit=b.source().id,
            text="x",
        )


# --- Judgment: raw probabilities per Jev function -------------------------------------


@pytest.mark.parametrize("p", [-0.01, 1.01])
def test_noul_probability_bounds(p: float):
    with pytest.raises(ValidationError):
        NoulAnswer(key="relevant", p_yes=p)


def test_score_distribution_must_sum_to_one():
    with pytest.raises(ValidationError, match="sum"):
        ScoreAnswer(key="k", levels=("a", "b"), probabilities=(0.2, 0.2))


def test_score_levels_and_probabilities_align():
    with pytest.raises(ValidationError, match="align"):
        ScoreAnswer(key="k", levels=("a", "b", "c"), probabilities=(0.5, 0.5))


def test_score_needs_two_unique_levels():
    with pytest.raises(ValidationError):
        ScoreAnswer(key="k", levels=("a",), probabilities=(1.0,))
    with pytest.raises(ValidationError):
        ScoreAnswer(key="k", levels=("a", "a"), probabilities=(0.5, 0.5))


def test_score_expected_position():
    s = ScoreAnswer(key="k", levels=("lo", "mid", "hi"), probabilities=(0.0, 0.5, 0.5))
    assert s.expected_position == pytest.approx(0.75)


def test_choice_argmax():
    c = ChoiceAnswer(key="k", options=("a", "b"), probabilities=(0.3, 0.7))
    assert c.argmax == "b"


def test_answer_keys_are_snake_case():
    with pytest.raises(ValidationError):
        NoulAnswer(key="Contains Evidence", p_yes=0.5)


def test_judgment_answer_keys_unique():
    with pytest.raises(ValidationError, match="unique"):
        Judgment.new(
            function="claim_detection",
            subjects=(b.unit().id,),
            model="jev-1.13.0",
            state_sha256="a" * 64,
            bundle_sha256="b" * 64,
            answers=(NoulAnswer(key="relevant", p_yes=0.1), NoulAnswer(key="relevant", p_yes=0.2)),
            judged_at=b.T0,
        )


def test_judgment_needs_answers():
    with pytest.raises(ValidationError):
        Judgment.new(
            function="claim_detection",
            subjects=(b.unit().id,),
            model="jev-1.13.0",
            state_sha256="a" * 64,
            bundle_sha256="b" * 64,
            answers=(),
            judged_at=b.T0,
        )


@pytest.mark.parametrize(
    ("function", "subjects"),
    [
        ("claim_detection", lambda: (b.claim().id,)),  # wants a unit
        ("novelty", lambda: (b.claim().id,)),  # wants a pair
        ("source_support", lambda: (b.source().id, b.claim().id)),  # order: claim, source
        ("relevance_triage", lambda: (b.LINE_IRI,)),  # external IRI is never a subject
    ],
)
def test_judgment_subject_kinds_per_function(
    function: str, subjects: Callable[[], tuple[str, ...]]
):
    with pytest.raises(ValidationError, match="subjects"):
        Judgment.new(
            function=function,  # pyright: ignore[reportArgumentType]
            subjects=subjects(),
            model="jev-1.13.0",
            state_sha256="a" * 64,
            bundle_sha256="b" * 64,
            answers=(NoulAnswer(key="relevant", p_yes=0.5),),
            judged_at=b.T0,
        )


def test_judgment_model_is_pinned_version():
    # Aliases drift and have no deprecation policy — only exact versions are recorded.
    with pytest.raises(ValidationError):
        Judgment.new(
            function="claim_detection",
            subjects=(b.unit().id,),
            model="jev-latest",
            state_sha256="a" * 64,
            bundle_sha256="b" * 64,
            answers=(NoulAnswer(key="relevant", p_yes=0.5),),
            judged_at=b.T0,
        )


def test_judgment_answer_lookup():
    j = b.judgment()
    assert j.answer("relevant") == NoulAnswer(key="relevant", p_yes=0.77)
    with pytest.raises(KeyError):
        j.answer("missing")


# --- Decision: unjudged is never fail-open --------------------------------------------


def test_unjudged_has_no_judgments_and_no_score():
    d = Decision.new(
        function="claim_detection",
        subjects=(b.unit().id,),
        policy="claim_detection@v1",
        judgments=(),
        thresholds=(),
        outcome="unjudged",
        score=None,
    )
    assert d.outcome == "unjudged"
    with pytest.raises(ValidationError, match="unjudged"):
        Decision.new(
            function="claim_detection",
            subjects=(b.unit().id,),
            policy="claim_detection@v1",
            judgments=(b.judgment().id,),
            thresholds=(),
            outcome="unjudged",
            score=None,
        )


def test_judged_decision_needs_judgment_and_score():
    with pytest.raises(ValidationError, match="judgment"):
        Decision.new(
            function="claim_detection",
            subjects=(b.unit().id,),
            policy="claim_detection@v1",
            judgments=(),
            thresholds=(),
            outcome="accept",
            score=0.9,
        )
    with pytest.raises(ValidationError, match="score"):
        Decision.new(
            function="claim_detection",
            subjects=(b.unit().id,),
            policy="claim_detection@v1",
            judgments=(b.judgment().id,),
            thresholds=(),
            outcome="reject",
            score=None,
        )


def test_decision_judgments_must_be_judgment_iris():
    with pytest.raises(ValidationError, match="judgments"):
        Decision.new(
            function="claim_detection",
            subjects=(b.unit().id,),
            policy="claim_detection@v1",
            judgments=(b.claim().id,),
            thresholds=(),
            outcome="accept",
            score=0.9,
        )


def test_decision_threshold_names_unique():
    with pytest.raises(ValidationError, match="unique"):
        Decision.model_validate(
            b.decision().model_dump(by_alias=True)
            | {"thresholds": [{"name": "a", "value": 0.1}, {"name": "a", "value": 0.2}]}
        )


# --- Label: gold = the author's tick ---------------------------------------------------


def test_label_kinds():
    with pytest.raises(ValidationError, match="claim"):
        Label.new(claim=b.unit().id, report=b.report().id, verdict="correct", harvested_at=b.T0)
    with pytest.raises(ValidationError, match="report"):
        Label.new(claim=b.claim().id, report=b.claim().id, verdict="correct", harvested_at=b.T0)


def test_label_verdict_is_binary():
    with pytest.raises(ValidationError):
        Label.new(claim=b.claim().id, report=b.report().id, verdict="maybe", harvested_at=b.T0)  # pyright: ignore[reportArgumentType]


# --- Report ----------------------------------------------------------------------------


def _report(**overrides: object) -> Report:
    raw = b.report().model_dump(by_alias=True) | overrides
    return Report.model_validate(raw)


def test_template_rendering_iff_no_prose():
    with pytest.raises(ValidationError, match="template"):
        _report(rendering="template")
    with pytest.raises(ValidationError, match="template"):
        _report(rendering="prose", prose=None)
    assert _report(rendering="template", prose=None).prose is None


def test_report_claims_unique_and_claim_kind():
    with pytest.raises(ValidationError, match="unique"):
        _report(claims=[b.claim().id, b.claim().id])
    with pytest.raises(ValidationError, match="claims"):
        _report(claims=[b.unit().id])


def test_unjudged_disjoint_from_claims():
    with pytest.raises(ValidationError, match="unjudged"):
        _report(unjudged=[b.claim().id])


def test_claude_calls_must_be_zero():
    # Non-goal: Claude at runtime. The meter exists to prove it stays 0.
    ops = b.report().operations.model_dump() | {"claude_calls": 1}
    with pytest.raises(ValidationError):
        Operations.model_validate(ops)


def test_rubric_axes_unique():
    ops = b.report().operations.model_dump()
    ops["rubric"] = [
        {"axis": "grounded", "mean_score": 0.5, "gold_agreement": None},
        {"axis": "grounded", "mean_score": 0.6, "gold_agreement": None},
    ]
    with pytest.raises(ValidationError, match="unique"):
        Operations.model_validate(ops)


def test_axis_meter_bounds():
    with pytest.raises(ValidationError):
        AxisMeter(axis="novel", mean_score=1.5, gold_agreement=None)


def test_report_id_is_one_per_line_per_day():
    r = b.report()
    assert r.id == content_id("report", b.LINE_IRI, "2026-09-22")


@pytest.mark.parametrize(
    "node",
    [n for n in b.every_node_kind() if not isinstance(n, Line)],
    ids=lambda n: type(n).__name__,
)
def test_id_kind_segment_matches_class_kind(node: StoreNode):
    # SUBJECT_KINDS and every kind_of() check rely on this binding.
    assert kind_of(node.id) == type(node).KIND


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_floats_are_rejected(bad: float):
    with pytest.raises(ValidationError):
        Decision.model_validate(b.decision().model_dump(by_alias=True) | {"score": bad})
    with pytest.raises(ValidationError):
        Operations.model_validate(b.report().operations.model_dump() | {"cost_usd": bad})


# --- RotationCursor / StageRecord (pipeline state kept in the store) ------------------


def test_cursor_is_a_singleton_id():
    assert b.cursor().id == RotationCursor.new(next_slug="other", updated_at=b.T0).id


def test_cursor_next_slug_is_kebab_or_none():
    assert RotationCursor.new(next_slug=None, updated_at=b.T0).next_slug is None
    with pytest.raises(ValidationError):
        RotationCursor.new(next_slug="Not A Slug", updated_at=b.T0)


def test_stage_record_id_is_stage_and_input_hash():
    r = b.stage_record()
    assert (
        r.id
        == StageRecord.new(
            stage="claim_detection", input_sha256="e" * 64, outputs=(), completed_at=b.T0
        ).id
    )


def test_stage_record_outputs_are_unique_store_iris():
    with pytest.raises(ValidationError, match="outputs"):
        StageRecord.new(stage="s", input_sha256="e" * 64, outputs=(b.LINE_IRI,), completed_at=b.T0)
    with pytest.raises(ValidationError, match="unique"):
        StageRecord.new(
            stage="s",
            input_sha256="e" * 64,
            outputs=(b.claim().id, b.claim().id),
            completed_at=b.T0,
        )
