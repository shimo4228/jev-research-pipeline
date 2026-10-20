"""`jrp eval intake` (evals): the shared intervals, the frozen set read from a partition, one
day's replay in production's own cut, the scores, and the command over a scratch store.
Synthetic sources only; nothing here touches the network."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from jev_research_pipeline.evals import intake as ev
from jev_research_pipeline.evals import stats
from jev_research_pipeline.evals.intake_report import (
    IntakeArgs,
    LineResult,
    evaluate_line,
    intake_command,
)
from jev_research_pipeline.evals.judge import Spend
from jev_research_pipeline.jev import LineContext, question_prefilter
from jev_research_pipeline.jev.core import JEV_MODEL
from jev_research_pipeline.model import (
    AdapterKind,
    GraphNodeType,
    Judgment,
    NoulAnswer,
    QueryCandidate,
    SourceItem,
    StageRecord,
)
from jev_research_pipeline.pipeline import nets
from jev_research_pipeline.pipeline.config import env_tracks, line_context
from jev_research_pipeline.questions import open_questions, question_queries
from jev_research_pipeline.store import GraphStore, input_sha256

from . import builders as b

D0, D1, D2, D3 = date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)
LONG = "An abstract long enough to clear the body floor of the screen. " * 5
QUERY_HF: ev.Query = ("hf_papers", "agent memory")
QUERY_AX: ev.Query = ("arxiv", "narrow questions")


def at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 5, 0, tzinfo=UTC)


# ------------------------------------------------------------------------------ stats


def test_chao2_reproduces_brons_worked_example():
    # Bron et al. 2024 (arXiv 2404.01176) eq. (1)-(4): n=92, f1=40, f2=33, no (T-1)/T
    estimate, variance = stats.chao2_from(92, 40, 33, factor=1.0)
    low, high = stats.lognormal_interval(92, estimate, variance)
    assert (round(estimate, 2), round(variance, 2)) == (116.24, 100.82)
    assert (round(low, 2), round(high, 2)) == (103.11, 144.88)


def test_chao2_needs_ten_units_and_reads_q2_zero_and_q1_zero():
    assert stats.chao2([1, 1, 2], units=9) is None
    no_doubles = stats.chao2([1, 1, 1, 3], units=10)
    assert no_doubles is not None
    assert no_doubles.estimate == pytest.approx(4 + 0.9 * 3 * 2 / 2)
    assert no_doubles.low >= no_doubles.s_obs
    complete = stats.chao2([2, 3, 4], units=10)
    assert complete is not None
    assert complete.missed == (0.0, 0.0, 0.0)


def test_paired_diff_has_a_t_interval_and_an_exact_sign_flip_p():
    d = stats.paired_diff([1, 2, 0, 3, 1])
    assert d.total == 7
    assert d.low is not None and d.high is not None
    assert d.low < 7 < d.high
    assert d.p == pytest.approx(4 / 32)  # 2 of 16 non-zero sign patterns, both tails
    assert stats.paired_diff([0, 0, 0]).p is None
    assert stats.paired_diff([2]).low is None


def test_t975_and_expected_flips():
    assert stats.t975(30) == 2.042
    assert abs(stats.t975(31) - 2.04) < 0.01
    assert stats.expected_flips([0.01, 0.2], [0.0, 0.02, 0.05]) == pytest.approx(2 / 3)
    assert stats.expected_flips([0.01], []) == 0.0


# --------------------------------------------------------------------------- a world


class World:
    """One line's partition: listings and keyword fetches per day, and prefilter answers."""

    def __init__(self, line: str = b.LINE_IRI) -> None:
        self.line = line
        self.nodes: dict[str, GraphNodeType] = {}
        self.n = 0

    def source(
        self, title: str, *, day: date, text: str = LONG, adapter: AdapterKind = "arxiv"
    ) -> SourceItem:
        self.n += 1
        s = SourceItem.new(
            line=self.line,
            adapter=adapter,
            url=f"https://arxiv.org/abs/2610.{self.n:05d}",
            title=title,
            text=text,
            fetched_at=at(day),
        )
        self.nodes[s.id] = s
        return s

    def fetch(self, stage: str, day: date, sources: Sequence[SourceItem], *, key: str = "") -> None:
        digest = key or input_sha256({"stage": stage, "day": day.isoformat()})
        r = StageRecord.new(
            stage=stage,
            input_sha256=digest,
            outputs=tuple(s.id for s in sources),
            completed_at=at(day),
        )
        self.nodes[r.id] = r

    def keyword(self, query: ev.Query, day: date, sources: Sequence[SourceItem]) -> None:
        self.fetch(f"fetch_keyword_{query[0]}", day, sources, key=ev._keyword_key(query, day))  # pyright: ignore[reportPrivateUsage]

    def judged(self, source: SourceItem, day: date, p: float = 0.8, *, state: str = "") -> None:
        ask = question_prefilter.ask(1)
        j = Judgment.new(
            function="question_prefilter",
            subjects=(source.id,),
            model=JEV_MODEL,
            state_sha256=state or input_sha256({"s": source.id}),
            bundle_sha256=ask.sha256,
            answers=(NoulAnswer(key="q0_on_topic", p_yes=p),),
            judged_at=at(day),
        )
        self.nodes[j.id] = j


