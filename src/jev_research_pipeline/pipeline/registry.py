"""The instrument registry: which numbers in the store are alive, before any of them is
compared (plan quality-metrics claim 5; research report 2026-10-20 §8.11).

A zero means nothing on its own. An empty arXiv listing on a Monday morning is the feed
working; the same zero on a Wednesday is a dead net; a meter that is a constant 0 reads
like a quiet day forever (a third of the operations block was such numbers on 2026-10-19,
inventory "0 と定数の判定"). So every number the weekly review compares is an Instrument
here, with what it reads, what each reading should show (its expectation, a calendar where
there is one) and, for a number known to be degenerate, a declaration with its reason and
the day by which it is reviewed. `status` gives each cell (instrument, line, run_date)
and the instrument over a window one Status word. The weekly review compares live numbers
only and prints the word in place of any other number.

tests/test_registry.py injects one fault per instrument and checks that its status stops
being healthy, and checks that every id in REGISTRY has such a fault: an instrument added
here without one does not pass verify.

Nothing here writes: `read_snapshot` loads the partitions and metrics/opened.jsonl, and
every other function is pure over the Snapshot. Partition.load raises StoreSchemaError on a
store whose @context is older (the caller decides what to do; `jrp run` migrates first).
"""

from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Final, Literal

from jev_research_pipeline import note_text as t
from jev_research_pipeline.adapters import firehose
from jev_research_pipeline.generation.prose import citations
from jev_research_pipeline.model import (
    Claim,
    GraphNodeType,
    Label,
    QuestionLog,
    Report,
    RunRecord,
    Sighting,
    SourceItem,
    StageRecord,
    Unit,
)
from jev_research_pipeline.note_text import Msg
from jev_research_pipeline.reduction.opened import OPENED_FILE, first_seen
from jev_research_pipeline.store import GraphStore

from .nets import DEFAULT_BUDGETS

type Part = Literal["M", "Q", "I", "S", "X", "W", "D", "OUT"]
"""The weekly review's parts: M instruments and the author's signal, Q questions, I intake,
S screening, X evidence and the note's slots, W writing, D delivery and resources, OUT the
outputs O1 / O2 (synthesis 2026-10-20, PARTS)."""

type Status = Literal[
    "live",
    "expected-zero",
    "declared-degenerate",
    "insufficient-n",
    "unexplained-zero",
    "stuck",
    "missing",
    "contradiction",
]
"""- live: a value above 0 that the expectation allows.
- expected-zero: a 0 the expectation explains (the calendar, or an instrument that allows 0).
- declared-degenerate: a 0 of an instrument declared degenerate, on or before its review_by.
- insufficient-n: the window holds fewer cells than the instrument's min_n (window only).
- unexplained-zero: a 0 that nothing explains (a declaration past its review_by included).
- stuck: the same value on `stuck_after` live cells of one line in a row.
- missing: a line-run (or tick) happened and the data it should have left is absent.
- contradiction: two stored numbers disagree, or a value comes on a day the calendar says
  is empty."""

FAILURES: Final[tuple[Status, ...]] = ("contradiction", "missing", "unexplained-zero", "stuck")
"""The statuses that make a number unusable, most severe first: an instrument's status over
a window is its most severe failing cell, if it has one."""

STATUS_WORDS: Final[Mapping[Status, Msg]] = {
    "live": t.STATUS_LIVE,
    "expected-zero": t.STATUS_EXPECTED_ZERO,
    "declared-degenerate": t.STATUS_DECLARED_DEGENERATE,
    "insufficient-n": t.STATUS_INSUFFICIENT_N,
    "unexplained-zero": t.STATUS_UNEXPLAINED_ZERO,
    "stuck": t.STATUS_STUCK,
    "missing": t.STATUS_MISSING,
    "contradiction": t.STATUS_CONTRADICTION,
}
"""What the weekly review prints for each status."""

type Expect = Literal["positive", "zero", "any", "agrees"]
"""What one reading should show:
- positive: a value above 0; a 0 is unexplained.
- zero: 0 (the calendar says the source is empty); a value above 0 is a contradiction.
- any: 0 is allowed; a 0 is expected-zero.
- agrees: another number of the same run says there must be a value; a 0 is a
  contradiction."""

