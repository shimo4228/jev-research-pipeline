"""The question-centric wiring the other files do not cover: screening's routing table,
canary detection, and what one question-day tick propagates to."""

from datetime import date
from pathlib import Path

import pytest

from jev_research_pipeline.jev import JevFailure, question_screening
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import Label, Question, QuestionLog, SourceItem
from jev_research_pipeline.pipeline.run import canary_lines
from jev_research_pipeline.report import harvest_note, qday_mark, write_note

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_jev

CTX = LineContext(line=b.line(), vocabulary=("agent memory",))
LONG = "An abstract about agent memory that is long enough to be screened. " * 5


def _source(text: str = LONG) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url="https://arxiv.org/abs/2609.01234",
        title="Narrow Questions Beat Broad Prompts",
        text=text,
        fetched_at=b.T0,
    )


def _jev(cassette: ClientFactory, answers: dict[str, object]) -> object:
    from jev_research_pipeline.jev import JevClient

    return JevClient(cassette(fake_jev(answers)), api_key="replay")  # pyright: ignore[reportArgumentType]


KEEP: dict[str, object] = {
    "on_topic": 0.97,
    "method_transferable": 0.97,
    "evidence_compatible": 0.97,
    "bridges_line": 0.97,
    "problem_overlap": (0.0, 0.0, 0.0, 1.0),
    "evidence_strength": (0.0, 0.0, 0.0, 1.0),
    "novelty_vs_evidence_set": (0.0, 0.0, 1.0),
}


@pytest.mark.parametrize(
    ("overrides", "route"),
    [
        ({}, "keep"),
        ({"on_topic": 0.1}, "drop"),  # a hard gate can only drop
        ({"method_transferable": 0.2}, "drop"),
        # the score clears the cut (0.65) but not by the band, and problem_overlap has no
        # majority level
        (
            {"problem_overlap": (0.3, 0.3, 0.0, 0.4), "novelty_vs_evidence_set": (0.0, 1.0, 0.0)},
            "review",
        ),
        # far above the cut (0.75): a clear call, whatever the split between high levels
        ({"problem_overlap": (0.3, 0.3, 0.0, 0.4)}, "keep"),
        (
            {
                "problem_overlap": (0.0, 1.0, 0.0, 0.0),
                "evidence_strength": (0.0, 1.0, 0.0, 0.0),
                "novelty_vs_evidence_set": (0.0, 1.0, 0.0),
            },
            "drop",  # weighted score well below the cut
        ),
        (
            {
                "problem_overlap": (0.0, 0.0, 1.0, 0.0),
                "evidence_strength": (0.0, 1.0, 0.0, 0.0),
                "novelty_vs_evidence_set": (0.0, 1.0, 0.0),
            },
            "review",  # 0.53: inside the band below the 0.6 cut
        ),
    ],
    ids=["keep", "off_topic", "method", "unsure", "clear", "weak", "borderline"],
)
async def test_gates_then_scores_then_code_routes(
    cassette: ClientFactory, overrides: dict[str, object], route: str
):
    jev = _jev(cassette, {**KEEP, **overrides})
    source = _source()
    result = await question_screening.judge(
        jev,  # pyright: ignore[reportArgumentType]
        CTX,
        source,
        b.question(),
        ["既知の claim"],
        now=b.T0,
    )
    assert question_screening.route(result, source=source) == route


def test_a_source_without_an_abstract_is_incomplete_before_anything_is_asked():
    short = _source("Title only.")
    failure = JevFailure(
        function="question_screening",
        subjects=(short.id, b.question().id),
        bundle_sha256=question_screening.ASK.sha256,
        reason="timeout",
        detail="",
    )
    assert question_screening.route(failure, source=short) == "incomplete"


