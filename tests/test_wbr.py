"""The weekly review (pipeline.wbr, `jrp wbr`): every number of one synthetic week, counted
by hand from the store the run writes, and the promise that it only reads the store.

The scenario (review week 2026-W45, 11-02..11-08; two mature cohorts W43 and W44):
- akc, questions agent-memory / memory-eval / tool-use (closed-one is dropped).
  W43 cohort: a1..a6 fetched 10-20. a1..a4 pass the prefilter (a6 is above the cut but
  below the text floor, a5 below the cut); a1..a3 route keep, a4 drop; a1, a2 are posted on
  10-21 and a1 is cited; a3 is posted and cited on 10-30, past its 7 days.
  W44 cohort: b1..b8 fetched 10-27. b1..b6 pass; b1..b4 keep, b5 review, b6 drop; b1..b3
  posted and cited on 10-28.
  W45: c1, d1 (and a1 again) fetched 11-03; agent-memory's prose cites its claim [2] (c1)
  and memory-eval's its claim [1] (d1): each section numbers its own claims, so read
  through the note's claim order [1] would be a1. tool-use screens c1 and d1, both drop.
- edge, questions edge-q / edge-quiet. On 11-04 edge-q keeps, posts and cites e1, an HF
  page of a1's arXiv paper: one paper, already delivered, so edge's O1 is 0.
- ans has no open question.
"""

import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

from jev_research_pipeline import cli
from jev_research_pipeline.jev import question_prefilter, question_screening
from jev_research_pipeline.jev.core import score_levels
from jev_research_pipeline.model import (
    Answer,
    Claim,
    GraphNodeType,
    Judgment,
    Label,
    LabelProvenance,
    LineRecord,
    NoulAnswer,
    Operations,
    Question,
    QuestionLog,
    Report,
    RunRecord,
    ScoreAnswer,
    Sighting,
    SourceItem,
    StageRecord,
    Unit,
    sha256_hex,
)
from jev_research_pipeline.model.jsonld import CONTEXT
from jev_research_pipeline.pipeline.config import ReservedSlug, load_tracks
from jev_research_pipeline.pipeline.doctor import doctor
from jev_research_pipeline.pipeline.monitor import LEDGER_FILE
from jev_research_pipeline.pipeline.registry import Snapshot
from jev_research_pipeline.pipeline.wbr import (
    O2,
    PRINTABLE_CHARS,
    REASONS_SHOWN,
    WEEKLY_FILE,
    AuthorSignal,
    Delivery,
    Funnel,
    Group,
    Inputs,
    LineSpec,
    Measure,
    Week,
    WeeklyReview,
    Written,
    note_name,
    paper_key,
    poisson_interval,
    printable,
    render,
    shift,
    weekly_review,
    wilson,
    write_weekly_review,
)
from jev_research_pipeline.questions import parse_questions
from jev_research_pipeline.reduction.opened import OPENED_FILE
from jev_research_pipeline.reduction.used import is_jrp_name, keys_of_text, scan_documents
from jev_research_pipeline.report import report_notes
from jev_research_pipeline.store import GraphStore, Partition

CJK = re.compile(r"[぀-ヿ一-鿿]")
"""Kana and CJK ideographs, as tests/test_note_text.py checks the en column."""
JST = timezone(timedelta(hours=9))
WEEK = Week.parse("2026-W45")
NOW = datetime(2026, 11, 9, 5, 30, tzinfo=JST)
GOLDEN = Path(__file__).parent / "golden" / "wbr"
GOLDEN_ENV = "JRP_GOLDEN_UPDATE"
LINES = {s: f"https://example.org/line/{s}" for s in ("akc", "edge", "ans")}
LONG = "Agents remember what they were told, and this measured effect is large. " * 4
SHORT = "A one-line abstract."

QUESTION_FILES = {
    "akc": (
        "<!-- jrp:questions:akc -->\n\n"
        "## 記憶は何で決まるのか\n- slug: agent-memory\n- status: open\n\n"
        "## 記憶をどう評価するか\n- slug: memory-eval\n- status: open\n\n"
        "## 道具をどう使うか\n- slug: tool-use\n- status: open\n\n"
        "## 閉じた問い\n- slug: closed-one\n- status: dropped\n"
    ),
    "edge": (
        "<!-- jrp:questions:edge -->\n\n"
        "## 境界はどこか\n- slug: edge-q\n\n"
        "## 静かな問い\n- slug: edge-quiet\n"
    ),
}

CONFIG = "".join(
    f'[tracks.{slug}]\nname = "{slug.upper()}"\nid = "{iri}"\nfirehose = false\n\n'
    for slug, iri in LINES.items()
)


def at(day: date, hour: int = 5) -> datetime:
    return datetime.combine(day, time(hour), JST)


def d(month: int, day: int) -> date:
    return date(2026, month, day)


def questions(slug: str) -> tuple[Question, ...]:
    parsed = parse_questions(QUESTION_FILES[slug], line=LINES[slug], opened_at=at(d(10, 1)))
    return tuple(q for q in parsed if q.status == "open")


AKC = {q.slug: q for q in questions("akc")}
EDGE = {q.slug: q for q in questions("edge")}