TICK: Final = ""
"""The `line` of a cell that belongs to the whole tick, not to one line (used scan, opened
notes, harvested ticks)."""

METERS_SINCE: Final = date(2026, 10, 21)
"""First run_date whose Reports carry writer_calls and Jev tokens, and whose harvest keeps
Label.first_harvested_at: commit ee24b9f reached main on 2026-10-20 after that day's 05:00
run. Earlier line-runs are no cells of those instruments (not measured is not missing)."""
OPENED_SINCE: Final = date(2026, 10, 21)
"""First run that records opened notes (commit 5178d68, 2026-10-20 after the 05:00 run)."""
USED_SINCE: Final = date(2026, 10, 20)
"""The used scan's first run (the 05:00 run of 2026-10-20 recorded its baseline)."""
REVIEW_BY: Final = date(2026, 12, 31)
"""Every declaration is reviewed by this day, in the same pass that adds arXiv's 2027
holiday list: after it, a declared 0 reads unexplained-zero until the declaration is
renewed with a reason or removed."""

ARXIV_STAGE: Final = "fetch_firehose_arxiv"
HF_STAGE: Final = "fetch_firehose_hf_papers"
CITATION_STAGE: Final = "fetch_citation_openalex"
"""StageRecord names: adapters.collect writes `fetch_{net}_{adapter}`."""

ARXIV_HOLIDAYS: Final = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 10, 12),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2026, 12, 29),
        date(2026, 12, 31),
    }
)
"""Days arXiv makes no announcement, as listed at https://info.arxiv.org/help/availability.html
(as-of 2026-10-20; the page lists 2026 only). Review-when: the page lists 2027 (check in
2026-12, REVIEW_BY), or an empty listing the day after a day not on this list."""
ARXIV_FEED_TZ: Final = timezone(timedelta(hours=-5), "EST")
"""The RSS feeds "are updated daily at midnight Eastern Standard Time"
(https://info.arxiv.org/help/rss.html, as-of 2026-10-20). Read literally: a fixed UTC-5."""


def arxiv_quiet(at: datetime) -> bool:
    """True when the arXiv listing fetched at `at` is empty by arXiv's calendar.

    The feed of a day carries the announcement of the evening before (Sunday to Thursday,
    20:00 ET), and is empty on Saturday and Sunday and after an arXiv holiday
    (https://info.arxiv.org/help/rss_specifications.html, skipDays; as-of 2026-10-20). A
    05:00 JST run reads the feed of the day before in ET, so it is empty on Sunday and
    Monday JST and two days after a holiday (2026-10-12 → the 10-14 run, inventory
    2026-10-19)."""
    feed_day = at.astimezone(ARXIV_FEED_TZ).date()
    return feed_day.weekday() >= 5 or feed_day - timedelta(days=1) in ARXIV_HOLIDAYS


def hf_quiet(at: datetime) -> bool:
    """True when HF daily papers fetched at `at` is empty: the request asks for the UTC day
    before (adapters.firehose.hf_date), and HF has no daily papers on Saturday and Sunday,
    so a 05:00 JST run reads 0 on Monday and Tuesday JST (inventory 2026-10-19)."""
    return date.fromisoformat(firehose.hf_date(at)).weekday() >= 5


@dataclass(frozen=True)
class Snapshot:
    """The store as the registry reads it."""

    lines: Mapping[str, Mapping[str, GraphNodeType]]
    """Line slug → its partition (store/lines/<slug>.jsonld), as Partition.load returns it.
    A line not here is not read, even when a RunRecord names it."""
    pipeline: Mapping[str, GraphNodeType] = field(default_factory=dict[str, GraphNodeType])
    """store/pipeline.jsonld: RunRecords and Sightings."""
    opened: Mapping[str, date] = field(default_factory=dict[str, date])
    """metrics/opened.jsonl: jrp note name → the first day it was seen opened."""
    firehose: Mapping[str, int] = field(default_factory=dict[str, int])
    """Line slug → its firehose budget (pipeline.nets.for_line(...).budget("firehose")); a
    line not here has the default. 0 asks no firehose, 1 the arXiv listing only, 2 both."""


