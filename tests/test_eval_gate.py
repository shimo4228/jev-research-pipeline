"""The S and X gate eval (evals/): freeze a set from a store, recompute the baseline and a
candidate from the stored Judgments, label with Claude through httpx2.MockTransport, ask Jev
again through a fake Jev, and the author's blind check. Never the real APIs.

The store is one line, akc, with two open questions (q-a, q-b) over two days:
- S on 11-02: s1 keeps for both questions; s2 sits at weighted 0.58 for q-a (review under
  today's keep 0.6, keep under 0.55); s3 fails q-a's on_topic gate; s4 the prefilter drops;
  s5's triage rejects it (no evidence); s6 passes triage and trust and was never screened
  (prefiltered on 11-03, a day with no RunRecord, so its question order is read from the
  questions file through the state hash).
- X: 11-02's note shows s1's two claims for q-a. 11-03's pool for q-a holds s1's third
  claim (score 0.95) and six claims of four new papers (s7 x2, s8, s9, s10, s11; 0.9 down to
  0.6) and a duplicate novelty rejects. Five slots: by score the note shows s1's claim and
  s7 x2, s8, s9 (3 papers new to the line); new papers first, s7 x2, s8, s9, s10 (4).
- The author ticked 11-02's q-a section ⭕.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx2
import pytest

from jev_research_pipeline import cli
from jev_research_pipeline.evals import check, gate_score, gate_set, sampling, silver, stats
from jev_research_pipeline.evals.gate_policy import (
    BASELINE,
    Judged_,
    Policy,
    SPair,
    s_outcome,
    validate,
    x_shown,
)
from jev_research_pipeline.evals.jitter import floor, jitter
from jev_research_pipeline.evals.paths import bench_dir, eval_root
from jev_research_pipeline.jev import (
    claim_detection,
    judged_of,
    novelty,
    question_prefilter,
    question_screening,
    relevance_triage,
    source_trust,
)
from jev_research_pipeline.jev.core import score_levels
from jev_research_pipeline.model import (
    ChoiceAnswer,
    Claim,
    GraphNodeType,
    Judgment,
    Label,
    LineRecord,
    NoulAnswer,
    Operations,
    QuestionLog,
    Report,
    RunRecord,
    ScoreAnswer,
    SourceItem,
    Unit,
    sha256_hex,
)
from jev_research_pipeline.pipeline.config import env_tracks, line_context
from jev_research_pipeline.pipeline.run import capped
from jev_research_pipeline.questions import parse_questions
from jev_research_pipeline.store import GraphStore, input_sha256

from .fakes import fake_jev

JST = timezone(timedelta(hours=9))
D1, D2 = date(2026, 11, 2), date(2026, 11, 3)
LINE = "https://example.org/line/akc"
CONFIG = f'[tracks.akc]\nname = "AKC"\nid = "{LINE}"\nfirehose = false\n'
QUESTIONS = (
    "<!-- jrp:questions:akc -->\n\n"
    "## 記憶は何で決まるのか\n- slug: q-a\n- status: open\n- brief: エージェントの記憶\n"
    "- evidence: 測定\n- not: 人間の記憶\n\n"
    "## 道具をどう使うか\n- slug: q-b\n- status: open\n"
)
TEXT = " ".join(f"Sentence {i} reports a measured effect on agent memory." for i in range(8))
NOW = datetime(2026, 11, 9, 9, 0, tzinfo=JST)
KEY = {"ANTHROPIC_API_KEY": "sk-ant-test"}


def at(day: date, hour: int = 5) -> datetime:
    return datetime.combine(day, time(hour), JST)


QS = parse_questions(QUESTIONS, line=LINE, opened_at=at(date(2026, 10, 1)))
QA, QB = QS[0], QS[1]

type Values = Mapping[str, float | tuple[float, ...]]

KEEP: Values = {
    "on_topic": 0.97,
    "method_transferable": 0.97,
    "evidence_compatible": 0.97,
    "bridges_line": 0.1,
    "problem_overlap": (0.0, 0.0, 0.0, 1.0),
    "evidence_strength": (0.0, 0.0, 0.0, 1.0),
    "novelty_vs_evidence_set": (0.0, 0.0, 1.0),
}
NEAR: Values = {
    **KEEP,
    "problem_overlap": (0.0, 0.0, 1.0, 0.0),
    "evidence_strength": (0.0, 0.0, 1.0, 0.0),
    "novelty_vs_evidence_set": (0.53, 0.47, 0.0),
}
"""Weighted 0.58, every routing answer above its majority: review at keep 0.6, keep at 0.55."""
GATE_FAIL: Values = {**KEEP, "on_topic": 0.1}


def _screen_answers(values: Values) -> tuple[Any, ...]:
    out: list[Any] = []
    for name, info in question_screening.Answers.model_fields.items():
        v = values[name]
        if isinstance(v, tuple):
            out.append(ScoreAnswer(key=name, levels=score_levels(info.annotation), probabilities=v))  # pyright: ignore[reportArgumentType]
        else:
            out.append(NoulAnswer(key=name, p_yes=v))
    return tuple(out)


class Store:
    """The scenario's nodes, built the way a run stores them."""

    def __init__(self) -> None:
        self.nodes: list[GraphNodeType] = []
        self.sources: dict[str, SourceItem] = {}
        self.claims: dict[str, list[Claim]] = {}
        self.units: dict[str, Unit] = {}

    def source(self, name: str, *, n_claims: int = 0, text: str = TEXT) -> SourceItem:
        s = SourceItem.new(
            line=LINE,
            adapter="arxiv",
            url=f"https://arxiv.org/abs/2611.{len(self.sources):05d}",
            title=f"Paper {name}",
            text=text,
            fetched_at=at(D1),
        )
        self.sources[name] = s
        self.nodes.append(s)
        claims: list[Claim] = []
        for i in range(n_claims):
            unit = Unit.cut(s, start=i * 60, end=i * 60 + 50, granularity="sentence")
            claim = Claim.from_unit(unit, line=LINE)
            self.units[claim.id] = unit
            claims.append(claim)
            self.nodes += [unit, claim]
        self.claims[name] = claims
        return s

    def judgment(
        self,
        function: str,
        subjects: tuple[str, ...],
        bundle: str,
        answers: tuple[Any, ...],
        day: date,
        *,
        state: str = "",
    ) -> Judgment:
        j = Judgment.new(
            function=function,  # pyright: ignore[reportArgumentType]
            subjects=subjects,
            model="jev-1.13.0",
            state_sha256=state or sha256_hex(f"{function} {subjects}"),
            bundle_sha256=bundle,
            answers=answers,
            judged_at=at(day),
        )
        self.nodes.append(j)
        return j

    def prefilter(self, name: str, q0: float, q1: float, day: date = D1, state: str = "") -> None:
        self.judgment(
            "question_prefilter",
            (self.sources[name].id,),
            question_prefilter.ask(2).batched("source").sha256,
            (NoulAnswer(key="q0_on_topic", p_yes=q0), NoulAnswer(key="q1_on_topic", p_yes=q1)),
            day,
            state=state,
        )

    def safe(
        self,
        name: str,
        *,
        evidence: float = 0.9,
        trust: tuple[float, ...] = (0.0, 0.0, 0.0, 1.0),
    ) -> None:
        sid = self.sources[name].id
        self.judgment(
            "relevance_triage",
            (sid,),
            relevance_triage.ASK.batched("source").sha256,
            (
                NoulAnswer(key="contains_evidence", p_yes=evidence),
                NoulAnswer(key="prompt_injection", p_yes=0.05),
            ),
            D1,
        )
        self.judgment(
            "source_trust",
            (sid,),
            source_trust.ASK.batched("source").sha256,
            (
                ScoreAnswer(
                    key="trust",
                    levels=score_levels(source_trust.Trust),
                    probabilities=trust,
                ),
            ),
            D1,
        )

    def screen(self, name: str, q: Any, values: Values, state: str = "") -> Judgment:
        return self.judgment(
            "question_screening",
            (self.sources[name].id, q.id),
            question_screening.BATCH_ASK.sha256,
            _screen_answers(values),
            D1,
            state=state,
        )

    def detect(self, claim: Claim, q: Any, p: float) -> None:
        self.judgment(
            "claim_detection",
            (claim.unit, q.id),
            claim_detection.ASK.sha256,
            (
                ChoiceAnswer(
                    key="relation",
                    options=("advances", "contradicts", "unrelated"),
                    probabilities=(p, 0.0, round(1.0 - p, 6)),
                ),
                NoulAnswer(key="checkable", p_yes=0.99),
            ),
            D1,
        )

    def novel(self, claim: Claim, q: Any, day: date, *, new: bool = True) -> None:
        self.judgment(
            "novelty",
            (claim.id, q.id),
            novelty.ASK.sha256,
            (
                ScoreAnswer(
                    key="novelty",
                    levels=score_levels(novelty.Novelty),
                    probabilities=(0.0, 1.0, 0.0) if new else (1.0, 0.0, 0.0),
                ),
                NoulAnswer(key="same_source", p_yes=0.1),
            ),
            day,
        )

    def day(self, day: date, shown: Mapping[str, Sequence[Claim]]) -> Report:
        report_id = Report.id_for(LINE, day)
        claims: list[str] = []
        for qid, cs in shown.items():
            ids = tuple(c.id for c in cs)
            claims += ids
            self.nodes.append(
                QuestionLog.new(
                    question=qid,
                    report=report_id,
                    run_date=day,
                    movement="new_evidence_same_answer",
                    text="",
                    claims=ids,
                    logged_at=at(day),
                )
            )
        report = Report.new(
            line=LINE,
            run_date=day,
            rendering="template",
            prose=None,
            claims=tuple(claims),
            unjudged=(),
            partial=False,
            operations=Operations(
                jev_questions=1,
                jev_input_tokens=0,
                jev_output_tokens=0,
                generation_input_tokens=0,
                generation_output_tokens=0,
                writer_calls=0,
                cost_usd=0.0,
                rubric=(),
                fill_rate_previous=None,
            ),
        )
        self.nodes.append(report)
        return report