type Values = Mapping[str, float | tuple[float, ...]]
"""Screening answers by field: a Noul's p_yes, a Score's distribution."""

KEEP: Values = {
    "on_topic": 0.97,
    "method_transferable": 0.97,
    "evidence_compatible": 0.97,
    "bridges_line": 0.1,
    "problem_overlap": (0.0, 0.0, 0.0, 1.0),
    "evidence_strength": (0.0, 0.0, 0.0, 1.0),
    "novelty_vs_evidence_set": (0.0, 0.0, 1.0),
}
DROP: Values = {**KEEP, "on_topic": 0.1}
REVIEW: Values = {
    **KEEP,
    "problem_overlap": (0.3, 0.3, 0.0, 0.4),
    "novelty_vs_evidence_set": (0.0, 1.0, 0.0),
}
"""Weighted 0.65 with no majority level: the rule accepts it, the route is review."""


def _answers(output: type[BaseModel], values: Values) -> tuple[Answer, ...]:
    out: list[Answer] = []
    for name, info in output.model_fields.items():
        value, kind = values[name], info.annotation
        if isinstance(value, tuple):
            assert isinstance(kind, type) and issubclass(kind, IntEnum)
            out.append(ScoreAnswer(key=name, levels=score_levels(kind), probabilities=value))
        else:
            out.append(NoulAnswer(key=name, p_yes=value))
    return tuple(out)