def read_snapshot(
    store: GraphStore, slugs: Sequence[str], *, firehose: Mapping[str, int] | None = None
) -> Snapshot:
    """Load what the registry reads, writing nothing."""
    opened = store.root / OPENED_FILE
    return Snapshot(
        lines={slug: store.line(slug).load() for slug in slugs},
        pipeline=store.pipeline().load(),
        opened=first_seen(opened.read_text(encoding="utf-8")) if opened.is_file() else {},
        firehose=dict(firehose or {}),
    )


@dataclass(frozen=True)
class Observation:
    """One reading of one instrument: a line-run's (or a tick's) value."""

    line: str
    """The line slug, or TICK."""
    run_date: date
    value: int | None
    """None = the run happened and the data it should have left is absent."""
    related: int | None = None
    """The number of the same run the expectation reads beside the value (prose sections
    written, Jev questions asked, the line's previous value)."""
    at: datetime | None = None
    """When the data was taken (a calendar reads it)."""
    conflict: str | None = None
    """An invariant between stored fields found broken, named for the reader."""


@dataclass(frozen=True)
class Declared:
    """A number known to be degenerate: its 0 is not a failure until `review_by`."""

    reason: Msg
    review_when: str
    """The event that voids the declaration."""
    review_by: date
    """After this day a declared 0 is unexplained-zero (the declaration lapsed)."""


type Observe = Callable[[Snapshot], Iterable[Observation]]


@dataclass(frozen=True)
class Instrument:
    id: str
    part: Part
    reads: str
    """What it reads in the store, for the next reader of this table."""
    observe: Observe
    """Every reading the store holds, all days; `status` keeps the window."""
    expect: Callable[[Observation], Expect]
    declared: Declared | None = None
    since: date | None = None
    """First run_date the store records this number; earlier readings are no cells."""
    stuck_after: int | None = None
    """This many equal values on one line's live cells in a row is stuck; None = never."""
    min_n: int = 1
    """Fewer cells in the window than this is insufficient-n."""


@dataclass(frozen=True)
class Cell:
    observation: Observation
    status: Status


@dataclass(frozen=True)
class InstrumentStatus:
    id: str
    part: Part
    status: Status
    cells: tuple[Cell, ...]
    """In (line, run_date) order."""


def cell_status(instrument: Instrument, obs: Observation) -> Status:
    """One reading's status (stuck is decided over a line's cells, in `status`)."""
    if obs.value is None:
        return "missing"
    if obs.conflict is not None:
        return "contradiction"
    expect = instrument.expect(obs)
    if obs.value > 0:
        return "contradiction" if expect == "zero" else "live"
    if expect == "agrees":
        return "contradiction"
    if instrument.declared is not None:
        lapsed = obs.run_date > instrument.declared.review_by
        return "unexplained-zero" if lapsed else "declared-degenerate"
    return "unexplained-zero" if expect == "positive" else "expected-zero"


def _stuck(cells: list[Cell], after: int) -> list[Cell]:
    """Mark live cells stuck from the `after`-th equal value in a row of one line on."""
    out = list(cells)
    previous: dict[str, tuple[int | None, int]] = {}  # line -> (last live value, streak)
    for i, cell in enumerate(out):
        if cell.status != "live":
            continue
        obs = cell.observation
        last, streak = previous.get(obs.line, (None, 0))
        streak = streak + 1 if obs.value == last else 1
        previous[obs.line] = (obs.value, streak)
        if streak >= after:
            out[i] = replace(cell, status="stuck")
    return out


def _window(instrument: Instrument, cells: Sequence[Cell]) -> Status:
    worst: Status | None = next((s for s in FAILURES if any(c.status == s for c in cells)), None)
    if worst is not None:
        return worst
    if len(cells) < instrument.min_n:
        return "insufficient-n"
    if any(c.status == "declared-degenerate" for c in cells):
        return "declared-degenerate"
    return "live" if any(c.status == "live" for c in cells) else "expected-zero"