def scenario(env: Mapping[str, str]) -> tuple[list[GraphNodeType], list[GraphNodeType]]:
    """(the line's nodes, the pipeline's nodes): the module docstring's store."""
    ctx = line_context(env_tracks(env)[0])
    st = Store()
    for name in ("s1", "s2", "s3", "s4", "s5", "s6"):
        st.source(name, n_claims=3 if name == "s1" else 0)
    for name in ("s7", "s8", "s9", "s10", "s11", "s12"):
        st.source(name, n_claims=2 if name == "s7" else 1)
    st.prefilter("s1", 0.9, 0.9)
    st.prefilter("s2", 0.9, 0.1)
    st.prefilter("s3", 0.7, 0.1)
    st.prefilter("s4", 0.35, 0.1)
    st.prefilter("s5", 0.9, 0.1)
    s6 = st.sources["s6"]
    st.prefilter("s6", 0.9, 0.1, D2, input_sha256(question_prefilter.state(ctx, s6, QS)))
    for name in ("s1", "s2", "s3", "s6"):
        st.safe(name)
    st.safe("s5", evidence=0.2)
    s1_state = input_sha256(question_screening.state(ctx, st.sources["s1"], QA, []))
    for j in (
        st.screen("s1", QA, KEEP, s1_state),
        st.screen("s2", QA, NEAR),
        st.screen("s3", QA, GATE_FAIL),
        st.screen("s1", QB, KEEP),
    ):
        judged = judged_of(question_screening.ASK, j)
        assert judged is not None
        st.nodes.append(question_screening.decision(judged))
    c1a, c1b, c1c = st.claims["s1"]
    for c in (c1a, c1b):
        st.detect(c, QA, 0.97)
        st.novel(c, QA, D1)
    r1 = st.day(D1, {QA.id: [c1a, c1b]})
    pool = [
        (c1c, 0.95),
        (st.claims["s7"][0], 0.9),
        (st.claims["s7"][1], 0.85),
        (st.claims["s8"][0], 0.8),
        (st.claims["s9"][0], 0.75),
        (st.claims["s10"][0], 0.7),
        (st.claims["s11"][0], 0.6),
    ]
    for c, p in pool:
        st.detect(c, QA, p)
        st.novel(c, QA, D2)
    dup = st.claims["s12"][0]
    st.detect(dup, QA, 0.99)
    st.novel(dup, QA, D2, new=False)
    st.day(D2, {QA.id: [c for c, _ in pool[:5]]})
    log1 = QuestionLog.id_for(QA.id, D1)
    st.nodes.append(
        Label.new(
            subject=log1,
            report=r1.id,
            verdict="correct",
            provenance="question_day",
            harvested_at=at(D2),
        )
    )
    record = RunRecord.new(
        started_at=at(D1),
        lines=("akc",),
        line_records=(LineRecord(slug="akc", report=r1.id, questions=(QA.id, QB.id)),),
    )
    return st.nodes, [record]


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "config.toml").write_text(CONFIG, encoding="utf-8")
    qdir = tmp_path / "questions"
    qdir.mkdir()
    (qdir / "akc.md").write_text(QUESTIONS, encoding="utf-8")
    e = {
        "JRP_DAILY_RESEARCH_CONFIG": str(tmp_path / "config.toml"),
        "JRP_QUESTIONS_DIR": str(qdir),
        "JRP_STORE_DIR": str(tmp_path / "store"),
    }
    store = GraphStore(tmp_path / "store")
    nodes, pipeline = scenario(e)
    store.line("akc").put(nodes)
    store.pipeline().put(pipeline)
    return e