class Line:
    """One line's nodes, built the way a run stores them."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.iri = LINES[slug]
        self.nodes: list[GraphNodeType] = []
        self.claims: dict[str, Claim] = {}

    def source(self, name: str, url: str, *, day: date, text: str = LONG) -> SourceItem:
        s = SourceItem.new(
            line=self.iri, adapter="arxiv", url=url, title=name, text=text, fetched_at=at(day)
        )
        unit = Unit.cut(s, start=0, end=min(40, len(text)), granularity="sentence")
        claim = Claim.from_unit(unit, line=self.iri)
        self.claims[name] = claim
        self.nodes += [s, unit, claim]
        return s

    def fetch(self, day: date, sources: Sequence[SourceItem]) -> None:
        self.nodes.append(
            StageRecord.new(
                stage="fetch_keyword_arxiv",
                input_sha256=sha256_hex(f"{self.slug} {day}"),
                outputs=tuple(s.id for s in sources),
                completed_at=at(day),
            )
        )

    def prefilter(self, day: date, source: SourceItem, q0: float, n: int = 3) -> None:
        values = (q0,) + (0.1,) * (n - 1)
        self.nodes.append(
            Judgment.new(
                function="question_prefilter",
                subjects=(source.id,),
                model="jev-1.13.0",
                state_sha256=sha256_hex(f"pre {source.id}"),
                bundle_sha256=question_prefilter.ask(n).batched("source").sha256,
                answers=tuple(
                    NoulAnswer(key=f"q{i}_on_topic", p_yes=v) for i, v in enumerate(values)
                ),
                judged_at=at(day),
            )
        )

    def screen(self, day: date, source: SourceItem, question: Question, values: Values) -> None:
        self.nodes.append(
            Judgment.new(
                function="question_screening",
                subjects=(source.id, question.id),
                model="jev-1.13.0",
                state_sha256=sha256_hex(f"screen {source.id} {question.id}"),
                bundle_sha256=question_screening.BATCH_ASK.sha256,
                answers=_answers(question_screening.Answers, values),
                judged_at=at(day),
            )
        )

    def day(
        self,
        day: date,
        sections: Sequence[tuple[Question, Sequence[str], str]],
        *,
        writer: int,
        tokens: int,
    ) -> Report:
        """One line-run: a QuestionLog per (question, claim names, prose), and the Report."""
        report_id = Report.id_for(self.iri, day)
        claims: list[str] = []
        for question, names, text in sections:
            ids = tuple(self.claims[n].id for n in names)
            claims += ids
            self.nodes.append(
                QuestionLog.new(
                    question=question.id,
                    report=report_id,
                    run_date=day,
                    movement="new_evidence_same_answer",
                    text=text,
                    claims=ids,
                    logged_at=at(day),
                )
            )
        prose = "\n\n".join(text for _, _, text in sections if text) or None
        report = Report.new(
            line=self.iri,
            run_date=day,
            rendering="prose" if prose else "template",
            prose=prose,
            claims=tuple(claims),
            unjudged=(),
            partial=False,
            operations=Operations(
                jev_questions=30 + tokens % 7,
                jev_input_tokens=tokens,
                jev_output_tokens=tokens // 20,
                generation_input_tokens=0,
                generation_output_tokens=0,
                writer_calls=writer,
                cost_usd=0.0,
                rubric=(),
                fill_rate_previous=None,
            ),
        )
        self.nodes.append(report)
        return report


def _record(
    day: date,
    slug: str,
    report: Report,
    *,
    qs: Sequence[Question],
    review: Sequence[SourceItem],
    reasons: Sequence[str] = (),
) -> RunRecord:
    return RunRecord.new(
        started_at=at(day),
        finished_at=at(day) + timedelta(minutes=6),
        lines=(slug,),
        reasons=tuple(reasons),
        notify_configured=True,
        line_records=(
            LineRecord(
                slug=slug,
                report=report.id,
                questions=tuple(q.id for q in qs),
                review=tuple(s.id for s in review),
                claim_count=len(report.claims),
            ),
        ),
    )


def _arxiv(n: str) -> str:
    return f"https://arxiv.org/abs/{n}"


REASON = "edge: fetch failed: keyword/web_search 503 at https://api.example.org/search?q=x jrp:x"
"""A reason with a URL and a mark-like word in it: the note prints neither."""


def scenario() -> tuple[dict[str, list[GraphNodeType]], list[GraphNodeType], dict[str, date]]:
    """(line slug → nodes, pipeline nodes, opened notes) — the module docstring's store."""
    akc, edge = Line("akc"), Line("edge")
    mem, ev, tool = AKC["agent-memory"], AKC["memory-eval"], AKC["tool-use"]
    # W43 cohort
    a = [akc.source(f"a{i}", _arxiv(f"2610.{i:05d}"), day=d(10, 20)) for i in range(1, 6)]
    a.append(akc.source("a6", _arxiv("2610.00006"), day=d(10, 20), text=SHORT))
    akc.fetch(d(10, 20), a)
    for s, q0 in zip(a, (0.9, 0.9, 0.9, 0.9, 0.1, 0.9), strict=True):
        akc.prefilter(d(10, 20), s, q0)
    for s, values in zip(a[:4], (KEEP, KEEP, KEEP, DROP), strict=True):
        akc.screen(d(10, 20), s, mem, values)
    akc.day(d(10, 20), [], writer=0, tokens=900)
    akc.day(d(10, 21), [(mem, ["a1", "a2"], "記憶の差は大きい [1]。")], writer=1, tokens=1100)
    # W44 cohort
    b = [akc.source(f"b{i}", _arxiv(f"2610.{10 + i:05d}"), day=d(10, 27)) for i in range(1, 9)]
    akc.fetch(d(10, 27), b)
    for i, s in enumerate(b):
        akc.prefilter(d(10, 27), s, 0.9 if i < 6 else 0.2)
    for s, values in zip(b[:6], (KEEP, KEEP, KEEP, KEEP, REVIEW, DROP), strict=True):
        akc.screen(d(10, 27), s, mem, values)
    akc.day(d(10, 27), [], writer=0, tokens=1300)
    r28 = akc.day(
        d(10, 28), [(mem, ["b1", "b2", "b3"], "[1] と [2] と [3]。")], writer=1, tokens=1700
    )
    akc.day(d(10, 30), [(mem, ["a3"], "遅れて届いた [1]。")], writer=1, tokens=1900)
    # W45
    c1 = akc.source("c1", _arxiv("2611.00001"), day=d(11, 3))
    d1 = akc.source("d1", _arxiv("2611.00002"), day=d(11, 3))
    akc.fetch(d(11, 3), [c1, a[0], d1])
    akc.screen(d(11, 3), c1, tool, DROP)
    akc.screen(d(11, 3), d1, tool, DROP)
    r03 = akc.day(
        d(11, 3),
        [(mem, ["a1", "c1"], "新しい結果 [2]。"), (ev, ["d1"], "評価の指標 [1]。")],
        writer=2,
        tokens=4000,
    )
    e1 = edge.source("e1", "https://huggingface.co/papers/2610.00001", day=d(11, 4))
    edge.fetch(d(11, 4), [e1])
    edge.screen(d(11, 4), e1, EDGE["edge-q"], KEEP)
    r04 = edge.day(d(11, 4), [(EDGE["edge-q"], ["e1"], "同じ論文 [1]。")], writer=1, tokens=2000)
    # the author's ticks
    log28 = QuestionLog.id_for(mem.id, d(10, 28))
    log21 = QuestionLog.id_for(mem.id, d(10, 21))
    akc.nodes += [
        _label(log28, r28.id, "question_day", first=d(11, 3)),
        _label(log21, Report.id_for(akc.iri, d(10, 21)), "question_day", first=d(10, 22)),
        _label(akc.claims["a1"].id, Report.id_for(akc.iri, d(10, 21)), "claim", first=d(10, 22)),
    ]
    pipeline: list[GraphNodeType] = [
        _record(d(10, 28), "akc", r28, qs=(mem, ev, tool), review=[b[4]]),
        _record(d(11, 3), "akc", r03, qs=(mem, ev, tool), review=[b[4]]),
        _record(d(11, 4), "edge", r04, qs=tuple(EDGE.values()), review=[], reasons=[REASON]),
        Sighting.new(key="arxiv:2610.00011", first_seen=d(11, 1), place="graph"),
        Sighting.new(key="arxiv:2610.09999", first_seen=d(11, 5), place="adr"),
        Sighting.new(key="arxiv:2610.00012", first_seen=d(11, 2), place="graph", baseline=True),
        Sighting.new(key="doi:10.1234/x", first_seen=d(11, 2), place="adr", unsure=True),
        Sighting.new(key="url:example.org/a", first_seen=d(11, 3), place="graph"),
        Sighting.new(key="arxiv:2610.00013", first_seen=d(10, 1), place="graph"),
    ]
    opened = {
        "2026-10-21_jrp_akc.md": d(10, 22),
        "2026-10-28_jrp_akc.md": d(11, 3),
        "2026-11-03_jrp_akc.md": d(11, 4),
    }
    return {"akc": akc.nodes, "edge": edge.nodes}, pipeline, opened