def status(
    instrument: Instrument, snapshot: Snapshot, *, start: date, end: date
) -> InstrumentStatus:
    """The instrument's cells with run_date in [start, end] (and on or after its `since`),
    and its status over them: the most severe failure if any cell fails; else
    insufficient-n under min_n cells; else declared-degenerate if a declared 0 is among
    them; else live if any cell is live; else expected-zero."""
    first = max(start, instrument.since) if instrument.since is not None else start
    observed = sorted(
        (o for o in instrument.observe(snapshot) if first <= o.run_date <= end),
        key=lambda o: (o.line, o.run_date),
    )
    cells = [Cell(o, cell_status(instrument, o)) for o in observed]
    if instrument.stuck_after is not None:
        cells = _stuck(cells, instrument.stuck_after)
    return InstrumentStatus(
        id=instrument.id,
        part=instrument.part,
        status=_window(instrument, cells),
        cells=tuple(cells),
    )


def statuses(
    snapshot: Snapshot,
    *,
    start: date,
    end: date,
    registry: Sequence[Instrument] | None = None,
) -> tuple[InstrumentStatus, ...]:
    """Every instrument's status over [start, end], in registry order."""
    return tuple(
        status(i, snapshot, start=start, end=end)
        for i in (REGISTRY if registry is None else registry)
    )


# ------------------------------------------------------------------- what ran, and when


@dataclass(frozen=True)
class LineRun:
    """One line's run on one day: the cells of a per-line instrument."""

    slug: str
    run_date: date
    started_at: datetime | None
    """The tick that wrote the day's Report (a same-day re-run overwrites it, so the latest
    such tick), else the latest tick that ran the line; None = known from its Report only
    (a store from before RunRecords)."""
    report: Report | None
    """None = the line-run raised before it wrote a note, or its Report is gone."""


def _of[N](nodes: Mapping[str, GraphNodeType], kind: type[N]) -> list[N]:
    return [n for n in nodes.values() if isinstance(n, kind)]


def _raised(record: RunRecord, slug: str) -> bool:
    return any(reason.startswith(f"{slug}: raised") for reason in record.reasons)


def _tick_runs(snapshot: Snapshot) -> dict[tuple[str, date], LineRun]:
    """Line-runs the RunRecords name. A line a tick picked that wrote no note and did not
    raise had no open question: it ran nothing, so it is no line-run."""
    runs: dict[tuple[str, date], LineRun] = {}
    for record in sorted(_of(snapshot.pipeline, RunRecord), key=lambda r: r.started_at):
        wrote = {r.slug: r.report for r in record.line_records}
        for slug in record.lines:
            nodes = snapshot.lines.get(slug)
            if nodes is None or (slug not in wrote and not _raised(record, slug)):
                continue
            stored = nodes.get(wrote[slug]) if slug in wrote else None
            run = LineRun(
                slug=slug,
                run_date=record.run_date,
                started_at=record.started_at,
                report=stored if isinstance(stored, Report) else None,
            )
            key = (slug, record.run_date)
            if run.report is not None or key not in runs or runs[key].report is None:
                runs[key] = run
    return runs


def line_runs(snapshot: Snapshot) -> tuple[LineRun, ...]:
    """Every line-run, one per (line, run_date), in that order: those the RunRecords name,
    then each Report no RunRecord covers (stores from before RunRecords)."""
    runs = _tick_runs(snapshot)
    for slug, nodes in snapshot.lines.items():
        for report in _of(nodes, Report):
            runs.setdefault((slug, report.run_date), LineRun(slug, report.run_date, None, report))
    return tuple(runs[k] for k in sorted(runs))


def tick_days(snapshot: Snapshot) -> frozenset[date]:
    """The days a tick ran: RunRecords, and the line-runs of stores from before them."""
    return frozenset(r.run_date for r in _of(snapshot.pipeline, RunRecord)) | {
        r.run_date for r in line_runs(snapshot)
    }


def _by_line(runs: Iterable[LineRun]) -> dict[str, list[LineRun]]:
    out: dict[str, list[LineRun]] = {}
    for run in runs:
        out.setdefault(run.slug, []).append(run)
    return out


# ------------------------------------------------------------------------- observations