@pytest.fixture
def gs(env: dict[str, str]) -> gate_set.GateSet:
    gate_set.freeze(env, "t", since=D1)
    return gate_set.load(env, "t")


def _pair(gs: gate_set.GateSet, name: str, q: Any) -> SPair:
    source = SourceItem.id_for(LINE, _url(name))
    return next(p for p in gs.pairs if p.question == q.id and p.source == source)


def _url(name: str) -> str:
    order = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11", "s12"]
    return f"https://arxiv.org/abs/2611.{order.index(name):05d}"


# ------------------------------------------------------------------------------- sampling


def test_a_sample_is_drawn_from_the_sorted_ids_whatever_their_order():
    strata = {"a": ["x3", "x1", "x2"], "b": ["y1"]}
    one = sampling.draw(strata, {"a": 2, "b": 5}, "seed")
    two = sampling.draw({"b": ["y1"], "a": ["x2", "x3", "x1"]}, {"a": 2, "b": 5}, "seed")
    assert one == two and len(one["a"]) == 2 and one["b"] == ("y1",)
    assert sampling.interleaved({"a": ("1", "2"), "b": ("3",)}) == [
        ("a", "1"),
        ("b", "3"),
        ("a", "2"),
    ]


def test_an_estimate_of_a_fully_labelled_population_is_its_true_value():
    cells = {"h|1": sampling.Cell("h", population=10, labelled=10, positive=7)}
    got = sampling.estimate(cells, {"h|1": 1.0}, 10.0, draws=500)
    assert got is not None and got.value == pytest.approx(0.7) and got.low == got.high == 0.7


