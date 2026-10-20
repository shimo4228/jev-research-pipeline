"""Minimal valid instances of every node kind, wired to each other by @id."""

from datetime import UTC, date, datetime, timedelta

from jev_research_pipeline.model import (
    AxisMeter,
    Claim,
    Decision,
    GraphNodeType,
    Judgment,
    Label,
    Line,
    LineRecord,
    NoulAnswer,
    Operations,
    QueryCandidate,
    Question,
    QuestionLog,
    Report,
    RotationCursor,
    RunRecord,
    ScoreAnswer,
    SectionRendering,
    Sighting,
    SourceItem,
    StageRecord,
    Threshold,
    Unit,
    UsedMark,
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
        subjects=(unit().id, question().id),
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
        subjects=(unit().id, question().id),
        policy="claim_detection@v2",
        bundle_sha256="b" * 64,
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
            jev_input_tokens=1300,
            jev_output_tokens=65,
            generation_input_tokens=1200,
            generation_output_tokens=800,
            writer_calls=2,
            cost_usd=0.012,
            rubric=(AxisMeter(axis="grounded", mean_score=0.8, gold_agreement=None),),
            fill_rate_previous=None,
        ),
    )


def question(version: int = 1) -> Question:
    return Question.new(
        line=LINE_IRI,
        slug="agent-memory",
        version=version,
        title="エージェントの記憶は何で決まるのか",
        brief="記憶機構の違いが下流の精度をどれだけ動かすか。",
        opened_at=T0,
        canary_papers=("https://arxiv.org/abs/2609.01234",),
        evidence=(claim().id,),
    )


def question_log() -> QuestionLog:
    return QuestionLog.new(
        question=question().id,
        report=report().id,
        run_date=T0.date(),
        movement="new_evidence_same_answer",
        text="今日の変化。",
        claims=(claim().id,),
        sources=(source().id,),
        logged_at=T0,
    )


def label() -> Label:
    return Label.new(
        subject=claim().id,
        report=report().id,
        verdict="correct",
        provenance="claim",
        harvested_at=T0,
    )


def sighting() -> Sighting:
    return Sighting.new(key="arxiv:2610.21411", first_seen=T0.date(), place="vault", baseline=False)


def used_mark() -> UsedMark:
    return UsedMark.new(
        source=source().id,
        report=report().id,
        surfaced_on=T0.date(),
        observed_from=T0.date(),
        verdict="used",
        seen_on=T0.date(),
    )


def score_judgment() -> Judgment:
    return Judgment.new(
        function="novelty",
        subjects=(claim().id, question().id),
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


def run_record() -> RunRecord:
    return RunRecord.new(
        started_at=T0,
        finished_at=T0 + timedelta(minutes=20),
        lines=("akc", "edge"),
        reasons=("edge: raised (RuntimeError: boom)",),
        notify_configured=True,
        line_records=(
            LineRecord(
                slug="akc",
                report=report().id,
                questions=(question().id,),
                review=(source().id,),
                renderings=(SectionRendering(question=question().id, rendering="rewritten"),),
                invalid_citations=1,
                claim_count=1,
            ),
        ),
    )


def every_node_kind() -> list[GraphNodeType]:
    return [
        line(),
        question(),
        question_log(),
        query(),
        source(),
        unit(),
        claim(),
        judgment(),
        decision(),
        report(),
        label(),
        sighting(),
        used_mark(),
        cursor(),
        stage_record(),
        run_record(),
    ]