def _fetched(nodes: Mapping[str, GraphNodeType], stage: str) -> dict[date, list[StageRecord]]:
    """A stage's records by day. A failed fetch leaves none (adapters.collect); a same-day
    re-run finds the first run's record, stamped with that run's time."""
    out: dict[date, list[StageRecord]] = {}
    for record in _of(nodes, StageRecord):
        if record.stage == stage:
            out.setdefault(record.completed_at.date(), []).append(record)
    return out


def _reading(run: LineRun, records: Sequence[StageRecord]) -> Observation:
    return Observation(
        line=run.slug,
        run_date=run.run_date,
        value=sum(len(r.outputs) for r in records),
        at=min(r.completed_at for r in records),
    )


def _firehose(stage: str, needs: int) -> Observe:
    """Per line-run whose firehose budget asks this stage (`needs`): the sources its fetch
    returned (StageRecord.outputs, before the firehose cap), or missing when the line ran
    and left no record (the fetch failed, or the line raised before it)."""

    def observe(snapshot: Snapshot) -> Iterator[Observation]:
        default = DEFAULT_BUDGETS["firehose"]
        fetched = {slug: _fetched(nodes, stage) for slug, nodes in snapshot.lines.items()}
        for run in line_runs(snapshot):
            if snapshot.firehose.get(run.slug, default) < needs:
                continue  # `firehose = false`, or a budget of 1 (no HF daily)
            records = fetched[run.slug].get(run.run_date)
            yield _reading(run, records) if records else Observation(run.slug, run.run_date, None)

    return observe


def _citation(snapshot: Snapshot) -> Iterator[Observation]:
    """Per line-run that sent `cites:` requests: the sources they returned. A run sends one
    only for papers its line already accepted, so a run without a record is no cell."""
    fetched = {slug: _fetched(nodes, CITATION_STAGE) for slug, nodes in snapshot.lines.items()}
    for run in line_runs(snapshot):
        if records := fetched[run.slug].get(run.run_date):
            yield _reading(run, records)


def _logs_by_report(nodes: Mapping[str, GraphNodeType]) -> dict[str, list[QuestionLog]]:
    out: dict[str, list[QuestionLog]] = {}
    for log in _of(nodes, QuestionLog):
        out.setdefault(log.report, []).append(log)
    return out


def _writer_calls(snapshot: Snapshot) -> Iterator[Observation]:
    """Per line-run: Operations.writer_calls, beside the prose sections that run wrote. A
    section reused from the same day's earlier run keeps that run's logged_at and costs no
    call, so it is not counted."""
    logs = {slug: _logs_by_report(nodes) for slug, nodes in snapshot.lines.items()}
    for run in line_runs(snapshot):
        if run.report is None:
            yield Observation(run.slug, run.run_date, None)
            continue
        written = sum(
            1
            for log in logs[run.slug].get(run.report.id, [])
            if log.text.strip() and (run.started_at is None or log.logged_at == run.started_at)
        )
        yield Observation(
            run.slug, run.run_date, run.report.operations.writer_calls, related=written
        )


def _jev_tokens(snapshot: Snapshot) -> Iterator[Observation]:
    """Per line-run: Operations.jev_input_tokens, beside Operations.jev_questions."""
    for run in line_runs(snapshot):
        if run.report is None:
            yield Observation(run.slug, run.run_date, None)
            continue
        ops = run.report.operations
        yield Observation(run.slug, run.run_date, ops.jev_input_tokens, related=ops.jev_questions)


def _source_of(nodes: Mapping[str, GraphNodeType], claim_id: str) -> str | None:
    claim = nodes.get(claim_id)
    unit = nodes.get(claim.unit) if isinstance(claim, Claim) else None
    source = nodes.get(unit.source) if isinstance(unit, Unit) else None
    return source.id if isinstance(source, SourceItem) else None