def test_a_cell_without_labels_borrows_its_stratum_and_an_unlabelled_stratum_is_unmeasured():
    cells = {
        "h|1": sampling.Cell("h", population=20, labelled=10, positive=5),
        "h|0": sampling.Cell("h", population=80, labelled=0),
        "g|0": sampling.Cell("g", population=50, labelled=0),
    }
    got = sampling.estimate(cells, {"h|1": 1.0, "h|0": 1.0}, 1.0, draws=2000)
    assert got is not None and got.value == pytest.approx(50.0)
    assert got.low < 50.0 < got.high
    assert sampling.estimate(cells, {"g|0": 1.0}, 1.0) is None


def test_the_paired_bootstrap_brackets_the_mean_and_refuses_no_cluster():
    mean, low, high = stats.paired_bootstrap([1.0, 0.0, 2.0, 1.0], reps=500)
    assert mean == 1.0 and low <= mean <= high
    with pytest.raises(ValueError):
        stats.paired_bootstrap([])


# --------------------------------------------------------------------------------- policy


def test_a_policy_replaces_values_and_refuses_names_the_run_does_not_have():
    p = Policy(overrides={"question_screening": {"keep": 0.55}})
    assert {t.name: t.value for t in p.of("question_screening")}["keep"] == 0.55
    assert {t.name: t.value for t in BASELINE.of("question_screening")}["keep"] == 0.6
    assert p.loosens("question_screening") and not BASELINE.loosens("question_screening")
    with pytest.raises(ValueError, match="no threshold"):
        validate({"question_screening": {"kep": 0.5}})
    with pytest.raises(ValueError, match="finite"):
        validate({"question_screening": {"keep": float("nan")}})
    with pytest.raises(ValueError, match="unknown function"):
        validate({"report_ordering": {}})


