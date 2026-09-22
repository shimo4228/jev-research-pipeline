"""Minimal valid instances of every node kind, wired to each other by @id."""

from datetime import UTC, date, datetime

from jev_research_pipeline.model import (
    AxisMeter,
    Claim,
    Decision,
    GraphNodeType,
    Judgment,
    Label,
    Line,
    NoulAnswer,
    Operations,
    QueryCandidate,
    Report,
    RotationCursor,
    ScoreAnswer,
    SourceItem,
    StageRecord,
    Threshold,
    Unit,
)

LINE_IRI = "https://doi.org/10.5281/zenodo.19212119"
T0 = datetime(2026, 9, 22, 6, 0, tzinfo=UTC)
SOURCE_TEXT = "Agents need memory. Narrow questions beat one broad question."


def line() -> Line:
    return Line(
        id=LINE_IRI, slug="akc", name="Agent Knowledge Cycle", adapters=("arxiv", "hf_papers")
    )


def source() -> SourceItem:
    return SourceItem.new(
        line=LINE_IRI,
        adapter="arxiv",
        url="https://arxiv.org/abs/2609.00001",
        title="Narrow questions",
        text=SOURCE_TEXT,
        fetched_at=T0,
        published_at=date(2026, 9, 20),
    )


def unit() -> Unit:
    return Unit.cut(source(), start=20, end=len(SOURCE_TEXT), granularity="sentence")


def claim() -> Claim:
    return Claim.from_unit(unit(), line=LINE_IRI)


def query() -> QueryCandidate:
    return QueryCandidate.new(line=LINE_IRI, adapter="arxiv", text="narrow question decomposition")


def judgment() -> Judgment:
    return Judgment.new(
        function="claim_detection",
        subjects=(unit().id,),
        model="jev-1.13.0",
        state_sha256="a" * 64,
        bundle_sha256="b" * 64,
        answers=(
            NoulAnswer(key="states_checkable_claim", p_yes=0.91),
            NoulAnswer(key="relevant", p_yes=0.77),
        ),
        judged_at=T0,
    )


def decision() -> Decision:
    return Decision.new(
        function="claim_detection",
        subjects=(unit().id,),
        policy="claim_detection@v1",
        judgments=(judgment().id,),
        thresholds=(Threshold(name="states_checkable_claim", value=0.5),),
        outcome="accept",
        score=0.91,
    )


def report() -> Report:
    return Report.new(
        line=LINE_IRI,
        run_date=date(2026, 9, 22),
        rendering="prose",
        prose="本文",
        claims=(claim().id,),
        unjudged=(),
        partial=False,
        operations=Operations(
            jev_questions=13,
            generation_input_tokens=1200,
            generation_output_tokens=800,
            claude_calls=0,
            cost_usd=0.012,
            rubric=(AxisMeter(axis="grounded", mean_score=0.8, gold_agreement=None),),
            fill_rate_previous=None,
        ),
    )


def label() -> Label:
    return Label.new(claim=claim().id, report=report().id, verdict="correct", harvested_at=T0)


def score_judgment() -> Judgment:
    return Judgment.new(
        function="novelty",
        subjects=(claim().id, claim().id),
        model="jev-1.13.0",
        state_sha256="c" * 64,
        bundle_sha256="d" * 64,
        answers=(
            ScoreAnswer(
                key="relation",
                levels=("unrelated", "related_or_extends", "same_claim"),
                probabilities=(0.1, 0.3, 0.6),
            ),
        ),
        judged_at=T0,
    )


def cursor() -> RotationCursor:
    return RotationCursor.new(next_slug="akc", updated_at=T0)


def stage_record() -> StageRecord:
    return StageRecord.new(
        stage="claim_detection", input_sha256="e" * 64, outputs=(claim().id,), completed_at=T0
    )


def every_node_kind() -> list[GraphNodeType]:
    return [
        line(),
        query(),
        source(),
        unit(),
        claim(),
        judgment(),
        decision(),
        report(),
        label(),
        cursor(),
        stage_record(),
    ]