def _label(subject: str, report: str, provenance: LabelProvenance, *, first: date) -> Label:
    label = Label.new(
        subject=subject,
        report=report,
        verdict="correct",
        provenance=provenance,
        harvested_at=at(d(11, 4)),
    )
    return label.model_copy(update={"first_harvested_at": at(first)})


def _ids(nodes: Sequence[GraphNodeType]) -> dict[str, GraphNodeType]:
    return {n.id: n for n in nodes}


def inputs(*, firehose: Mapping[str, int] | None = None) -> Inputs:
    lines, pipeline, opened = scenario()
    snapshot = Snapshot(
        lines={slug: _ids(nodes) for slug, nodes in lines.items()} | {"ans": {}},
        pipeline=_ids(pipeline),
        opened=opened,
        firehose=dict(firehose or dict.fromkeys(LINES, 0)),
    )
    specs = (LineSpec("akc", questions("akc")), LineSpec("edge", questions("edge")))
    return Inputs(snapshot=snapshot, lines=(*specs, LineSpec("ans", None)))


@pytest.fixture(scope="module")
def review() -> WeeklyReview:
    return weekly_review(inputs(), WEEK)


# -------------------------------------------------------------------------- week, stats


def test_a_week_parses_from_its_iso_label_and_the_default_is_the_last_complete_one():
    assert (WEEK.start, WEEK.end, WEEK.label, WEEK.short) == (d(11, 2), d(11, 8), "2026-W45", "W45")
    assert note_name(WEEK) == "2026-11-09_jrp_wbr.md"
    assert Week.last_complete(d(11, 9)) == WEEK  # Monday morning: the week just ended
    assert Week.last_complete(d(11, 8)) == WEEK.shifted(-1)  # Sunday: that week is not over
    for bad in ("2026-45", "2026-W54", "W45"):
        with pytest.raises(ValueError, match=r"(?i)week"):
            Week.parse(bad)


@pytest.mark.parametrize(
    ("k", "low", "high"), [(0, 0.0, 3.689), (1, 0.0253, 5.5716), (10, 4.7954, 18.3904)]
)
def test_the_poisson_interval_is_garwoods(k: int, low: float, high: float):
    got = poisson_interval(k)
    assert got == pytest.approx((low, high), abs=1e-3)


def test_wilson_and_the_delta_method():
    assert wilson(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-4)
    moved = shift(Measure(4), Measure(6))
    assert moved is not None
    assert moved == pytest.approx((math.log(1.5), math.sqrt(1 / 4 + 1 / 6)))
    assert shift(Measure(0), Measure(3)) is None  # no logarithm of 0
    assert Measure(2, 4).ln_var == pytest.approx(1 / 2 - 1 / 4)


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("https://arxiv.org/abs/2610.00001v2", "arxiv:2610.00001"),
        ("https://huggingface.co/papers/2610.00001", "arxiv:2610.00001"),
        ("https://doi.org/10.1145/3600000.1", "doi:10.1145/3600000.1"),
        ("https://github.com/Owner/Repo", "gh:owner/repo"),
        ("https://www.example.org/post/?utm_source=x", "url:example.org/post"),
    ],
)
def test_a_paper_key_takes_arxiv_then_doi_then_github_then_the_url(url: str, key: str):
    source = SourceItem.new(
        line=LINES["akc"], adapter="arxiv", url=url, title="t", text="x", fetched_at=NOW
    )
    assert paper_key(source) == key


# ------------------------------------------------------------------------------ numbers


def test_o1_counts_papers_once_by_key_with_each_sections_own_numbering(review: WeeklyReview):
    by_week = {w.week.short: w for w in review.o1}
    assert list(by_week) == ["W40", "W41", "W42", "W43", "W44", "W45"]
    assert [w.total for w in review.o1] == [0, 0, 0, 1, 4, 2]
    # W44: b1..b3 on 10-28, and a3, first cited on 10-30 (late for its cohort, still O1)
    # W45: c1 and d1; edge's e1 is a1's paper, so edge first-cites nothing
    assert dict(by_week["W45"].lines) == {
        "akc": (2, "live"),
        "edge": (0, "live"),
        "ans": (0, "insufficient-n"),
    }
    assert by_week["W45"].interval == pytest.approx(poisson_interval(2))
    assert [w.status for w in review.o1[:3]] == ["insufficient-n"] * 3  # no line ran


def test_o2_counts_fresh_paper_keys_the_author_saw_after_jrp_cited_them(review: WeeklyReview):
    # in: b1 (cited 10-28, seen 11-01: a hit) and an uncited key; out: baseline, unsure, a
    # URL key and a key seen 38 days before the week's end
    assert (review.o2.k, review.o2.n) == (1, 2)


