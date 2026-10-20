"""The instrument registry (pipeline.registry): each instrument is healthy on a healthy
week, one injected fault makes it fail, and every instrument in REGISTRY has a fault here
(a new instrument without one fails verify). The calendar is pinned on synthetic dates."""

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import get_args

import pytest

from jev_research_pipeline import note_text as t
from jev_research_pipeline.model import (
    Claim,
    GraphNodeType,
    Label,
    LineRecord,
    Operations,
    QuestionLog,
    Report,
    RunRecord,
    Sighting,
    SourceItem,
    StageRecord,
    Unit,
    content_id,
    sha256_hex,
)
from jev_research_pipeline.note_text import LANGS
from jev_research_pipeline.pipeline.registry import (
    ARXIV_HOLIDAYS,
    ARXIV_STAGE,
    CITATION_STAGE,
    FAILURES,
    HF_STAGE,
    METERS_SINCE,
    REGISTRY,
    STATUS_WORDS,
    TICK,
    Instrument,
    InstrumentStatus,
    Snapshot,
    Status,
    arxiv_quiet,
    hf_quiet,
    line_runs,
    read_snapshot,
    status,
    statuses,
)
from jev_research_pipeline.reduction.opened import OPENED_FILE
from jev_research_pipeline.store import GraphStore

from . import builders as b

JST = timezone(timedelta(hours=9))
START = date(2026, 10, 26)  # a Monday, after every instrument's `since`
DAYS = tuple(START + timedelta(days=i) for i in range(7))
END = DAYS[-1]
SLUG = "akc"
REGISTRY_BY_ID = {i.id: i for i in REGISTRY}


def at(day: date, hour: int = 5) -> datetime:
    return datetime.combine(day, time(hour), JST)


def _fake_outputs(stage: str, day: date, n: int) -> tuple[str, ...]:
    return tuple(content_id("source", stage, day.isoformat(), str(k)) for k in range(n))


def _stage(stage: str, day: date, n: int, *, hour: int = 5) -> StageRecord:
    return StageRecord.new(
        stage=stage,
        input_sha256=sha256_hex(f"{stage} {day}"),
        outputs=_fake_outputs(stage, day, n),
        completed_at=at(day, hour),
    )


def _source(day: date) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url=f"https://arxiv.org/abs/2610.{day.day:05d}",
        title=f"Paper of {day}",
        text=b.SOURCE_TEXT,
        fetched_at=at(day),
    )


def _claim(day: date) -> tuple[SourceItem, Unit, Claim]:
    source = _source(day)
    unit = Unit.cut(source, start=20, end=len(b.SOURCE_TEXT), granularity="sentence")
    return source, unit, Claim.from_unit(unit, line=b.LINE_IRI)


def _report(day: date, i: int) -> Report:
    return Report.new(
        line=b.LINE_IRI,
        run_date=day,
        rendering="prose",
        prose="本文 [1]",
        claims=(_claim(day)[2].id,),
        unjudged=(),
        partial=False,
        operations=Operations(
            jev_questions=10 + i,
            jev_input_tokens=1000 + i,
            jev_output_tokens=50,
            generation_input_tokens=100,
            generation_output_tokens=100,
            writer_calls=2,
            cost_usd=0.0,
            rubric=(),
            fill_rate_previous=None,
        ),
    )


def _log(day: date, text: str = "根拠がある [1]。") -> QuestionLog:
    source, _, claim = _claim(day)
    return QuestionLog.new(
        question=b.question().id,
        report=Report.id_for(b.LINE_IRI, day),
        run_date=day,
        movement="new_evidence_same_answer",
        text=text,
        claims=(claim.id,),
        sources=(source.id,),
        logged_at=at(day),
    )


def _label(day: date) -> Label:
    """A tick on the previous day's note, first harvested this morning and seen again by
    every harvest since (the latest one: the morning of END)."""
    before = day - timedelta(days=1)
    label = Label.new(
        subject=_claim(before)[2].id,
        report=Report.id_for(b.LINE_IRI, before),
        verdict="correct",
        provenance="claim",
        harvested_at=at(END),
    )
    return label.model_copy(update={"first_harvested_at": at(day)})