def setup(cap: int = 3) -> ev.LineSetup:
    q = b.question()
    return ev.LineSetup(
        slug="akc",
        ctx=LineContext(line=b.line(), vocabulary=("agent memory",)),
        questions=(q,),
        queries={q.id: (QUERY_HF, QUERY_AX)},
        nets=nets.NetConfig(firehose_max=cap),
        firehose_query="agent memory",
    )


def listing_world() -> tuple[World, dict[str, SourceItem]]:
    """D1 (before the window): a listing production judged. D2: HF 1 + arXiv 5 into a cap
    of 3. D3: an empty listing day, and a keyword fetch."""
    w = World()
    old = w.source("Old agent memory paper", day=D1)
    w.fetch("fetch_firehose_arxiv", D1, [old])
    w.judged(old, D1)
    hf = w.source("Agent memory from HF", day=D2)
    titles = [
        "agent memory one",
        "agent memory two",
        "unrelated alpha",
        "agent memory three",
        "unrelated beta",
    ]
    ax = [w.source(t, day=D2) for t in titles]
    w.fetch("fetch_firehose_hf_papers", D2, [hf])
    w.fetch("fetch_firehose_arxiv", D2, ax)
    w.fetch("fetch_firehose_arxiv", D3, [])
    kw = w.source("Keyword find", day=D3)
    w.keyword(QUERY_HF, D3, [kw])
    named = {s.title: s for s in w.nodes.values() if isinstance(s, SourceItem)}
    return w, named


def test_the_replay_keeps_hf_first_and_cuts_arxiv_by_productions_own_ranking():
    w, named = listing_world()
    frozen = ev.frozen_set("akc", w.nodes, [QUERY_HF])
    base = ev.arm(ev.BASELINE, setup())
    reaches = ev.replay(frozen, setup(), base, [D2], start=D2)
    kept = [r.source for r in reaches if r.via.startswith("firehose")]
    assert kept[0] == named["Agent memory from HF"].id
    listing = [
        named[t]
        for t in [
            "agent memory one",
            "agent memory two",
            "unrelated alpha",
            "agent memory three",
            "unrelated beta",
        ]
    ]
    expected, ranked = nets.firehose_cut(listing, 2, "agent memory")
    assert ranked
    assert kept[1:] == [s.id for s in expected]


def test_a_backlog_fills_the_room_an_empty_day_leaves_with_the_overflow():
    w, named = listing_world()
    frozen = ev.frozen_set("akc", w.nodes, [QUERY_HF])
    candidate = ev.Candidate(name="backlog", firehose=ev.FirehoseSpec(backlog_days=7))
    s = setup()
    base = ev.replay(frozen, s, ev.arm(ev.BASELINE, s), [D2, D3], start=D2)
    cand = ev.replay(frozen, s, ev.arm(candidate, s), [D2, D3], start=D2)
    filled = {r.source for r in cand if r.via == ev.BACKLOG}
    assert len(filled) == 3  # the three of D2's listing that D2 did not keep
    assert named["Old agent memory paper"].id not in filled  # judged before the window
    assert not {r.source for r in base if r.day == D2} & filled
    assert {r.source for r in base} < {r.source for r in cand}


def test_a_dropped_query_reaches_nothing_and_the_keyword_record_is_named():
    w, named = listing_world()
    frozen = ev.frozen_set("akc", w.nodes, [QUERY_HF])
    [kw] = [f for f in frozen.fetches if f.net == "keyword"]
    assert kw.query == QUERY_HF
    assert kw.via == "keyword/hf: agent memory"
    s = setup()
    dropped = ev.arm(
        ev.Candidate(name="d", queries={"akc": ev.QueryEdit(drop=("hf: agent memory",))}), s
    )
    reaches = ev.replay(frozen, s, dropped, [D3], start=D2)
    assert named["Keyword find"].id not in {r.source for r in reaches}
    assert dropped.queries == (QUERY_AX,)