def test_without_sightings_o2_is_being_measured():
    bare = inputs()
    pipeline = {k: v for k, v in bare.snapshot.pipeline.items() if not isinstance(v, Sighting)}
    got = weekly_review(replace(bare, snapshot=replace(bare.snapshot, pipeline=pipeline)), WEEK)
    assert (got.o2.k, got.o2.n) == (0, 0)
    assert "O2 著者の新出 key の先回り (graph と ADR のみ・上限寄り、直近 30 日): 測定中" in render(
        got, "ja"
    )


def test_the_mature_cohorts_break_o1_down_exactly(review: WeeklyReview):
    assert [c.short for c in review.cohorts] == ["W43", "W44"]
    everyone = review.groups[0]
    assert everyone.kind == "all"
    # a6 fails the text floor, a5 the prefilter, a4 is dropped; a3's post comes on day 10
    assert everyone.old == Funnel(new=6, on_topic=4, kept=3, posted=2, cited=1)
    assert everyone.new == Funnel(new=8, on_topic=6, kept=4, posted=3, cited=3)
    shifts = {r.name: r.shift for r in review.rows(everyone)}
    deltas = {name: moved[0] for name, moved in shifts.items() if moved is not None}
    assert set(deltas) == {"N_new", "N_ot", "p_sel", "p_ext", "p_wri", "O1_c"}
    identity = sum(deltas[n] for n in ("N_ot", "p_sel", "p_ext", "p_wri"))
    assert identity == pytest.approx(deltas["O1_c"])  # Δln O1_c is the sum of its factors
    assert shifts["N_ot"] == pytest.approx((math.log(6 / 4), math.sqrt(1 / 4 + 1 / 6)))
    rows = review.rows(everyone)
    assert not any(r.beyond_noise for r in rows)
    assert review.worst() is None


def test_an_immature_or_empty_cohort_has_no_breakdown():
    got = weekly_review(inputs(), WEEK.shifted(-1))  # W44: cohorts W42 (empty) and W43
    assert got.groups[0].old == Funnel()
    assert "分解: 比べられる成熟 cohort が 2 つそろわない" in render(got, "ja")


def test_the_factor_that_fell_beyond_noise_is_named(review: WeeklyReview):
    group = Group(
        "all",
        ("akc",),
        Funnel(new=2000, on_topic=600, kept=240, posted=100, cited=60),
        Funnel(new=1500, on_topic=360, kept=150, posted=60, cited=36),
    )
    fell = replace(review, groups=(group, *review.groups[1:]))
    worst = fell.worst()
    assert worst is not None and worst.name == "N_ot"  # ln(360/600) = -0.51, SE 0.07
    assert "雑音を超えて最も下がった因子は I 入口 の N_ot (Δln -0.51 ± 0.07)" in render(fell, "ja")


def test_lines_are_split_by_the_free_slots_of_the_weeks_notes(review: WeeklyReview):
    # akc 11-03: 3 open questions → 3 x 3 = 9 slots, 3 claims; edge 11-04: 2 → 4 x 2 = 8, 1
    assert [(s.line, s.free, s.capacity, s.slot_bound) for s in review.slots] == [
        ("akc", 6, 9, False),
        ("edge", 7, 8, False),
    ]
    kinds = {g.kind: g.lines for g in review.groups}
    assert kinds == {"all": ("akc", "edge", "ans"), "slot": (), "supply": ("akc", "edge")}


def test_a_question_that_did_not_move_shows_where_it_stopped(review: WeeklyReview):
    states = {(q.line, q.slug): q for q in review.questions}
    assert sum(q.moved for q in review.questions) == 2  # agent-memory, memory-eval
    assert len(review.questions) == 5  # the dropped question is not open
    chains = {
        key: (q.screened, q.kept, q.claimed, q.cited, q.stopped)
        for key, q in states.items()
        if not q.moved
    }
    assert chains == {
        ("akc", "tool-use"): (2, 0, 0, 0, "keep"),
        ("edge", "edge-q"): (1, 1, 1, 1, "delivered"),
        ("edge", "edge-quiet"): (0, 0, 0, 0, "screening"),
    }
    assert review.unset == ("ans",)


def test_repetition_and_novelty(review: WeeklyReview):
    # slots: a1 (posted 10-21) and e1 (a1's paper) of 4; Review: b5 shown on 10-28 again;
    # keyword results: c1, d1, e1 are new, a1 is not
    assert review.repeats.slots == (2, 4)
    assert review.repeats.review == (1, 1)
    assert review.repeats.keyword == (3, 4)


def test_delivery_and_resources(review: WeeklyReview):
    d_ = review.delivery
    assert dict(d_.runs) == {"akc": 1, "edge": 1}
    assert (d_.reports, d_.records) == (2, 2)
    assert d_.answers == 3 * len(question_screening.Answers.model_fields)
    assert (d_.writer_calls, d_.tokens_in, d_.tokens_out) == (3, 6000, 300)
    assert d_.reasons == (("edge: fetch failed: keyword/web_search 503 at &lt;url> jrp :x", 1),)