def _run_record(day: date, *, wrote: bool = True) -> RunRecord:
    records = (
        (LineRecord(slug=SLUG, report=Report.id_for(b.LINE_IRI, day), claim_count=1),)
        if wrote
        else ()
    )
    return RunRecord.new(
        started_at=at(day),
        finished_at=at(day) + timedelta(minutes=6),
        lines=(SLUG,),
        reasons=() if wrote else (f"{SLUG}: raised (RuntimeError: boom)",),
        line_records=records,
    )


def _ids(nodes: Iterable[GraphNodeType]) -> dict[str, GraphNodeType]:
    return {n.id: n for n in nodes}


def healthy() -> Snapshot:
    """One line run every morning of the week 2026-10-26..11-01, everything working: the
    firehose empty only where the calendar says so, one new cited source a day, the writer
    and Jev metered, one new tick and one opened note a day from the second day on."""
    line: list[GraphNodeType] = []
    pipeline: list[GraphNodeType] = [
        Sighting.new(key="arxiv:2610.00001", first_seen=START, place="graph")
    ]
    opened: dict[str, date] = {}
    for i, day in enumerate(DAYS):
        line += [*_claim(day), _report(day, i), _log(day)]
        line.append(_stage(ARXIV_STAGE, day, 0 if arxiv_quiet(at(day)) else 100 + i))
        line.append(_stage(HF_STAGE, day, 0 if hf_quiet(at(day)) else 20 + i))
        line.append(_stage(CITATION_STAGE, day, 0))
        pipeline.append(_run_record(day))
        if i:
            line.append(_label(day))
            opened[f"{day - timedelta(days=1)}_jrp_{SLUG}.md"] = day
    return Snapshot(lines={SLUG: _ids(line)}, pipeline=_ids(pipeline), opened=opened)


def _put(snapshot: Snapshot, *nodes: GraphNodeType) -> Snapshot:
    return replace(snapshot, lines={SLUG: {**snapshot.lines[SLUG], **_ids(nodes)}})


def _drop(snapshot: Snapshot, *ids: str) -> Snapshot:
    kept = {k: v for k, v in snapshot.lines[SLUG].items() if k not in ids}
    return replace(snapshot, lines={SLUG: kept})


def _report_of(snapshot: Snapshot, day: date) -> Report:
    report = snapshot.lines[SLUG][Report.id_for(b.LINE_IRI, day)]
    assert isinstance(report, Report)
    return report


def _ops(snapshot: Snapshot, day: date, **update: object) -> Snapshot:
    report = _report_of(snapshot, day)
    ops = report.operations.model_copy(update=update)
    return _put(snapshot, report.model_copy(update={"operations": ops}))


def _check(instrument: Instrument, snapshot: Snapshot) -> InstrumentStatus:
    return status(instrument, snapshot, start=START, end=END)


def _cell(result: InstrumentStatus, day: date, line: str = SLUG) -> Status:
    cells: list[Status] = [
        c.status
        for c in result.cells
        if c.observation.run_date == day and c.observation.line == line
    ]
    (cell,) = cells
    return cell


# --------------------------------------------------------------------------- the drill

type Fault = Callable[[Snapshot, Instrument], tuple[Snapshot, Instrument]]

WED, THU = date(2026, 10, 28), date(2026, 10, 29)


def _lapsed(snapshot: Snapshot, instrument: Instrument) -> tuple[Snapshot, Instrument]:
    """The declaration was not renewed: its review_by is behind the window."""
    assert instrument.declared is not None
    declared = replace(instrument.declared, review_by=START - timedelta(days=1))
    return snapshot, replace(instrument, declared=declared)


def _dead_arxiv(snapshot: Snapshot, instrument: Instrument) -> tuple[Snapshot, Instrument]:
    """Wednesday's listing came back empty: arXiv announced on Tuesday evening."""
    return _put(snapshot, _stage(ARXIV_STAGE, WED, 0)), instrument


