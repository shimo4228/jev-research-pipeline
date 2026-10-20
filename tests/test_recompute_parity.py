"""Re-applying today's rules to the store (the weekly review's path) gives what the run
decided. A Judgment read back through judged_of() lands, under question_screening.rule(),
on the outcome and score of the Decision that points to it, and under
question_prefilter.passing() on the questions the run passed its source for.

Why: a Decision is overwritten when its pair is judged again, so only the Judgments keep a
cohort's first verdicts — and a recount written beside the code drifts from it unseen.

The data is synthetic but goes the run's way: a JevClient over a fake Jev (MockTransport)
answers, the live result is decided by the module's own decision(), and the Judgments,
Decisions and sources are written to a store partition and read back from it.
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx2
from pydantic import BaseModel

from jev_research_pipeline.jev import (
    JevClient,
    JevFailure,
    Judged,
    decide,
    judged_of,
    question_prefilter,
    question_screening,
)
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.jev.core import Ask, JevState
from jev_research_pipeline.model import Decision, GraphNodeType, Judgment, Question, SourceItem
from jev_research_pipeline.store import GraphStore

from . import builders as b
from .fakes import Distribution, NoulValue, fake_jev

QS = question_screening
QP = question_prefilter
CTX = LineContext(line=b.line(), vocabulary=("agent memory",))
TEXT = "An abstract about agent memory that is long enough to be screened. " * 5

type Answers = Mapping[str, NoulValue | Distribution]
"""What fake_jev answers, per question name."""

OLD_SCREEN: Ask[QS.Answers] = Ask(
    function="question_screening",
    version="v2",
    output=QS.Answers,
    instructions=QS.ASK.instructions,
)
"""An earlier version of the screen: the store keeps its Judgments and Decisions too."""

TOP: Answers = {
    "on_topic": 0.97,
    "method_transferable": 0.97,
    "evidence_compatible": 0.97,
    "bridges_line": 0.97,
    "problem_overlap": (0.0, 0.0, 0.0, 1.0),
    "evidence_strength": (0.0, 0.0, 0.0, 1.0),
    "novelty_vs_evidence_set": (0.0, 0.0, 1.0),
}

UNSURE: Answers = {
    **TOP,
    "problem_overlap": (0.3, 0.3, 0.0, 0.4),
    "novelty_vs_evidence_set": (0.0, 1.0, 0.0),
}
"""Weighted 0.65: the rule accepts it, yet it routes to Review — problem_overlap has no
majority level (certainty 0.4 < 0.5)."""

SCREEN_CASES: tuple[Answers, ...] = (
    TOP,  # keep
    {**TOP, "on_topic": 0.1},  # a gate drops
    {**TOP, "evidence_compatible": 0.2},
    {**TOP, "on_topic": 0.49},  # just under a gate's cut: dropped
    {**TOP, "method_transferable": 0.3},  # on a gate's cut: it passes
    UNSURE,
    {**TOP, "problem_overlap": (0.3, 0.3, 0.0, 0.4)},  # 0.75: a clear keep
    {
        **TOP,
        "problem_overlap": (0.0, 0.0, 1.0, 0.0),
        "evidence_strength": (0.0, 1.0, 0.0, 0.0),
        "novelty_vs_evidence_set": (0.0, 1.0, 0.0),
    },  # 0.53: reject, inside the band
    {
        **TOP,
        "problem_overlap": (0.0, 1.0, 0.0, 0.0),
        "evidence_strength": (0.0, 1.0, 0.0, 0.0),
        "novelty_vs_evidence_set": (0.0, 1.0, 0.0),
    },  # well below the cut
)


def _dist(rng: random.Random, n: int) -> tuple[float, ...]:
    weights = [rng.random() for _ in range(n)]
    return tuple(w / sum(weights) for w in weights)


def _random_screen(rng: random.Random) -> Answers:
    return {
        "on_topic": rng.random(),
        "method_transferable": rng.random(),
        "evidence_compatible": rng.random(),
        "bridges_line": rng.random(),
        "problem_overlap": _dist(rng, 4),
        "evidence_strength": _dist(rng, 4),
        "novelty_vs_evidence_set": _dist(rng, 3),
    }


def _source(i: int) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url=f"https://arxiv.org/abs/2609.{i:05d}",
        title=f"Source {i}",
        text=TEXT,
        fetched_at=b.T0,
    )


def _slots(answers: Sequence[Answers]) -> Answers:
    """fake_jev overrides that answer slot sN of a batched request with answers[N]."""
    return {f"s{i}.{k}": v for i, a in enumerate(answers) for k, v in a.items()}


async def _ask[OutputT: BaseModel](
    ask: Ask[OutputT],
    items: list[tuple[tuple[str, ...], JevState]],
    answers: Answers,
    *,
    status: int = 200,
) -> list[Judged[OutputT] | JevFailure]:
    """One request through the client the run uses (several items = one batched request)."""
    transport = httpx2.MockTransport(fake_jev(answers, status=status))
    async with httpx2.AsyncClient(transport=transport) as http:
        jev = JevClient(http, api_key="fake")
        return await jev.judge_batch(ask, items, subject="source", now=b.T0)


@dataclass
class Run:
    """What the run stored, and what it knew live that the store does not keep."""

    nodes: list[GraphNodeType] = field(default_factory=list[GraphNodeType])
    live: dict[str, object] = field(default_factory=dict[str, object])
    """Per Judgment id: the live route (screen) or the live passing list (prefilter)."""

    def keep(self, *nodes: GraphNodeType) -> None:
        self.nodes.extend(nodes)

    def read_back(self, tmp_path: Path) -> dict[str, GraphNodeType]:
        partition = GraphStore(tmp_path).line("akc")
        partition.put(self.nodes)
        return partition.load()


# --- question_screening ---------------------------------------------------------------------


async def _screened(question: Question) -> Run:
    run = Run()
    rng = random.Random(20261020)
    singles = [*SCREEN_CASES, *(_random_screen(rng) for _ in range(30))]
    sources = [_source(i) for i in range(len(singles) + 4)]
    run.keep(question, *sources)

    def stored(
        results: Sequence[Judged[QS.Answers] | JevFailure], at: Sequence[SourceItem]
    ) -> None:
        for result, source in zip(results, at, strict=True):
            run.keep(QS.decision(result), QS.bridges_decision(result))
            if isinstance(result, Judged):
                run.keep(result.judgment)
                run.live[result.judgment.id] = QS.route(result, source=source)

    for answers, source in zip(singles, sources[: len(singles)], strict=True):
        stored(await _ask(QS.ASK, QS.items(CTX, [source], question, []), answers), [source])
    batch = sources[len(singles) : len(singles) + 3]  # one batched request of three
    slots = [UNSURE, _random_screen(rng), TOP]
    stored(await _ask(QS.ASK, QS.items(CTX, batch, question, []), _slots(slots)), batch)
    unjudged = sources[-1]
    stored(await _ask(QS.ASK, QS.items(CTX, [unjudged], question, []), {}, status=400), [unjudged])
    # The same pair as the first case under the earlier version: a Judgment and a Decision
    # of their own, which today's ask must not read back.
    (old,) = await _ask(OLD_SCREEN, QS.items(CTX, [sources[0]], question, []), TOP)
    assert isinstance(old, Judged)
    run.keep(old.judgment, decide(old, ask=OLD_SCREEN, thresholds=QS.THRESHOLDS, rule=QS.rule))
    return run


def _recomputable(
    nodes: Mapping[str, GraphNodeType],
) -> list[tuple[Decision, Judged[QS.Answers]]]:
    """Every judged screening Decision of today's ask and thresholds, with the Judgment it
    points to read back — the selection a recount of the store recomputes over."""
    policies = {QS.ASK.policy, QS.BATCH_ASK.policy}
    out: list[tuple[Decision, Judged[QS.Answers]]] = []
    for d in nodes.values():
        if not (
            isinstance(d, Decision)
            and d.function == "question_screening"
            and d.policy in policies
            and d.outcome != "unjudged"
            and d.thresholds == QS.THRESHOLDS
        ):
            continue
        judgment = nodes[d.judgments[0]]
        assert isinstance(judgment, Judgment)
        judged = judged_of(QS.ASK, judgment)
        assert judged is not None, d.policy
        out.append((d, judged))
    return out


async def test_the_screening_rule_recomputed_from_the_store_is_the_decision(tmp_path: Path):
    run = await _screened(b.question())
    nodes = run.read_back(tmp_path)
    pairs = _recomputable(nodes)
    # every judged pair of today's ask is compared, alone and batched; none slips through
    assert len(pairs) == len(run.live) == len(SCREEN_CASES) + 30 + 3
    assert {d.policy for d, _ in pairs} == {QS.ASK.policy, QS.BATCH_ASK.policy}
    assert {d.outcome for d, _ in pairs} == {"accept", "reject"}
    for d, judged in pairs:
        assert QS.rule(judged) == (d.outcome == "accept", d.score), d.id
    # the earlier version's Judgment is in the store, and today's ask does not read it
    old = [
        n
        for n in nodes.values()
        if isinstance(n, Judgment) and n.bundle_sha256 == OLD_SCREEN.sha256
    ]
    assert len(old) == 1
    assert judged_of(QS.ASK, old[0]) is None
    assert judged_of(OLD_SCREEN, old[0]) is not None


async def test_a_recomputed_keep_is_an_accept_but_not_every_accept_is_a_keep(tmp_path: Path):
    run = await _screened(b.question())
    nodes = run.read_back(tmp_path)
    routes: dict[str, str] = {}
    for d, judged in _recomputable(nodes):
        source = nodes[d.subjects[0]]
        assert isinstance(source, SourceItem)
        routes[d.id] = QS.route(judged, source=source)
        assert routes[d.id] == run.live[judged.judgment.id]  # the route the run saw live
    accepted = {d.id for d, _ in _recomputable(nodes) if d.outcome == "accept"}
    keep = {i for i, r in routes.items() if r == "keep"}
    assert keep
    assert keep <= accepted
    # The converse fails: a weighted score in [0.6, 0.7) at certainty < 0.5 is accepted by
    # the rule yet routed to Review, so route and Decision.outcome are different counts.
    assert {routes[i] for i in accepted - keep} == {"review"}


# --- question_prefilter ---------------------------------------------------------------------


def _questions(n: int) -> list[Question]:
    return [
        Question.new(
            line=b.LINE_IRI,
            slug=f"question-{i}",
            version=1,
            title=f"問い {i}",
            brief="記憶機構の違いが下流の精度をどれだけ動かすか。",
            opened_at=b.T0,
        )
        for i in range(n)
    ]


async def test_prefilter_passing_recomputed_from_the_store_is_what_the_run_passed(
    tmp_path: Path,
):
    run = Run()
    rng = random.Random(20261021)
    three, two = _questions(3), _questions(2)
    sources = [_source(i) for i in range(12)]
    run.keep(*three, *sources)

    async def asked(questions: list[Question], at: list[SourceItem], answers: Answers) -> None:
        n = len(questions)
        for result in await _ask(QP.ask(n), QP.items(CTX, at, questions), answers):
            run.keep(QP.decision(result, n))
            if isinstance(result, Judged):
                run.keep(result.judgment)
                run.live[result.judgment.id] = QP.passing(result, n)

    for source in sources[:8]:
        answers: Answers = {QP.field(i): rng.random() for i in range(3)}
        await asked(three, [source], answers)
    slots = [{QP.field(i): rng.random() for i in range(3)} for _ in range(3)]
    await asked(three, sources[8:11], _slots(slots))  # one batched request of three
    await asked(three, [sources[11]], {QP.field(i): 0.1 for i in range(3)})  # passes none
    # The same source on a day the line had two open questions: another bundle.
    await asked(two, [sources[0]], {QP.field(0): 0.9, QP.field(1): 0.2})

    nodes = run.read_back(tmp_path)
    decisions = {
        (d.subjects[0], d.bundle_sha256): d
        for d in nodes.values()
        if isinstance(d, Decision) and d.function == "question_prefilter"
    }
    judgments = [
        n for n in nodes.values() if isinstance(n, Judgment) and n.function == "question_prefilter"
    ]
    assert len(judgments) == len(run.live) == 13
    passed: list[list[int]] = []
    for j in judgments:
        n = len(j.answers)  # one q{i}_on_topic per open question that day
        judged = judged_of(QP.ask(n), j)
        assert judged is not None
        other = 2 if n == 3 else 3
        assert judged_of(QP.ask(other), j) is None  # another question count, another ask
        passing = QP.passing(judged, n)
        assert passing == run.live[j.id]
        d = decisions[(j.subjects[0], j.bundle_sha256)]
        assert (d.outcome == "accept", d.score) == (
            bool(passing),
            max(float(getattr(judged.output, QP.field(i))) for i in range(n)),
        )
        passed.append(passing)
    assert [] in passed and any(len(p) > 1 for p in passed)