def test_the_authors_signal(review: WeeklyReview):
    a = review.author
    # one question-day tick first harvested in W45 (the W43 one and the claim tick are not);
    # two notes first seen opened in W45; one positive, first ticked 10-22
    assert (a.ticks, a.opened, a.positives, a.added, a.unknown) == (1, 2, 1, 0, 0)


def test_the_instruments_are_shown_by_their_status(review: WeeklyReview):
    assert dict(review.status) == {
        "firehose.arxiv": "insufficient-n",
        "firehose.hf": "insufficient-n",
        "citation": "insufficient-n",
        "used.vault": "declared-degenerate",
        "writer_calls": "live",
        "jev_tokens": "live",
        "o1": "live",
        "claims_posted": "live",
        "label.first_harvest": "live",
        "opened": "live",
    }
    assert review.exceptions() == 4  # three questions that did not move, edge's O1 of 0


def test_a_failing_instrument_is_an_exception_and_hides_the_numbers_it_measures():
    """With akc's firehose on, no akc run left an arXiv listing: missing, in the week and in
    both cohorts' windows, so the intake factors print the word instead of a number."""
    got = weekly_review(inputs(firehose={"akc": 2, "edge": 0, "ans": 0}), WEEK)
    assert got.status["firehose.arxiv"] == "missing"
    assert [g.intake for g in got.gates] == ["missing", "missing"]
    text = render(got, "ja")
    assert "- 計器 firehose.arxiv: 欠落 (akc 2026-11-03)" in text
    assert "| I 入口 | N_ot 問いに合う新規の論文 | 欠落 | 欠落 | — | — |" in text
    assert "| X 根拠化 | p_ext claim が載った | 0.67 (2/3) | 0.75 (3/4) | +0.12 | 0.50 |" in text
    assert "firehose.arxiv (I 入口): 欠落 — akc 2026-11-03" in text


# ------------------------------------------------------------------------------ the note


def test_the_note_holds_no_source_key_and_no_jrp_mark(review: WeeklyReview):
    for lang in ("ja", "en", "zh"):
        text = render(review, lang)
        assert keys_of_text(text) == set(), lang
        assert "jrp:" not in text
        assert "https://" not in text


HOSTILE = (
    "akc: raised (X: ![x](HTTPS://e.example/p.png) `$= dv.view(1)` <img src=x onerror=y> "
    "[[Secret note]] %%hide <!-- arXiv:2611.12345 github.com/owner/repo 10.1234/abc JRP:z"
)
"""A reason quoting an exception about a third-party excerpt: an embed of a remote image, an
inline DataviewJS query, HTML, a wikilink, an Obsidian comment, an HTML comment left open,
and source keys with no scheme or in upper case."""
LIVE = ("![", "`$=", "`=", "<img", "[[", "%%", "<!--", "http", "jrp:")
"""What would execute, fetch or be read as a mark in Obsidian, in lower case."""


def test_a_reason_from_outside_is_printed_but_never_executes_or_fetches():
    """DEGRADED reasons and a broken invariant (here: a listed note name seen before its own
    date) reach the note escaped, with their source keys replaced."""
    bare = inputs()
    tick = RunRecord.new(started_at=at(d(11, 5)), reasons=(HOSTILE,))
    early = "2026-11-09_jrp_x<!--[[y]]%%![z](https://e.example/q.png).md"
    snapshot = replace(
        bare.snapshot,
        pipeline={**bare.snapshot.pipeline, tick.id: tick},
        opened={**bare.snapshot.opened, early: d(11, 5)},
    )
    got = weekly_review(replace(bare, snapshot=snapshot), WEEK)
    assert got.status["opened"] == "contradiction"
    for lang in ("ja", "en", "zh"):
        text = render(got, lang)
        assert [x for x in LIVE if x in text.lower()] == [], lang
        assert keys_of_text(text) == set(), lang
    text = render(got, "ja")
    assert "  - akc: raised (X: !\\[x](&lt;url> \\`$\\= dv.view(1)` &lt;img src=x " in text
    assert "\\[\\[Secret note]] \\%\\%hide &lt;!-- &lt;url> &lt;url> &lt;url> JRP :z (1)" in text
    assert "計器 opened: 矛盾 (tick 全体 2026-11-05: 2026-11-09_jrp_x&lt;!--\\[\\[y]]" in text


def test_a_cut_never_reopens_what_sanitize_closed():
    """Cut at every length, the printed reason stays a prefix of the whole, holds no live
    syntax and ends on no half-written escape or entity."""
    whole = printable(HOSTILE, limit=10_000)
    for limit in range(1, len(whole) + 1):
        cut = printable(HOSTILE, limit)
        assert len(cut) <= limit and whole.startswith(cut), limit
        assert [x for x in LIVE if x in cut.lower()] == [], (limit, cut)
        assert not cut.endswith("\\") and not re.search(r"&[#\w]*$", cut), (limit, cut)
    assert printable("x" * 200) == "x" * PRINTABLE_CHARS


def test_the_note_reads_in_every_language(review: WeeklyReview):
    en = render(review, "en")
    assert [line for line in en.splitlines() if CJK.search(line)] == []
    assert "## 3. Breakdown (mature cohorts W43 → W44, 7 days from the first fetch)" in en
    zh = render(review, "zh")
    assert "## 9. 仪表" in zh