def _failed_hf(snapshot: Snapshot, instrument: Instrument) -> tuple[Snapshot, Instrument]:
    """Thursday's HF daily fetch failed, so it left no StageRecord."""
    return _drop(snapshot, _stage(HF_STAGE, THU, 0).id), instrument


def _silent_writer(snapshot: Snapshot, instrument: Instrument) -> tuple[Snapshot, Instrument]:
    """The writer meter reads 0 on a day the note has prose this run wrote."""
    return _ops(snapshot, WED, writer_calls=0), instrument


def _silent_jev(snapshot: Snapshot, instrument: Instrument) -> tuple[Snapshot, Instrument]:
    """The Jev token meter reads 0 on a day Jev was asked 12 questions."""
    return _ops(snapshot, WED, jev_input_tokens=0), instrument


def _uncited(snapshot: Snapshot, instrument: Instrument) -> tuple[Snapshot, Instrument]:
    """Two runs in a row whose prose cites nothing."""
    return _put(snapshot, _log(WED, "根拠がない。"), _log(THU, "根拠がない。")), instrument


def _unposted(snapshot: Snapshot, instrument: Instrument) -> tuple[Snapshot, Instrument]:
    """Two notes in a row with no claim on them."""
    empty = [_report_of(snapshot, d).model_copy(update={"claims": ()}) for d in (WED, THU)]
    return _put(snapshot, *empty), instrument


def _forgotten_first(snapshot: Snapshot, instrument: Instrument) -> tuple[Snapshot, Instrument]:
    """A re-harvest dropped the first harvest of a tick on a note written this week."""
    return _put(snapshot, _label(WED).model_copy(update={"first_harvested_at": None})), instrument


def _opened_early(snapshot: Snapshot, instrument: Instrument) -> tuple[Snapshot, Instrument]:
    """A note listed as opened the day before it was written."""
    opened = {**snapshot.opened, f"{WED}_jrp_{SLUG}.md": WED - timedelta(days=1)}
    return replace(snapshot, opened=opened), instrument


FAULTS: dict[str, tuple[Fault, Status]] = {
    "firehose.arxiv": (_dead_arxiv, "unexplained-zero"),
    "firehose.hf": (_failed_hf, "missing"),
    "citation": (_lapsed, "unexplained-zero"),
    "used.vault": (_lapsed, "unexplained-zero"),
    "writer_calls": (_silent_writer, "contradiction"),
    "jev_tokens": (_silent_jev, "contradiction"),
    "o1": (_uncited, "unexplained-zero"),
    "claims_posted": (_unposted, "unexplained-zero"),
    "label.first_harvest": (_forgotten_first, "contradiction"),
    "opened": (_opened_early, "contradiction"),
}
"""One injected fault per instrument and the status it must turn the instrument into."""
HEALTHY: dict[str, Status] = {
    "citation": "declared-degenerate",
    "used.vault": "declared-degenerate",
}
"""The status of a healthy week where it is not live: declared 0s."""


def test_every_instrument_has_a_fault():
    """An instrument nobody has broken on purpose is not known to report a break."""
    assert set(REGISTRY_BY_ID) == set(FAULTS)
    assert len(REGISTRY_BY_ID) == len(REGISTRY)  # ids are unique


@pytest.mark.parametrize("name", sorted(FAULTS))
def test_one_fault_stops_the_instrument_being_healthy(name: str):
    instrument = REGISTRY_BY_ID[name]
    fault, want = FAULTS[name]
    before = healthy()
    assert _check(instrument, before).status == HEALTHY.get(name, "live")
    after, broken = fault(before, instrument)
    assert (after, broken) != (before, instrument)  # the fault changed what is read
    got = _check(broken, after)
    assert got.status == want
    assert got.status in FAILURES


def test_a_healthy_week_is_healthy_everywhere():
    got = {s.id: s.status for s in statuses(healthy(), start=START, end=END)}
    assert got == {i.id: HEALTHY.get(i.id, "live") for i in REGISTRY}
    assert list(got) == [i.id for i in REGISTRY]


# --------------------------------------------------------------------------- calendar