def _cited(nodes: Mapping[str, GraphNodeType]) -> tuple[dict[date, set[str]], dict[date, str]]:
    """The sources each day's prose cites, and per day the first [n] that resolves to no
    source. Each QuestionLog numbers its own claims from 1 ([n] = claims[n-1],
    generation.prose.citations); Report.claims is the whole note's order and is not read."""
    cited: dict[date, set[str]] = {}
    broken: dict[date, str] = {}
    for log in sorted(_of(nodes, QuestionLog), key=lambda q: q.id):
        for n in sorted(citations(log.text)):
            source = _source_of(nodes, log.claims[n - 1]) if 1 <= n <= len(log.claims) else None
            if source is None:
                broken.setdefault(log.run_date, f"{log.id} [{n}] resolves to no source")
            else:
                cited.setdefault(log.run_date, set()).add(source)
    return cited, broken


def _first_cited(snapshot: Snapshot) -> Iterator[Observation]:
    """Per line-run: the sources the line's prose cites for the first time that day (O1 in
    sources; the weekly review counts papers), beside the line's previous value."""
    for slug, runs in _by_line(line_runs(snapshot)).items():
        cited, broken = _cited(snapshot.lines[slug])
        first: dict[str, date] = {}
        for day in sorted(cited):
            for source in cited[day]:
                first.setdefault(source, day)
        per_day = Counter(first.values())
        previous: int | None = None
        for run in runs:
            if run.report is None:
                yield Observation(slug, run.run_date, None)
                continue
            value = per_day.get(run.run_date, 0)
            yield Observation(
                slug, run.run_date, value, related=previous, conflict=broken.get(run.run_date)
            )
            previous = value


def _claims_posted(snapshot: Snapshot) -> Iterator[Observation]:
    """Per line-run: the claims on its note, beside the line's previous Report's count."""
    for slug, runs in _by_line(line_runs(snapshot)).items():
        previous: int | None = None
        for run in runs:
            if run.report is None:
                yield Observation(slug, run.run_date, None)
                continue
            value = len(run.report.claims)
            yield Observation(slug, run.run_date, value, related=previous)
            previous = value


def _label_conflict(label: Label, nodes: Mapping[str, GraphNodeType]) -> str | None:
    first = label.first_harvested_at
    report = nodes.get(label.report)
    written = report.run_date if isinstance(report, Report) else None
    if first is None:
        late = written is not None and written >= METERS_SINCE
        return "no first harvest on a note written since it is kept" if late else None
    if first > label.harvested_at:
        return "first harvest after the latest harvest"
    if written is not None and first.date() < written:
        return "first harvest before its note was written"
    return None


def _first_harvests(snapshot: Snapshot) -> Iterator[Observation]:
    """Per tick: Labels first harvested that day (new ticks; 0 is allowed), with a broken
    first harvest on the day of the Label's latest harvest."""
    labels = [(label, nodes) for nodes in snapshot.lines.values() for label in _of(nodes, Label)]
    firsts = Counter(
        label.first_harvested_at.date()
        for label, _ in labels
        if label.first_harvested_at is not None
    )
    broken: dict[date, str] = {}
    for label, nodes in sorted(labels, key=lambda pair: pair[0].id):
        if (why := _label_conflict(label, nodes)) is not None:
            broken.setdefault(label.harvested_at.date(), f"{label.id}: {why}")
    for day in sorted(tick_days(snapshot) | set(firsts) | set(broken)):
        yield Observation(TICK, day, firsts.get(day, 0), conflict=broken.get(day))


def _note_date(note: str) -> date | None:
    try:
        return date.fromisoformat(note[:10])
    except ValueError:
        return None


def _opened(snapshot: Snapshot) -> Iterator[Observation]:
    """Per tick: jrp notes first seen opened that day (0 is allowed), with a note seen
    before its own date (`YYYY-MM-DD_jrp_<slug>.md`) as a broken reading."""
    seen = Counter(snapshot.opened.values())
    broken: dict[date, str] = {}
    for note, day in sorted(snapshot.opened.items()):
        written = _note_date(note)
        if written is not None and day < written:
            broken.setdefault(day, f"{note} seen opened on {day}, before its own date")
    for day in sorted(tick_days(snapshot) | set(seen)):
        yield Observation(TICK, day, seen.get(day, 0), conflict=broken.get(day))