def test_capped_keeps_the_runs_caps_under_any_rank():
    items = [("q", "s1", 0.9), ("q", "s1", 0.8), ("q", "s1", 0.7), ("q", "s2", 0.1)]
    kept = capped(
        items, ["q"], question=lambda i: i[0], source=lambda i: i[1], rank=lambda i: (-i[2],)
    )
    assert kept == [items[0], items[1], items[3]]  # two from one source at most
    flipped = capped(
        items, ["q"], question=lambda i: i[0], source=lambda i: i[1], rank=lambda i: (i[2],)
    )
    assert flipped[0] == items[3]


# ------------------------------------------------------------------------------- the set


def test_the_set_holds_every_prefiltered_pair_and_rebuilds_its_states(gs: gate_set.GateSet):
    m = gs.manifest
    assert m.counts["s_pairs"] == 12  # six sources x two questions, the floor cleared
    assert m.counts["s_dev"] + m.counts["s_holdout"] == 12
    assert m.rebuild["akc"]["prefilter"] == (6, 6)  # five by the RunRecord, s6 by its state
    assert m.rebuild["akc"]["screening"] == (1, 4)  # only s1 / q-a was stored with its real state
    assert m.parity["screening"] == (4, 4)
    assert m.parity["x_sections"] == (2, 2)
    assert m.counts["x_days"] == 2


def test_a_personal_question_takes_a_named_authors_page_at_its_own_floor():
    st = Store()
    for name, levels in (("blog", (0.0, 1.0, 0.0, 0.0)), ("ad", (1.0, 0.0, 0.0, 0.0))):
        st.source(name)
        st.prefilter(name, 0.9, 0.1)
        st.safe(name, trust=levels)  # personal sits at 1/3, anonymous at 0
    screened = {name: st.screen(name, QA, KEEP).id for name in ("blog", "ad")}
    read = Judged_({n.id: n for n in st.nodes if isinstance(n, Judgment)})

    def pair(name: str, level: Literal["report", "personal"]) -> SPair:
        sid = st.sources[name].id
        of = {
            n.function: n.id for n in st.nodes if isinstance(n, Judgment) and n.subjects[0] == sid
        }
        return SPair(
            id=f"{name}-{level}",
            line="akc",
            source=sid,
            question=QA.id,
            day=D1,
            split="dev",
            prefilter=of["question_prefilter"],
            index=0,
            triage=of["relevance_triage"],
            trust=of["source_trust"],
            trust_level=level,
            screening=(screened[name],),
            stratum="",
        )

    assert s_outcome(read, pair("blog", "report"), BASELINE) == "safe"
    assert s_outcome(read, pair("blog", "personal"), BASELINE) == "keep"
    assert s_outcome(read, pair("ad", "personal"), BASELINE) == "safe"
    # a personal floor set above min_trust still takes what a report question takes
    above = Policy(overrides={"source_trust": {"min_trust_personal": 0.9}})
    assert source_trust.floor("personal", above.of("source_trust")) == 0.5
    lower = Policy(overrides={"source_trust": {"min_trust_personal": 0.4}})
    assert s_outcome(read, pair("blog", "personal"), lower) == "safe"


def test_each_pair_lands_where_the_baseline_routes_it(gs: gate_set.GateSet):
    read = Judged_(gs.judgments)
    expect = {
        ("s1", QA): ("keep", "high"),
        ("s2", QA): ("review", "band-low"),
        ("s3", QA): ("drop", "gate"),
        ("s4", QA): ("prefilter", "pf-near"),
        ("s5", QA): ("safe", "safe"),
        ("s6", QA): ("unasked", "unasked"),
        ("s1", QB): ("keep", "high"),
        ("s4", QB): ("prefilter", "pf-far"),
    }
    for (name, q), (outcome, stratum) in expect.items():
        p = _pair(gs, name, q)
        assert s_outcome(read, p, BASELINE) == outcome, name
        assert p.stratum == stratum, name
    assert _pair(gs, "s1", QA).gold is True and _pair(gs, "s2", QA).gold is None