def test_arxiv_is_empty_on_sunday_and_monday_mornings_and_two_days_after_a_holiday():
    week = [date(2026, 10, 11) + timedelta(days=i) for i in range(14)]  # Sun 10-11 .. Sat 10-24
    quiet = {d for d in week if arxiv_quiet(at(d))}
    assert quiet == {
        date(2026, 10, 11),  # Sunday
        date(2026, 10, 12),  # Monday (also the holiday itself: its own run reads Sunday ET)
        date(2026, 10, 14),  # two days after the 10-12 holiday
        date(2026, 10, 18),
        date(2026, 10, 19),
    }
    assert date(2026, 10, 12) in ARXIV_HOLIDAYS


def test_the_arxiv_calendar_follows_the_hour_of_the_fetch():
    """At 15:00 JST it is already the same day in EST: Monday afternoon reads Monday's feed
    (Sunday evening's announcement), Saturday afternoon reads Saturday's empty one."""
    assert arxiv_quiet(at(date(2026, 10, 19), 5))
    assert not arxiv_quiet(at(date(2026, 10, 19), 15))
    assert arxiv_quiet(at(date(2026, 10, 24), 15))
    assert not arxiv_quiet(datetime(2026, 10, 23, 4, 59, tzinfo=UTC))  # Thu 23:59 EST


def test_hf_daily_is_empty_when_the_utc_day_before_is_a_weekend():
    week = [date(2026, 10, 19) + timedelta(days=i) for i in range(7)]  # Mon .. Sun
    assert {d for d in week if hf_quiet(at(d))} == {date(2026, 10, 19), date(2026, 10, 20)}
    assert not hf_quiet(at(date(2026, 10, 20), 10))  # 01:00 UTC Tuesday asks for Monday


def test_a_healthy_week_reads_the_calendar_zeros_as_expected():
    arxiv = _check(REGISTRY_BY_ID["firehose.arxiv"], healthy())
    hf = _check(REGISTRY_BY_ID["firehose.hf"], healthy())
    assert [_cell(arxiv, d) for d in DAYS] == ["expected-zero", *["live"] * 5, "expected-zero"]
    assert [_cell(hf, d) for d in DAYS] == [*["expected-zero"] * 2, *["live"] * 5]


def test_a_listing_on_a_day_the_calendar_says_is_empty_contradicts_it():
    got = _check(REGISTRY_BY_ID["firehose.arxiv"], _put(healthy(), _stage(ARXIV_STAGE, START, 5)))
    assert _cell(got, START) == "contradiction"
    assert got.status == "contradiction"


def test_the_same_listing_three_runs_in_a_row_is_stuck():
    same = [_stage(ARXIV_STAGE, d, 300) for d in DAYS[1:4]]
    got = _check(REGISTRY_BY_ID["firehose.arxiv"], _put(healthy(), *same))
    assert [_cell(got, d) for d in DAYS[1:5]] == ["live", "live", "stuck", "live"]
    assert got.status == "stuck"


def test_a_failed_arxiv_fetch_is_missing_not_zero():
    got = _check(REGISTRY_BY_ID["firehose.arxiv"], _drop(healthy(), _stage(ARXIV_STAGE, WED, 0).id))
    assert _cell(got, WED) == "missing"


def test_a_line_without_the_firehose_has_no_firehose_cells():
    no_stages = _drop(
        healthy(), *(_stage(s, d, 0).id for d in DAYS for s in (ARXIV_STAGE, HF_STAGE))
    )
    off = replace(no_stages, firehose={SLUG: 0})
    assert _check(REGISTRY_BY_ID["firehose.arxiv"], off).cells == ()
    assert _check(REGISTRY_BY_ID["firehose.arxiv"], off).status == "insufficient-n"
    arxiv_only = replace(healthy(), firehose={SLUG: 1})
    assert _check(REGISTRY_BY_ID["firehose.hf"], arxiv_only).cells == ()
    assert _check(REGISTRY_BY_ID["firehose.arxiv"], arxiv_only).status == "live"