def test_the_note_matches_its_golden(review: WeeklyReview):
    """The rendered note of the scenario, byte for byte. A deliberate change of the note's
    text regenerates it: JRP_GOLDEN_UPDATE=1 uv run pytest tests/test_wbr.py -k golden."""
    path = GOLDEN / "2026-W45.ja.md"
    text = render(review, "ja")
    if os.environ.get(GOLDEN_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")


def test_the_notes_name_is_outside_the_harvest_glob_and_the_used_scan(
    tmp_path: Path, review: WeeklyReview
):
    vault = tmp_path / "vault"
    note = vault / "daily-research" / note_name(WEEK)
    note.parent.mkdir(parents=True)
    note.write_text(render(review, "ja"), encoding="utf-8")
    assert is_jrp_name(note)
    for slug in LINES:
        assert report_notes(vault, slug) == []
    assert scan_documents([], vault).found == {}


def test_a_track_cannot_take_the_reviews_slug(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[tracks.wbr]\nname = "W"\n', encoding="utf-8")
    with pytest.raises(ReservedSlug, match="reserved"):
        load_tracks(cfg)
    env = {"JRP_DAILY_RESEARCH_CONFIG": str(cfg), "JRP_CODEX_AUTH": str(tmp_path / "none")}
    checks = {c.name: c for c in doctor(env)}
    assert not checks["config"].ok and "ReservedSlug" in checks["config"].detail


# ------------------------------------------------------------------------- files, the CLI


def scenario_on_disk(tmp_path: Path) -> dict[str, str]:
    """The scenario on disk: config.toml, questions/, the store and a vault dir."""
    (tmp_path / "config.toml").write_text(CONFIG, encoding="utf-8")
    qdir = tmp_path / "questions"
    qdir.mkdir()
    for slug, text in QUESTION_FILES.items():
        (qdir / f"{slug}.md").write_text(text, encoding="utf-8")
    store = GraphStore(tmp_path / "store")
    lines, pipeline, opened = scenario()
    for slug, nodes in lines.items():
        store.line(slug).put(nodes)
    store.pipeline().put(pipeline)
    rows = [json.dumps({"note": n, "first_seen": day.isoformat()}) for n, day in opened.items()]
    (store.root / OPENED_FILE).parent.mkdir(parents=True)
    (store.root / OPENED_FILE).write_text("\n".join(rows) + "\n", encoding="utf-8")
    (tmp_path / "vault").mkdir()
    return {
        "JRP_DAILY_RESEARCH_CONFIG": str(tmp_path / "config.toml"),
        "JRP_QUESTIONS_DIR": str(qdir),
        "JRP_STORE_DIR": str(store.root),
        "JRP_VAULT_DIR": str(tmp_path / "vault"),
    }


def _files(root: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.relative_to(root) != WEEKLY_FILE
    }


def _no_call(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"no request expected without ANTHROPIC_API_KEY: {request.url}")


async def _write(env: Mapping[str, str], out: Path, now: datetime = NOW) -> Written:
    """The review with a monitoring-judge client that fails on any request: the env of these
    tests has no ANTHROPIC_API_KEY."""
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(_no_call)) as http:
        return await write_weekly_review(env, week=WEEK, out=out, now=now, http=http)


async def test_it_reads_the_store_and_writes_only_its_note_and_one_row(
    tmp_path: Path, review: WeeklyReview
):
    env = scenario_on_disk(tmp_path)
    store = Path(env["JRP_STORE_DIR"])
    before = _files(store)
    out = tmp_path / "out"
    written = await _write(env, out)
    assert _files(store) == before  # same bytes, same mtimes: nothing in the store moved
    assert written.note == out / "2026-11-09_jrp_wbr.md"
    assert sorted(p.name for p in out.iterdir()) == ["2026-11-09_jrp_wbr.md"]
    assert written.review == replace(review, monitor=written.review.monitor)
    assert written.note.read_text(encoding="utf-8") == render(written.review, "ja")
    assert not (store / LEDGER_FILE).exists()  # no key: nothing called, nothing written
    (line,) = (store / WEEKLY_FILE).read_text(encoding="utf-8").splitlines()
    row: Any = json.loads(line)
    assert row == json.loads(json.dumps(written.row))
    assert (row["week"], row["generated_at"], row["exceptions"]) == ("2026-W45", NOW.isoformat(), 4)
    assert (row["monitor"]["fidelity"], row["monitor"]["precision"]) == (
        {"asked": 3, "judged": 0, "passed": 0, "stop": "no-key", "failed": []},
        {"asked": 2, "judged": 0, "passed": 0, "stop": "no-key", "failed": []},
    )
    assert [w["count"] for w in row["o1"]] == [0, 0, 0, 1, 4, 2]
    assert row["breakdown"]["all"]["old"] == {
        "new": 6,
        "on_topic": 4,
        "kept": 3,
        "posted": 2,
        "cited": 1,
    }
    await _write(env, out, NOW + timedelta(hours=1))
    assert len((store / WEEKLY_FILE).read_text(encoding="utf-8").splitlines()) == 2


async def test_a_store_with_an_older_additive_context_is_read_in_memory_and_left_as_is(
    tmp_path: Path, review: WeeklyReview
):
    env = scenario_on_disk(tmp_path)
    path = Path(env["JRP_STORE_DIR"]) / "lines" / "akc.jsonld"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["@context"] = {k: v for k, v in CONTEXT.items() if k != "claim_count"}
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="旧 schema"):
        Partition(path).load()  # the run would migrate it first; wbr does not
    before = (path.stat().st_mtime_ns, path.read_bytes())
    written = await _write(env, tmp_path / "out")
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before
    assert written.review == replace(review, monitor=written.review.monitor)