def test_the_x_pool_drops_what_novelty_rejects_and_the_replay_matches_the_note(
    gs: gate_set.GateSet,
):
    read = Judged_(gs.judgments)
    d2 = next(d for d in gs.days if d.day == D2)
    assert len(d2.entries) == 8
    assert len(x_shown(read, d2, BASELINE)) == 5
    strata = [e.stratum for e in d2.entries]
    assert (strata.count("shown"), strata.count("cut"), strata.count("dup")) == (5, 2, 1)
    by_key = {e.key for e in x_shown(read, d2, Policy(slots="new_paper_first"))}
    assert _key("s1") not in by_key and _key("s10") in by_key


def _key(name: str) -> str:
    return "arxiv:" + _url(name).rsplit("/", 1)[1]


def test_materials_hold_the_question_and_the_source_the_labeller_reads(gs: gate_set.GateSet):
    s = [m for m in gs.materials.values() if m.kind == "s"]
    x = [m for m in gs.materials.values() if m.kind == "x"]
    assert len(s) == 12 and len(x) == 10
    one = next(m for m in s if m.item == _pair(gs, "s1", QA).id)
    assert one.question.title == QA.title and one.question.not_ == ("人間の記憶",)
    assert one.excerpt.startswith("Sentence 0") and one.title == "Paper s1"
    assert all(m.claim for m in x)


# ------------------------------------------------------------------------------ scoring


def _candidate(**raw: Any) -> gate_score.Candidate:
    c = gate_score.Candidate.model_validate(raw)
    c.policy()
    return c


EMPTY_FLOOR = floor(Path("/nonexistent"))


def test_a_lower_keep_cut_keeps_the_pair_at_the_cut_and_nothing_else(gs: gate_set.GateSet):
    r = gate_score.score(
        gs, _candidate(name="k", thresholds={"question_screening": {"keep": 0.55}}), {}, EMPTY_FLOOR
    )
    gained = sum(r.s[sp].gained for sp in gate_score.SPLITS)
    lost = sum(r.s[sp].lost for sp in gate_score.SPLITS)
    assert (gained, lost) == (1, 0)
    assert sum(r.s[sp].kept_b for sp in gate_score.SPLITS) == 2
    assert all(r.s[sp].precision_b is None for sp in gate_score.SPLITS)  # no labels
    assert sum(r.x[sp].new_c - r.x[sp].new_b for sp in gate_score.SPLITS) == 0


def test_new_papers_first_shows_one_more_paper_new_to_the_line(gs: gate_set.GateSet):
    r = gate_score.score(
        gs, _candidate(name="n", slots={"order": "new_paper_first"}), {}, EMPTY_FLOOR
    )
    assert sum(r.x[sp].new_c - r.x[sp].new_b for sp in gate_score.SPLITS) == 1
    assert sum(r.x[sp].shown_c for sp in gate_score.SPLITS) == sum(
        r.x[sp].shown_b for sp in gate_score.SPLITS
    )
    text = gate_score.render(r)
    assert "## X 根拠化と掲載枠" in text and "未測定" in text and "hillclimb 不可" in text


def test_a_candidate_file_names_only_what_the_run_has(tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text('name = "b"\n[thresholds.question_screening]\nkep = 0.5\n', encoding="utf-8")
    with pytest.raises(ValueError, match="no threshold"):
        gate_score.load_candidate(bad)
    for repo in sorted(Path("bench/gate/candidates").glob("*.toml")):
        assert gate_score.load_candidate(repo).name == repo.stem


def _s(gold_c: int, changed: int, dp: sampling.Interval | None = None) -> gate_score.SScore:
    flat = sampling.Interval(0.0, -0.1, 0.1)
    return gate_score.SScore(
        pairs=1,
        kept_b=1,
        kept_c=1,
        gained=0,
        lost=0,
        unasked=0,
        gold_b=1,
        gold_c=gold_c,
        gold=1,
        labelled=90,
        changed_labelled=changed,
        d_precision=dp,
        d_recall=flat if dp is not None else None,
    )


def test_the_verdict_fails_a_change_wholly_below_zero_or_a_lost_tick():
    worse = _s(1, 90, sampling.Interval(-0.2, -0.3, -0.1))
    assert gate_score.verdict_s(worse).gate == "FAIL" and gate_score.verdict_s(worse).hillclimb
    v = gate_score.verdict_s(_s(0, 3, sampling.Interval(0.0, -0.1, 0.1)))
    assert v.gate == "FAIL" and "著者の ⭕" in v.regressions and not v.hillclimb
    assert gate_score.verdict_s(_s(1, 0)).gate == "PASS(一部未測定)"


# ---------------------------------------------------------------------- silver (Claude)


def _reply(body: Mapping[str, Any], answer: Mapping[str, object]) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_synthetic",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [{"type": "text", "text": json.dumps(answer)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 100},
        },
    )


