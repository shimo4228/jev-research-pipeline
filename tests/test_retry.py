"""retry_sources: a source an earlier run left unjudged goes through the run again, until a
Decision in today's form answers it or RETRY_DAYS pass since its fetch."""

from datetime import timedelta

from jev_research_pipeline.jev import question_screening, relevance_triage
from jev_research_pipeline.model import Decision, GraphNodeType, SourceItem
from jev_research_pipeline.pipeline.run import RETRY_MAX, retry_sources, today_bundles

from . import builders as b

NOW = b.T0 + timedelta(days=20)
QUESTION = b.question()
OLD_SCREEN = "0" * 64
"""The bundle of an earlier screening wording: not a form today's run asks."""


def _source(i: int, *, age_days: float) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="feed",
        url=f"https://example.org/post/{i}",
        title=f"Post {i}",
        text="A post. " * 30,
        fetched_at=NOW - timedelta(days=age_days),
    )


def _decision(
    function: str, subjects: tuple[str, ...], bundle: str, *, judged: bool = False
) -> Decision:
    return Decision.new(
        function=function,  # pyright: ignore[reportArgumentType]
        subjects=subjects,
        policy=f"{function}@v",
        bundle_sha256=bundle,
        judgments=(b.judgment().id,) if judged else (),
        thresholds=(),
        outcome="accept" if judged else "unjudged",
        score=0.9 if judged else None,
    )


def _retried(nodes: list[GraphNodeType], *, today: tuple[str, ...] = ()) -> list[str]:
    return [
        s.id
        for s in retry_sources(
            {n.id: n for n in nodes},
            open_questions={QUESTION.id},
            bundles=today_bundles(1),
            today=today,
            now=NOW,
        )
    ]


def test_an_unjudged_source_is_retried_until_a_decision_answers_it():
    s = _source(0, age_days=3)
    triage = relevance_triage.ASK.batched("source").sha256
    unjudged = _decision("relevance_triage", (s.id,), triage)
    assert _retried([s, unjudged]) == [s.id]
    # the judged retry has the same @id and replaces the unjudged Decision in the store
    answered = _decision("relevance_triage", (s.id,), triage, judged=True)
    assert answered.id == unjudged.id
    assert _retried([s, answered]) == []


def test_a_rewording_leaves_no_orphan():
    s = _source(0, age_days=3)
    pair = (s.id, QUESTION.id)
    old = _decision("question_screening", pair, OLD_SCREEN)
    assert _retried([s, old]) == [s.id]  # no answer in today's form yet
    today = _decision("question_screening", pair, question_screening.BATCH_ASK.sha256, judged=True)
    assert today.id != old.id
    assert _retried([s, old, today]) == []  # the old wording's unjudged stays, unretried


def test_what_is_not_retried():
    fresh, stale, fetched_today, closed = (
        _source(i, age_days=a) for i, a in enumerate((2, 15, 0, 2))
    )
    bundle = question_screening.BATCH_ASK.sha256
    nodes: list[GraphNodeType] = [
        fresh,
        stale,
        fetched_today,
        closed,
        _decision("question_screening", (fresh.id, QUESTION.id), bundle),
        _decision("question_screening", (stale.id, QUESTION.id), bundle),
        _decision("question_screening", (fetched_today.id, QUESTION.id), bundle),
        # a question no longer open: an earlier version of the same one
        _decision("question_screening", (closed.id, b.question(version=2).id), bundle),
        # a function after the note's sources are settled is not retried here
        _decision("claim_detection", (b.unit().id, QUESTION.id), bundle),
    ]
    assert _retried(nodes, today=(fetched_today.id,)) == [fresh.id]


def test_oldest_first_and_at_most_retry_max():
    sources = [_source(i, age_days=1 + i * 0.1) for i in range(RETRY_MAX + 5)]
    bundle = relevance_triage.ASK.batched("source").sha256
    nodes: list[GraphNodeType] = [
        *sources,
        *(_decision("relevance_triage", (s.id,), bundle) for s in sources),
    ]
    got = _retried(nodes)
    assert len(got) == RETRY_MAX
    assert got[0] == sources[-1].id  # the oldest first
    assert sources[0].id not in got  # the newest wait for the next run