def test_a_query_line_must_parse():
    with pytest.raises(ValueError, match="not a query line"):
        ev.QueryEdit(drop=("memory",))
    assert ev.parse_query("web:  agent  memory ") == ("web_search", "agent memory")
    assert ev.query_line(("hf_papers", "x y")) == "hf: x y"


def test_scores_count_new_papers_once_on_their_first_passing_day():
    w, named = listing_world()
    frozen = ev.frozen_set("akc", w.nodes, [QUERY_HF])
    s = setup()
    base_arm = ev.arm(ev.BASELINE, s)
    reaches = ev.replay(frozen, s, base_arm, [D2, D3], start=D2)
    verdicts = {r.source: ev.verdict_of([0.9]) for r in reaches}
    verdicts[named["Keyword find"].id] = ev.verdict_of([0.2])
    known = frozenset(k for k, d in frozen.first.items() if d < D2)
    score = ev.score(frozen, base_arm, reaches, verdicts, known=known, days=[D2, D3])
    assert score.n_ot == 3  # HF + the two arXiv kept; the keyword find fails
    assert score.per_day == {D2: 3, D3: 0}
    assert score.keys_new == score.keys == 4
    rows = {r.via: r for r in ev.by_source(score.found)}
    assert rows["firehose"].found == 3
    assert rows["firehose/hf_papers"].unique == 1
    assert score.chao_all is None  # one query request-day: below MIN_UNITS


def test_the_self_check_matches_productions_prefiltered_set():
    w, named = listing_world()
    frozen = ev.frozen_set("akc", w.nodes, [QUERY_HF])
    s = setup()
    base_arm = ev.arm(ev.BASELINE, s)
    reaches = ev.replay(frozen, s, base_arm, [D2], start=D2)
    for r in reaches:
        w.judged(frozen.sources[r.source], D2)
    check = ev.self_check(ev.frozen_set("akc", w.nodes, [QUERY_HF]), reaches, base_arm, [D2])
    assert (check.matched, check.off) == (1, ())
    w.judged(named["unrelated beta"], D2)  # production judged one the replay cut
    check = ev.self_check(ev.frozen_set("akc", w.nodes, [QUERY_HF]), reaches, base_arm, [D2])
    assert check.off == ((D2, 0, 1),)


def test_a_query_is_exhausted_after_three_sends_with_nothing_new():
    w = World()
    same = w.source("The same result", day=D0)
    for day in (D0, D1, D2, D3):
        w.keyword(QUERY_HF, day, [same])
    frozen = ev.frozen_set("akc", w.nodes, [QUERY_HF])
    [y] = ev.query_yields(frozen, {same.id: ev.verdict_of([0.7])}, [QUERY_HF], until=D3)
    assert (y.sends, y.new, y.ot) == (4, (1, 0, 0, 0), (1, 0, 0, 0))
    assert y.exhausted


def test_the_rotation_follows_the_runs_own_budget_and_the_estimate_moves_with_it():
    s = setup()
    base = ev.sends(s, ev.arm(ev.BASELINE, s).queries, turn=0, runs=4, today=D3, env={})
    assert base == {QUERY_HF: 4, QUERY_AX: 4}
    dropped = ev.arm(
        ev.Candidate(name="d", queries={"akc": ev.QueryEdit(drop=("hf: agent memory",))}), s
    )
    cand = ev.sends(s, dropped.queries, turn=0, runs=4, today=D3, env={})
    assert cand == {QUERY_AX: 4}
    yields = {
        QUERY_HF: ev.QueryYield(QUERY_HF, 4, (1, 0, 0, 0), (1, 0, 0, 0)),
        QUERY_AX: ev.QueryYield(QUERY_AX, 4, (2, 2, 2, 2), (1, 1, 1, 1)),
    }
    rot = ev.rotation(yields, base, cand, runs=4)
    assert rot.base.per_run == pytest.approx(1.25)
    assert rot.cand.per_run == pytest.approx(1.0)
    assert rot.freed == 1.0
    assert rot.low <= rot.delta <= rot.high


def test_turn_of_counts_the_lines_earlier_reports():
    report = b.report()
    nodes: dict[str, GraphNodeType] = {report.id: report}
    assert ev.turn_of(nodes, report.line, report.run_date) == 0
    assert ev.turn_of(nodes, report.line, date(2027, 1, 1)) == 1


# -------------------------------------------------------------------------- the command


CONFIG = '[tracks.akc]\nname = "AKC"\n'
QUESTIONS = """<!-- jrp:questions:akc -->

## エージェントの記憶は何で決まるのか
- slug: agent-memory
- status: open
- brief: 記憶機構の違いが下流の精度をどれだけ動かすか。
- hf: agent memory
- arxiv: narrow questions
"""