def test_citation_cells_exist_only_where_cites_requests_went_out():
    """A run sends `cites:` only for papers its line accepted: no record is no cell."""
    snapshot = _drop(healthy(), _stage(CITATION_STAGE, WED, 0).id)
    got = _check(REGISTRY_BY_ID["citation"], snapshot)
    assert WED not in {c.observation.run_date for c in got.cells}
    assert got.status == "declared-degenerate"
    found = _check(REGISTRY_BY_ID["citation"], _put(healthy(), _stage(CITATION_STAGE, WED, 4)))
    assert _cell(found, WED) == "live"
    assert found.status == "declared-degenerate"  # one find does not void the declaration


# ------------------------------------------------------------------ line-runs and since


def test_a_line_that_raised_is_missing_from_every_per_line_instrument():
    raised = replace(
        _drop(
            healthy(),
            Report.id_for(b.LINE_IRI, WED),
            _log(WED).id,
            _stage(ARXIV_STAGE, WED, 0).id,
            _stage(HF_STAGE, WED, 0).id,
        ),
    )
    pipeline = {**raised.pipeline, _run_record(WED).id: _run_record(WED, wrote=False)}
    snapshot = replace(raised, pipeline=pipeline)
    for name in (
        "firehose.arxiv",
        "firehose.hf",
        "writer_calls",
        "jev_tokens",
        "o1",
        "claims_posted",
    ):
        got = _check(REGISTRY_BY_ID[name], snapshot)
        assert _cell(got, WED) == "missing", name
        assert got.status == "missing", name


def test_a_picked_line_with_no_open_question_ran_nothing():
    record = RunRecord.new(started_at=at(WED, 12), lines=(SLUG,))
    snapshot = replace(healthy(), pipeline={**healthy().pipeline, record.id: record})
    assert [r.run_date for r in line_runs(snapshot)] == list(DAYS)
    assert line_runs(snapshot)[2].started_at == at(WED)


def test_a_rerun_that_raised_keeps_the_report_the_first_run_wrote():
    raised = RunRecord.new(
        started_at=at(WED, 9), lines=(SLUG,), reasons=(f"{SLUG}: raised (TimeoutError: )",)
    )
    snapshot = replace(healthy(), pipeline={**healthy().pipeline, raised.id: raised})
    (wed,) = [r for r in line_runs(snapshot) if r.run_date == WED]
    assert (wed.started_at, wed.report) == (at(WED), _report_of(healthy(), WED))


def test_a_same_day_rerun_that_reuses_its_sections_calls_no_writer():
    """The second tick's Report overwrites the first; its section is the first tick's
    QuestionLog (logged_at of the first tick), so no prose was written and 0 calls agree."""
    rerun = RunRecord.new(
        started_at=at(WED, 9),
        lines=(SLUG,),
        line_records=(LineRecord(slug=SLUG, report=Report.id_for(b.LINE_IRI, WED)),),
    )
    snapshot = _ops(
        replace(healthy(), pipeline={**healthy().pipeline, rerun.id: rerun}),
        WED,
        writer_calls=0,
    )
    got = _check(REGISTRY_BY_ID["writer_calls"], snapshot)
    assert _cell(got, WED) == "expected-zero"
    assert got.status == "live"
    assert [r.started_at for r in line_runs(snapshot) if r.run_date == WED] == [at(WED, 9)]


def test_a_store_from_before_run_records_is_read_from_its_reports():
    """Every instrument reads the Reports, except writer_calls: a line-run with no RunRecord
    is none of its cells, so it has too few readings rather than a reading."""
    snapshot = replace(healthy(), pipeline={})
    runs = line_runs(snapshot)
    assert [(r.run_date, r.started_at) for r in runs] == [(d, None) for d in DAYS]
    assert {s.id: s.status for s in statuses(snapshot, start=START, end=END)} == {
        i.id: HEALTHY.get(i.id, "live") for i in REGISTRY
    } | {"writer_calls": "insufficient-n"}