def _main(monkeypatch: pytest.MonkeyPatch, env: Mapping[str, str], *argv: str) -> int:
    # the developer's own key must never reach the monitoring judge of a test
    for key in ("JRP_NOTE_LANG", "OTEL_EXPORTER_OTLP_ENDPOINT", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return cli.main(["wbr", *argv])


def test_an_incompatible_store_stops_with_one_line_and_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    env = scenario_on_disk(tmp_path)
    path = Path(env["JRP_STORE_DIR"]) / "lines" / "edge.jsonld"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["@context"] = {**CONTEXT, "text": "schema:description"}
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert _main(monkeypatch, env, "--week", "2026-W45", "--out", str(tmp_path / "out")) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "store/lines/edge.jsonld は旧 schema" in err
    assert not (tmp_path / "out").exists()
    assert not (Path(env["JRP_STORE_DIR"]) / WEEKLY_FILE).exists()


def test_the_cli_writes_into_the_vaults_daily_research_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    env = scenario_on_disk(tmp_path)
    assert _main(monkeypatch, {**env, "JRP_NOTE_LANG": "en"}, "--week", "2026-W45") == 0
    note = tmp_path / "vault" / "daily-research" / "2026-11-09_jrp_wbr.md"
    assert capsys.readouterr().out == f"{note}\n"
    text = note.read_text(encoding="utf-8")
    assert text.startswith("# jrp weekly review 2026-W45")
    assert "- OUT precision sample (monitoring judge, up to 12 O1 papers: does the claim " in text
    assert "question forward): not measured (no key)" in text


def test_the_cli_refuses_a_week_that_is_not_an_iso_week(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(SystemExit) as stopped:
        _main(monkeypatch, {}, "--week", "2026-45")
    assert stopped.value.code == 2


def test_the_cli_says_what_is_missing_without_a_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    env = scenario_on_disk(tmp_path)
    monkeypatch.delenv("JRP_VAULT_DIR", raising=False)
    env = {k: v for k, v in env.items() if k != "JRP_VAULT_DIR"}
    assert _main(monkeypatch, env, "--week", "2026-W45") == 1
    assert "JRP_VAULT_DIR" in capsys.readouterr().err


def test_an_empty_store_reads_as_no_data_everywhere(tmp_path: Path):
    empty = Inputs(snapshot=Snapshot(lines={"akc": {}}), lines=(LineSpec("akc", questions("akc")),))
    got = weekly_review(empty, WEEK)
    text = render(got, "ja")
    assert got.o1[-1].status == "insufficient-n" and got.exceptions() == 3
    assert "| O1 本文で初めて引用された論文 | データ不足 |" in text
    assert "未計測 (この週の RunRecord に Review が無い)" in text


@pytest.mark.parametrize(
    ("author", "shown"),
    [
        (AuthorSignal(0, 0, 3, 2, 0), "recommendation の正例 3 件 (14 日で +2)"),
        (
            AuthorSignal(0, 0, 3, 0, 3),
            "recommendation の正例 3 件 (初回のチェックの日が記録より前)",
        ),
        (AuthorSignal(0, 0, 0, 0, 0), "recommendation の正例 0 件 (14 日変化なし)"),
    ],
)
def test_the_positives_say_whether_they_moved(
    review: WeeklyReview, author: AuthorSignal, shown: str
):
    assert shown in render(replace(review, author=author), "ja")


def test_o2_gets_a_rate_from_20_keys_on(review: WeeklyReview):
    text = render(replace(review, o2=O2(k=5, n=25)), "en")
    assert "last 30 days): 0.20 (Wilson 0.09-0.39, 5/25)" in text


def test_a_meter_that_is_not_live_prints_its_word_per_o1(review: WeeklyReview):
    broken = replace(review, status={**review.status, "writer_calls": "contradiction"})
    assert "書き手の呼び出し 矛盾" in render(broken, "ja")
    unmetered = replace(review, delivery=replace(review.delivery, tokens_in=None))
    assert "Jev token 入力 未計測 / 出力 150.0" in render(unmetered, "ja")


def test_the_reasons_are_cut_after_the_most_frequent(review: WeeklyReview):
    reasons = tuple((f"akc: reason {i}", 20 - i) for i in range(REASONS_SHOWN + 2))
    delivery: Delivery = replace(review.delivery, reasons=reasons)
    text = render(replace(review, delivery=delivery), "ja")
    assert "  - akc: reason 0 (20)" in text and "  - ほか 2 件" in text
    assert "reason 9" not in text