class Api:
    def __init__(self, respond: Callable[[dict[str, Any]], httpx2.Response] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self._respond = respond or self._yes_for_s1_and_new_papers

    @staticmethod
    def _yes_for_s1_and_new_papers(body: dict[str, Any]) -> httpx2.Response:
        text = body["messages"][0]["content"][0]["text"]
        yes = "Paper s1\n" in text or "Paper s7" in text or "Paper s8" in text
        return _reply(body, {"answer": "yes" if yes else "no", "reason": "r"})

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.sent.append(body)
        return self._respond(body)


async def _label(
    gs: gate_set.GateSet, env: Mapping[str, str], api: Api, **kw: Any
) -> silver.LabelResult:
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(api)) as http:
        return await silver.label(
            gs, env, silver.ledger_path(eval_root(env)), http=http, now=NOW, lang="ja", **kw
        )


async def test_without_a_key_nothing_is_labelled_or_written(
    gs: gate_set.GateSet, env: dict[str, str]
):
    api = Api()
    got = await _label(gs, env, api)
    assert got.stop == "no-key" and got.labelled == 0 and not api.sent
    assert not silver.ledger_path(eval_root(env)).exists()


async def test_labels_are_written_once_and_read_back_under_the_rubric(
    gs: gate_set.GateSet, env: dict[str, str]
):
    api = Api()
    got = await _label(gs, {**env, **KEY}, api)
    assert got.stop is None and got.labelled == 22 and got.usd == pytest.approx(22 * 0.006)
    ledger = silver.ledger_path(eval_root(env))
    answers = silver.labels(ledger, "t", "ja")
    assert answers[_pair(gs, "s1", QA).id] == "yes" and answers[_pair(gs, "s3", QA).id] == "no"
    again = await _label(gs, {**env, **KEY}, api)
    assert again.labelled == 0 and again.already == 22 and len(api.sent) == 22
    first = api.sent[0]
    assert first["model"] == "claude-opus-5-5" and "外部由来のデータ" in json.dumps(
        first, ensure_ascii=False
    )


async def test_the_weeks_cap_stops_the_labeller(gs: gate_set.GateSet, env: dict[str, str]):
    got = await _label(gs, {**env, **KEY, silver.BUDGET_ENV: "0.5"}, Api())
    assert got.stop == "budget" and got.labelled < 22
    assert got.week_usd <= 0.5


async def test_a_429_stops_at_once_and_is_not_retried(gs: gate_set.GateSet, env: dict[str, str]):
    def limited(_: dict[str, Any]) -> httpx2.Response:
        return httpx2.Response(
            429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}}
        )

    api = Api(limited)
    got = await _label(gs, {**env, **KEY}, api, concurrency=1)
    assert got.stop == "rate-limit" and got.labelled == 0 and len(api.sent) == 1


async def test_labelled_sets_score_precision_and_recall(gs: gate_set.GateSet, env: dict[str, str]):
    await _label(gs, {**env, **KEY}, Api())
    answers = silver.labels(silver.ledger_path(eval_root(env)), "t", "ja")
    r = gate_score.score(
        gs, _candidate(name="n", slots={"order": "new_paper_first"}), answers, EMPTY_FLOOR
    )
    assert any(r.x[sp].precision_b is not None for sp in gate_score.SPLITS)
    assert any(r.s[sp].recall_b is not None for sp in gate_score.SPLITS)


# ------------------------------------------------------------------------------- jitter