def _vault_sightings(snapshot: Snapshot) -> Iterator[Observation]:
    """Per tick: keys the used scan saw first in the vault that day."""
    seen = Counter(
        s.first_seen
        for s in _of(snapshot.pipeline, Sighting)
        if s.place == "vault" or s.place.startswith("vault:")
    )
    for day in sorted(tick_days(snapshot) | set(seen)):
        yield Observation(TICK, day, seen.get(day, 0))


# ------------------------------------------------------------------------- expectations


def _arxiv_expect(obs: Observation) -> Expect:
    return "zero" if obs.at is not None and arxiv_quiet(obs.at) else "positive"


def _hf_expect(obs: Observation) -> Expect:
    return "zero" if obs.at is not None and hf_quiet(obs.at) else "positive"


def _any(obs: Observation) -> Expect:
    return "any"


def _agrees_with_related(obs: Observation) -> Expect:
    """A value must come with a related number above 0; with 0 beside it, 0 is fine."""
    return "agrees" if (obs.related or 0) > 0 else "any"


def _not_twice(obs: Observation) -> Expect:
    """0 is allowed once; a 0 after the line's previous 0 (two Reports in a row) is not."""
    return "positive" if obs.related == 0 else "any"


REGISTRY: Final[tuple[Instrument, ...]] = (
    Instrument(
        id="firehose.arxiv",
        part="I",
        reads="StageRecord fetch_firehose_arxiv per line-run: what the arXiv listing "
        "returned, before the firehose cap",
        observe=_firehose(ARXIV_STAGE, needs=1),
        expect=_arxiv_expect,
        stuck_after=3,
    ),
    Instrument(
        id="firehose.hf",
        part="I",
        reads="StageRecord fetch_firehose_hf_papers per line-run: what HF daily returned "
        "(at most firehose.HF_LIMIT, so equal values are no sign)",
        observe=_firehose(HF_STAGE, needs=2),
        expect=_hf_expect,
    ),
    Instrument(
        id="citation",
        part="I",
        reads="StageRecord fetch_citation_openalex per line-run that sent `cites:`: the "
        "works citing the line's accepted papers",
        observe=_citation,
        expect=_any,
        declared=Declared(
            reason=t.DECLARED_CITATION_SEEDS,
            review_when="the seeds are papers old enough to be cited, or a citation source "
            "reaches a note's claims",
            review_by=REVIEW_BY,
        ),
    ),
    Instrument(
        id="used.vault",
        part="OUT",
        reads="Sighting nodes with place vault or vault:<folder>, by first_seen",
        observe=_vault_sightings,
        expect=_any,
        declared=Declared(
            reason=t.DECLARED_USED_VAULT,
            review_when="the used scan is given a path that holds the author's own vault notes",
            review_by=REVIEW_BY,
        ),
        since=USED_SINCE,
    ),
    Instrument(
        id="writer_calls",
        part="D",
        reads="Report.operations.writer_calls per line-run, beside the QuestionLogs with "
        "prose that run wrote",
        observe=_writer_calls,
        expect=_agrees_with_related,
        since=METERS_SINCE,
    ),
    Instrument(
        id="jev_tokens",
        part="D",
        reads="Report.operations.jev_input_tokens per line-run, beside jev_questions",
        observe=_jev_tokens,
        expect=_agrees_with_related,
        since=METERS_SINCE,
        stuck_after=3,
    ),
    Instrument(
        id="o1",
        part="OUT",
        reads="QuestionLog.text [n] → claims[n-1] → Claim.unit → Unit.source per line-run: "
        "sources the line's prose cites for the first time",
        observe=_first_cited,
        expect=_not_twice,
    ),
    Instrument(
        id="claims_posted",
        part="X",
        reads="len(Report.claims) per line-run",
        observe=_claims_posted,
        expect=_not_twice,
    ),
    Instrument(
        id="label.first_harvest",
        part="M",
        reads="Label.first_harvested_at per tick: the author's new ticks",
        observe=_first_harvests,
        expect=_any,
        since=METERS_SINCE,
    ),
    Instrument(
        id="opened",
        part="M",
        reads="metrics/opened.jsonl per tick: jrp notes first seen on Obsidian's "
        "recently-opened lists",
        observe=_opened,
        expect=_any,
        since=OPENED_SINCE,
    ),
)
"""Every instrument the weekly review may compare (v0)."""