def test_a_jev_failure_goes_to_unjudged_not_review():
    """Review is for judged borderlines; the first pilot routed every Jev failure there."""
    source = _source()
    failure = JevFailure(
        function="question_screening",
        subjects=(source.id, b.question().id),
        bundle_sha256=question_screening.ASK.sha256,
        reason="timeout",
        detail="",
    )
    assert question_screening.route(failure, source=source) == "unjudged"


def test_a_canary_that_does_not_survive_screening_is_reported():
    question = b.question()  # its canary is arxiv.org/abs/2609.01234
    assert canary_lines([question], {question.id: [_source()]}) == []
    assert canary_lines([question], {question.id: []}) == [
        f"canary 落下: {question.slug} / https://arxiv.org/abs/2609.01234"
    ]


def test_a_question_day_tick_propagates_to_what_it_cited(tmp_path: Path):
    claim, source = b.claim(), b.source()
    log = QuestionLog.new(
        question=b.question().id,
        report=b.report().id,
        run_date=date(2026, 9, 22),
        movement="answer_changed",
        text="今日の変化。",
        claims=(claim.id,),
        sources=(source.id,),
        logged_at=b.T0,
    )
    mark = qday_mark(b.question().id, log.run_date)
    note = write_note(
        tmp_path,
        "akc",
        log.run_date,
        f'---\njrp_report: "{b.report().id}"\n---\n- [x] 読む価値があった <!-- {mark} -->\n',
    )
    result = harvest_note(note, now=b.T0, logs={mark.removeprefix("jrp:qday:"): log})
    subjects = {(lb.subject, lb.provenance) for lb in result.labels}
    assert subjects == {
        (log.id, "question_day"),
        (claim.id, "question_day"),
        (source.id, "question_day"),
    }
    assert all(lb.verdict == "correct" for lb in result.labels)


def test_an_untouched_question_day_withdraws_its_labels(tmp_path: Path):
    claim = b.claim()
    log = QuestionLog.new(
        question=b.question().id,
        report=b.report().id,
        run_date=date(2026, 9, 22),
        movement="none",
        text="",
        claims=(claim.id,),
        logged_at=b.T0,
    )
    mark = qday_mark(b.question().id, log.run_date)
    note = write_note(
        tmp_path,
        "akc",
        log.run_date,
        f'---\njrp_report: "{b.report().id}"\n---\n- [ ] 読む価値があった <!-- {mark} -->\n',
    )
    result = harvest_note(note, now=b.T0, logs={mark.removeprefix("jrp:qday:"): log})
    assert result.labels == ()
    assert set(result.cleared) == {
        Label.id_for(log.id, b.report().id),
        Label.id_for(claim.id, b.report().id),
    }


def test_a_ticked_proposal_comes_back_as_adopted(tmp_path: Path):
    note = write_note(
        tmp_path,
        "akc",
        date(2026, 9, 22),
        f'---\njrp_report: "{b.report().id}"\n---\n'
        "- [x] 新しい問い <!-- jrp:question:vantage-point -->\n",
    )
    result = harvest_note(note, now=b.T0)
    assert result.adopted == ("vantage-point",)
    assert result.labels == ()  # a proposal is adopted, not labeled


def test_adopting_writes_the_question_into_the_authors_file(tmp_path: Path):
    from jev_research_pipeline.pipeline.run import adopt_candidates
    from jev_research_pipeline.questions import parse_questions, questions_path

    env = {"JRP_QUESTIONS_DIR": str(tmp_path / "questions")}
    proposal = Question.new(
        line=b.LINE_IRI,
        slug="vantage-point",
        version=1,
        title="視点を変えたときに何が見えるか",
        opened_at=b.T0,
    )
    lines = adopt_candidates(env, "akc", ("vantage-point", "unknown"), {"vantage-point": proposal})
    assert lines == [f"問いを採用: {proposal.title}"]
    text = questions_path(env, "akc").read_text(encoding="utf-8")
    assert [q.slug for q in parse_questions(text, line=b.LINE_IRI, opened_at=b.T0)] == [
        "vantage-point"
    ]