async def test_jitter_asks_the_same_states_again_and_records_the_flips(
    gs: gate_set.GateSet, env: dict[str, str]
):
    calls: list[httpx2.Request] = []
    handler = fake_jev(dict(KEEP))

    async def counted(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return await handler(request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(counted)) as http:
        got = await jitter(gs, {**env, "TYPESAFE_API_KEY": "k"}, http=http, now=NOW, n=5)
    assert got.reasked is not None and len(calls) == 1  # one state was rebuilt
    assert got.floor.judged == 1 and got.floor.flips == 0
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(counted)) as http:
        none = await jitter(gs, env, http=http, now=NOW)
    assert none.reasked is None and len(calls) == 1


# -------------------------------------------------------------------------------- check


async def test_the_check_page_hides_the_label_and_reads_the_ticks_back(
    gs: gate_set.GateSet, env: dict[str, str], tmp_path: Path
):
    await _label(gs, {**env, **KEY}, Api())
    answers = silver.labels(silver.ledger_path(eval_root(env)), "t", "ja")
    page = tmp_path / "check.md"
    n = check.write_check(gs, answers, page, n=6)
    text = page.read_text(encoding="utf-8")
    assert n == 6 and text.count("- [ ] yes") == 6 and "silver" not in text.split("\n", 3)[3]
    key = json.loads(page.with_suffix(".key.json").read_text(encoding="utf-8"))
    ticked = text
    for row in key:
        block = f"## {row['n']}. "
        head, rest = ticked.split(block, 1)
        rest = rest.replace(f"- [ ] {row['silver']}", f"- [x] {row['silver']}", 1)
        ticked = head + block + rest
    page.write_text(ticked, encoding="utf-8")
    agreement = check.read_check(page)
    assert agreement.answered == 6 and agreement.agree == 6 and agreement.exact == 6
    assert "6 件中 6 件" in check.render_agreement(agreement)


# ---------------------------------------------------------------------------------- cli


def test_the_cli_freezes_and_scores_a_candidate(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    for k in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY", "JRP_VAULT_DIR"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert cli.main(["eval", "gate", "freeze", "--set", "c", "--since", D1.isoformat()]) == 0
    assert "eval set c" in capsys.readouterr().out
    code = cli.main(
        ["eval", "gate", "--set", "c", "--candidate", "bench/gate/candidates/new-paper-first.toml"]
    )
    out = capsys.readouterr().out
    assert code == 0 and "# gate eval: new-paper-first" in out
    assert (bench_dir(env, "gate", "c") / "results" / "new-paper-first.md").is_file()
    assert cli.main(["eval", "gate", "--set", "missing", "--candidate", "x.toml"]) == 1
    assert cli.main(["eval", "gate", "freeze", "--set", "../escape"]) == 1
    with pytest.raises(SystemExit):
        cli.main(["eval", "gate", "jitter", "--set", "c", "--max-questions", "0"])
    with pytest.raises(ValueError):
        bench_dir(env, "gate", "../x")


def test_the_floor_counts_a_state_asked_twice_once(tmp_path: Path):
    rows = [
        {
            "at": "2026-11-01T09:00:00+09:00",
            "judgment": "j1",
            "route_old": "keep",
            "route_new": "review",
            "w_old": 0.6,
            "w_new": 0.59,
        },
        {
            "at": "2026-11-02T09:00:00+09:00",
            "judgment": "j1",
            "route_old": "keep",
            "route_new": "keep",
            "w_old": 0.6,
            "w_new": 0.61,
        },
        {
            "at": "2026-11-02T09:00:00+09:00",
            "judgment": "j2",
            "route_old": "drop",
            "route_new": "drop",
            "w_old": 0.3,
            "w_new": 0.3,
        },
    ]
    (tmp_path / "jitter.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    f = floor(tmp_path)
    assert (f.judged, f.flips, f.runs) == (2, 0, 1)


def test_a_refreeze_sets_aside_what_was_measured_on_the_old_set(
    gs: gate_set.GateSet, env: dict[str, str]
):
    (gs.root / "jitter.jsonl").write_text("{}\n", encoding="utf-8")
    (gs.root / "results").mkdir()
    gate_set.freeze(env, "t", since=D1)
    assert not (gs.root / "jitter.jsonl").exists() and not (gs.root / "results").exists()
    moved = list((gs.root / "superseded").glob("*/jitter.jsonl"))
    assert len(moved) == 1