def scratch_env(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "questions").mkdir()
    (tmp_path / "questions" / "akc.md").write_text(QUESTIONS, encoding="utf-8")
    (tmp_path / "config.toml").write_text(CONFIG, encoding="utf-8")
    return {
        "JRP_QUESTIONS_DIR": str(tmp_path / "questions"),
        "JRP_DAILY_RESEARCH_CONFIG": str(tmp_path / "config.toml"),
        "JRP_STORE_DIR": str(tmp_path / "store"),
        "JRP_EVAL_DIR": str(tmp_path / "evals"),
    }


def stored_world(env: dict[str, str]) -> World:
    """listing_world for the env's own line, with every source judged under today's
    questions (the exact state a run sends), so the eval asks Jev nothing."""
    [track] = env_tracks(env)
    ctx = line_context(track)
    questions = open_questions(env, "akc", line=ctx.line.id, now=at(D3))
    queries = question_queries(env, "akc", questions)
    w = World(line=ctx.line.id)
    old = w.source("Old agent memory paper", day=D1)
    w.fetch("fetch_firehose_arxiv", D1, [old])
    hf = w.source("Agent memory from HF", day=D2)
    ax = [
        w.source(t, day=D2) for t in ("agent memory one", "unrelated", "agent memory two", "noise")
    ]
    w.fetch("fetch_firehose_hf_papers", D2, [hf])
    w.fetch("fetch_firehose_arxiv", D2, ax)
    w.fetch("fetch_firehose_arxiv", D3, [])
    for day in (D1, D2, D3):
        w.keyword(QUERY_HF, day, [old])  # an exhausted query: the same old paper each send
    q = QueryCandidate.new(line=ctx.line.id, adapter="hf_papers", text="agent memory")
    w.nodes[q.id] = q
    for s in [old, hf, *ax]:
        state = input_sha256(question_prefilter.state(ctx, s, questions))
        w.judged(s, D1 if s is old else D2, 0.9 if "memory" in s.title else 0.1, state=state)
    assert queries
    GraphStore(Path(env["JRP_STORE_DIR"])).line("akc").put(w.nodes.values())
    return w


async def test_the_command_compares_a_backlog_candidate_in_the_bench_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    env = scratch_env(tmp_path)
    stored_world(env)
    store_file = Path(env["JRP_STORE_DIR"]) / "lines" / "akc.jsonld"
    before = store_file.read_bytes()
    candidate = tmp_path / "backlog.toml"
    candidate.write_text(
        'name = "backlog"\n[firehose]\nmax = 3\nbacklog_days = 7\n', encoding="utf-8"
    )
    code = await intake_command(
        env, IntakeArgs(candidate=candidate, lines=(), days=2, as_of=D3, jitter=0)
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "## akc" in out
    assert "N_ot" in out and "雑音の床" in out and "未測定" in out
    assert store_file.read_bytes() == before  # the store is read, never written
    reports = list((tmp_path / "evals" / "intake" / "reports").glob("*-backlog.*"))
    assert {p.suffix for p in reports} == {".json", ".md"}


async def test_evaluate_line_scores_the_candidate_against_the_baseline(tmp_path: Path):
    env = scratch_env(tmp_path)
    stored_world(env)
    candidate = ev.Candidate(name="cap1", firehose=ev.FirehoseSpec(max=1))
    result: LineResult = await evaluate_line(
        env,
        "akc",
        candidate,
        bench=tmp_path / "evals" / "intake",
        spend=Spend(cap=0.5),
        http=None,
        now=at(D3),
        days=2,
        as_of=D3,
        jitter_n=0,
    )
    assert result.days == [D2, D3]
    assert result.base.n_ot == 3  # HF + two "agent memory" arXiv items under a cap of 300
    assert result.cand.n_ot == 1  # a cap of 1 keeps the HF item only
    assert result.diff.total == -2
    assert result.check.matched == result.check.days == 2
    assert result.floor is None
    [y] = [y for y in result.yields if y.query == QUERY_HF]
    assert y.sends == 3


async def test_a_candidate_that_does_not_load_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    bad = tmp_path / "bad.toml"
    bad.write_text('name = "x"\n[queries.akc]\ndrop = ["memory"]\n', encoding="utf-8")
    assert await intake_command({}, IntakeArgs(candidate=bad, lines=())) == 2
    assert "not a query line" in capsys.readouterr().err


@pytest.mark.parametrize(
    "path", sorted((Path(__file__).parent.parent / "bench" / "intake").glob("*.toml"))
)
def test_the_committed_candidates_load(path: Path):
    candidate = ev.load_candidate(path)
    assert candidate.name == path.stem