def test_a_line_run_without_its_run_record_is_no_writer_cell():
    """Wednesday's RunRecord is gone and its Report says 0 writer calls beside a section with
    prose (written, or reused from an earlier run: nothing tells which): no cell, so no
    contradiction; the other days read as before."""
    record = _run_record(WED)
    pipeline = {k: v for k, v in healthy().pipeline.items() if k != record.id}
    snapshot = _ops(replace(healthy(), pipeline=pipeline), WED, writer_calls=0)
    got = _check(REGISTRY_BY_ID["writer_calls"], snapshot)
    assert WED not in {c.observation.run_date for c in got.cells}
    assert len(got.cells) == len(DAYS) - 1 and got.status == "live"
    assert _check(REGISTRY_BY_ID["writer_calls"], _ops(healthy(), WED, writer_calls=0)).status == (
        "contradiction"
    )


def test_a_line_the_snapshot_did_not_load_is_not_read():
    record = RunRecord.new(
        started_at=at(WED),
        lines=("edge",),
        reasons=("edge: raised (RuntimeError: boom)",),
    )
    snapshot = replace(healthy(), pipeline={**healthy().pipeline, record.id: record})
    assert {r.slug for r in line_runs(snapshot)} == {SLUG}


def test_meters_from_before_they_were_kept_are_no_cells_and_after_it_none_is_missing():
    old_day = METERS_SINCE - timedelta(days=1)
    unmeasured = _report(old_day, 0).model_copy(
        update={
            "operations": _report(old_day, 0).operations.model_copy(
                update={"writer_calls": None, "jev_input_tokens": None}
            )
        }
    )
    snapshot = _put(healthy(), unmeasured)
    got = status(REGISTRY_BY_ID["writer_calls"], snapshot, start=old_day, end=END)
    assert old_day not in {c.observation.run_date for c in got.cells}
    assert got.status == "live"
    lost = _ops(healthy(), WED, writer_calls=None)
    assert _cell(_check(REGISTRY_BY_ID["writer_calls"], lost), WED) == "missing"


def test_an_empty_window_is_insufficient_not_healthy():
    far = date(2027, 3, 1)
    got = status(REGISTRY_BY_ID["o1"], healthy(), start=far, end=far + timedelta(days=6))
    assert (got.cells, got.status) == ((), "insufficient-n")


# ------------------------------------------------------------------- per instrument


def test_a_zero_meter_beside_zero_questions_is_fine():
    snapshot = _ops(healthy(), WED, jev_questions=0, jev_input_tokens=0)
    assert _cell(_check(REGISTRY_BY_ID["jev_tokens"], snapshot), WED) == "expected-zero"


def test_one_note_without_a_citation_is_allowed_and_the_second_is_not():
    once = _put(healthy(), _log(WED, "根拠がない。"))
    got = _check(REGISTRY_BY_ID["o1"], once)
    assert (_cell(got, WED), got.status) == ("expected-zero", "live")
    twice = _check(REGISTRY_BY_ID["o1"], _put(once, _log(THU, "根拠がない。")))
    assert _cell(twice, THU) == "unexplained-zero"


def test_a_source_cited_again_is_not_new():
    """Thursday's prose cites Wednesday's claim again: no new source on Thursday."""
    source, _, claim = _claim(WED)
    again = _log(THU).model_copy(update={"claims": (claim.id,), "sources": (source.id,)})
    got = _check(REGISTRY_BY_ID["o1"], _put(healthy(), again))
    assert got.cells[3].observation.value == 0
    assert _cell(got, THU) == "expected-zero"


def test_a_citation_that_resolves_to_no_source_is_a_contradiction():
    dangling = _drop(healthy(), _claim(WED)[1].id)  # the unit behind Wednesday's claim
    got = _check(REGISTRY_BY_ID["o1"], dangling)
    assert _cell(got, WED) == "contradiction"
    conflict = got.cells[2].observation.conflict
    assert conflict is not None and "[1] resolves to no source" in conflict
    out_of_range = _put(healthy(), _log(WED, "根拠 [2]。"))
    assert _cell(_check(REGISTRY_BY_ID["o1"], out_of_range), WED) == "contradiction"


@pytest.mark.parametrize(
    ("update", "why"),
    [
        ({"first_harvested_at": at(END, 6)}, "first harvest after the latest harvest"),
        (
            {"first_harvested_at": at(WED - timedelta(days=2))},
            "first harvest before its note was written",
        ),
    ],
)
def test_a_first_harvest_out_of_order_is_a_contradiction(update: dict[str, object], why: str):
    got = _check(
        REGISTRY_BY_ID["label.first_harvest"],
        _put(healthy(), _label(WED).model_copy(update=update)),
    )
    assert _cell(got, END, TICK) == "contradiction"
    conflict = next(c.observation.conflict for c in got.cells if c.observation.run_date == END)
    assert conflict is not None and why in conflict


def test_a_tick_kept_from_before_first_harvests_were_recorded_stays_unknown():
    """A Label of a note from before METERS_SINCE has no first harvest by design."""
    old = date(2026, 10, 15)
    label = Label.new(
        subject=_claim(old)[2].id,
        report=Report.id_for(b.LINE_IRI, old),
        verdict="correct",
        provenance="claim",
        harvested_at=at(END),
    )
    snapshot = _put(healthy(), _report(old, 0), label)
    assert _check(REGISTRY_BY_ID["label.first_harvest"], snapshot).status == "live"


def test_no_new_tick_and_no_opened_note_is_allowed():
    snapshot = replace(_drop(healthy(), *(_label(d).id for d in DAYS[1:])), opened={})
    for name in ("label.first_harvest", "opened"):
        got = _check(REGISTRY_BY_ID[name], snapshot)
        assert {c.status for c in got.cells} == {"expected-zero"}, name
        assert got.status == "expected-zero", name


def test_the_weekly_reviews_own_note_is_not_an_opened_jrp_note():
    """A `*_jrp_wbr.md` recorded in opened.jsonl (before the reader kept it out) is neither
    counted nor checked against its date."""
    review = "2026-11-02_jrp_wbr.md"
    snapshot = replace(healthy(), opened={**healthy().opened, review: WED})
    got = _check(REGISTRY_BY_ID["opened"], snapshot)
    assert got == _check(REGISTRY_BY_ID["opened"], healthy())
    assert got.status == "live"


def test_a_listed_name_without_a_date_is_counted_and_checks_nothing():
    snapshot = replace(healthy(), opened={**healthy().opened, "notes_jrp_x.md": WED})
    got = _check(REGISTRY_BY_ID["opened"], snapshot)
    assert (got.cells[2].observation.value, got.status) == (2, "live")


def test_a_vault_sighting_is_live_and_the_declaration_still_stands():
    seen = Sighting.new(key="arxiv:2610.09999", first_seen=WED, place="vault:notes")
    snapshot = replace(healthy(), pipeline={**healthy().pipeline, seen.id: seen})
    got = _check(REGISTRY_BY_ID["used.vault"], snapshot)
    assert (_cell(got, WED, TICK), got.status) == ("live", "declared-degenerate")


# ---------------------------------------------------------------------- the surface


def test_every_status_has_its_word_in_every_language():
    words = {s: STATUS_WORDS[s] for s in STATUS_WORDS}
    assert set(words) == set(get_args(Status.__value__))
    for msg in words.values():
        assert all(msg(lang) for lang in LANGS)
    for i in REGISTRY:
        if i.declared is not None:
            assert all(i.declared.reason(lang) for lang in LANGS)
            assert i.declared.reason in {t.DECLARED_CITATION_SEEDS, t.DECLARED_USED_VAULT}


def test_read_snapshot_reads_the_store_and_writes_nothing(tmp_path: Path):
    store = GraphStore(tmp_path)
    snapshot = healthy()
    store.line(SLUG).put(snapshot.lines[SLUG].values())
    store.pipeline().put(snapshot.pipeline.values())
    opened = tmp_path / OPENED_FILE
    opened.parent.mkdir(parents=True)
    opened.write_text(
        "".join(f'{{"note": "{n}", "first_seen": "{d}"}}\n' for n, d in snapshot.opened.items()),
        encoding="utf-8",
    )
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    read = read_snapshot(store, [SLUG], firehose={SLUG: 2})
    assert {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")} == before
    assert read == replace(snapshot, firehose={SLUG: 2})
    assert read_snapshot(GraphStore(tmp_path / "empty"), [SLUG]) == Snapshot(lines={SLUG: {}})
    assert not (tmp_path / "empty").exists()
