"""`jrp eval intake`: does a candidate intake configuration reach more new on-topic papers
than the current one, on the same frozen fetches? (plan docs/plans/intake-eval.html; research
report docs/plans/research/2026-10-20-intake-eval.md)

Production cannot answer it: what the nets return changes every day, so a week under a
changed configuration is a week of other papers. The eval holds the fetches still and changes
one thing at a time (measurement-discipline 8: the arm mirrors production's mechanism).

Frozen sets, both store-shaped partitions, read and never written:
- history: the line's own partition. Every StageRecord(fetch_*) is one request of one day,
  its outputs in the order the source answered. A firehose listing's are there in full,
  overflow included, because adapters.collect stores every result before the cap cuts. A
  keyword request's query is the authored or stored query text whose collect() key
  (adapter, net, query, run date) hashes to the record's input.
- snapshot: <bench>/snapshots/<date>/<slug>.jsonld (evals.freeze): today's firehose and every
  keyword query of both configurations, each sent once.

One day's replay for one configuration (Arm), in production's own functions:
1. firehose: HF daily, then the arXiv listing, each through nets.firehose_cut in the room the
   cap leaves (the arXiv listing ranked by run.firehose_query), the HF results kept out of the
   arXiv listing's room as nets.fetch_nets keeps them (`seen`). With backlog_days > 0 the room
   the day leaves is filled from the arXiv listings of the backlog_days days before, minus
   what an earlier day reached, by the same ranking.
2. recommendation, citation, exploration: every recorded result, unless the net is off. Their
   requests are the ones production sent that day, on that day's seeds.
3. keyword: every recorded result of a query the configuration keeps.
4. the body floor: question_screening.no_abstract, or the candidate's floor for abstracts.
5. the prefilter (evals.judge): the stored Judgment for today's open questions, else the
   bench's own, else asked once under the USD cap.

Numbers (Score), over the window's days:
- N_ot: paper keys (wbr.paper_key) the line had not fetched before the window, reached past
  the floor, whose source passes the prefilter for some question; each on the first day it
  passes. "Before the window" is the store as of the window's first day, never today's: a
  candidate must not look better because the current configuration already fetched a paper.
- new-rate: of the keys reached, the share the line had not fetched before the window.
- per source: N_ot found through each net and each keyword query, and through it alone
  (unique). Unique depends on the set — two queries that find the same paper both read 0 — so
  a swap is scored by replaying the swapped set, never by summing uniques.
- Chao2 (evals.stats) over the request-days of the query nets, with and without the nets
  seeded by accepted papers (recommendation, citation): at least that many new on-topic
  papers no request reached. It licenses "coverage is missing", never "a query is exhausted".
- self-check: the baseline's replay of each day against the sources production prefiltered
  that day (a prefilter Judgment dated that day). A day that does not match is named.
"""

import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Final

from pydantic import AwareDatetime, Field, model_validator

from jev_research_pipeline.jev import LineContext, question_prefilter, question_screening
from jev_research_pipeline.jev.core import threshold
from jev_research_pipeline.model import (
    AdapterKind,
    DiscoveryNet,
    GraphNodeType,
    Judgment,
    QueryCandidate,
    Question,
    Report,
    SourceItem,
    StageRecord,
)
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.model.nodes import NonEmptyText, NonNegInt
from jev_research_pipeline.pipeline import nets
from jev_research_pipeline.pipeline.config import config_path, env_tracks, line_context
from jev_research_pipeline.pipeline.run import authored_candidates, firehose_query, make_adapter
from jev_research_pipeline.pipeline.wbr import paper_key
from jev_research_pipeline.query_text import clean_query
from jev_research_pipeline.questions import (
    QUERY_FIELDS,
    AuthoredQueries,
    open_questions,
    question_queries,
)
from jev_research_pipeline.store import input_sha256

from .stats import Chao2, chao2

type Query = tuple[AdapterKind, str]
"""(adapter, cleaned text): one authored query line."""

CUT: Final = threshold(question_prefilter.THRESHOLDS, "on_topic")
SEEDED: Final[frozenset[str]] = frozenset({"recommendation", "citation"})
"""Nets whose requests are built from the line's accepted papers: positively dependent on
the others by construction."""
QUERY_NETS: Final[frozenset[str]] = frozenset(
    {"recommendation", "citation", "keyword", "exploration"}
)
"""The nets that sample the literature again on another day (Chao2's units). A firehose
listing announces each paper once, so its days are not replicates."""
BACKLOG: Final = "firehose/arxiv backlog"
_FIELD_OF: Final[Mapping[str, str]] = {kind: key for key, kind in QUERY_FIELDS.items()}


def parse_query(text: str) -> Query:
    """`hf: agent memory` → ("hf_papers", "agent memory"), as questions/*.md writes it."""
    key, sep, rest = text.partition(":")
    kind = QUERY_FIELDS.get(key.strip())
    cleaned = clean_query(rest) if sep else None
    if kind is None or cleaned is None:
        fields = "|".join(QUERY_FIELDS)
        raise ValueError(f"not a query line (<{fields}>: <text>): {text!r}")
    return kind, cleaned


def query_line(query: Query) -> str:
    return f"{_FIELD_OF.get(query[0], query[0])}: {query[1]}"


# ------------------------------------------------------------------------ the candidate


class FirehoseSpec(Value):
    max: NonNegInt | None = None
    """Firehose sources kept per line-run; None = production's ([nets] firehose_max)."""
    backlog_days: NonNegInt = 0
    """0 = production: the room a small listing leaves stays empty."""


class QueryEdit(Value):
    drop: tuple[str, ...] = ()
    add: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _lines(self) -> "QueryEdit":
        for text in (*self.drop, *self.add):
            parse_query(text)
        return self


class Candidate(Value):
    """One configuration, as a TOML file (docs: AGENTS.md「入口を比べる」). Every key is
    optional; what it leaves out is production's."""

    name: NonEmptyText
    firehose: FirehoseSpec = FirehoseSpec()
    nets: dict[DiscoveryNet, bool] = Field(default_factory=dict[DiscoveryNet, bool])
    """A net set to false sends nothing."""
    body_floor: NonNegInt | None = None
    """Characters an abstract needs to be screened; None = production's
    (question_screening.MIN_ABSTRACT_CHARS). A repository keeps its own floor."""
    queries: dict[str, QueryEdit] = Field(default_factory=dict[str, QueryEdit])
    """Per line slug: query lines to drop from questions/<slug>.md and to add to it."""


BASELINE: Final = Candidate(name="baseline")


def load_candidate(path: Path) -> Candidate:
    return Candidate.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))


# ----------------------------------------------------------------------------- the line


@dataclass(frozen=True)
class LineSetup:
    """One line as a run of today would set it up."""

    slug: str
    ctx: LineContext
    questions: tuple[Question, ...]
    queries: Mapping[str, AuthoredQueries]
    """Question @id → its authored query lines."""
    nets: nets.NetConfig
    firehose_query: str

    @property
    def authored(self) -> tuple[Query, ...]:
        out: dict[Query, None] = {}
        for q in self.questions:
            for kind, text in self.queries.get(q.id, ()):
                if (cleaned := clean_query(text)) is not None:
                    out[(kind, cleaned)] = None
        return tuple(out)


def line_setup(env: Mapping[str, str], slug: str, *, now: AwareDatetime) -> LineSetup:
    """Raises KeyError for a slug config.toml does not have, NoQuestions like a run."""
    tracks = {t.slug: t for t in env_tracks(env)}
    ctx = line_context(tracks[slug])
    questions = tuple(open_questions(env, slug, line=ctx.line.id, now=now))
    queries = question_queries(env, slug, questions)
    cfg = config_path(env)
    return LineSetup(
        slug=slug,
        ctx=ctx,
        questions=questions,
        queries=queries,
        nets=nets.for_line(cfg, slug, nets.load_nets(cfg)),
        firehose_query=firehose_query(questions, queries, ctx.vocabulary),
    )


# -------------------------------------------------------------------------- the arms


@dataclass(frozen=True)
class Arm:
    """One configuration as the replay applies it to one line."""

    name: str
    cap: int
    backlog_days: int
    off: frozenset[str]
    floor: int | None
    queries: tuple[Query, ...]
    """The line's query set under this configuration, in rotation order."""
    dropped: frozenset[Query]

    def screenable(self, source: SourceItem) -> bool:
        if self.floor is None or source.adapter == "github":
            return not question_screening.no_abstract(source)
        return len(source.text) >= self.floor


def arm(candidate: Candidate, setup: LineSetup) -> Arm:
    edit = candidate.queries.get(setup.slug, QueryEdit())
    dropped = frozenset(parse_query(q) for q in edit.drop)
    kept = [q for q in setup.authored if q not in dropped]
    added = [q for q in (parse_query(a) for a in edit.add) if q not in kept]
    cap = candidate.firehose.max
    return Arm(
        name=candidate.name,
        cap=setup.nets.firehose_max if cap is None else cap,
        backlog_days=candidate.firehose.backlog_days,
        off=frozenset(net for net, on in candidate.nets.items() if not on),
        floor=candidate.body_floor,
        queries=(*kept, *added),
        dropped=dropped,
    )


def authored_for(setup: LineSetup, queries: Sequence[Query]) -> dict[str, AuthoredQueries]:
    """`queries` back in run.authored_candidates' shape: each kept line under its own
    question, an added line under the first question."""
    wanted = set(queries)
    out: dict[str, list[tuple[AdapterKind, str]]] = {}
    placed: set[Query] = set()
    for q in setup.questions:
        for kind, text in setup.queries.get(q.id, ()):
            cleaned = clean_query(text)
            if cleaned is not None and (kind, cleaned) in wanted:
                out.setdefault(q.id, []).append((kind, cleaned))
                placed.add((kind, cleaned))
    if setup.questions:
        first = setup.questions[0].id
        out.setdefault(first, []).extend(q for q in queries if q not in placed)
    return {k: tuple(v) for k, v in out.items() if v}


def sends(
    setup: LineSetup,
    queries: Sequence[Query],
    *,
    turn: int,
    runs: int,
    today: date,
    env: Mapping[str, str],
) -> dict[Query, int]:
    """How often each query goes out over the next `runs` runs (turn, turn + 1, …), by the
    run's own rotation (run.authored_candidates) and keyword budget (nets.plan)."""
    available: list[AdapterKind] = [
        kind
        for kind in setup.ctx.line.adapters
        if (need := make_adapter(kind, today=today).required_env) is None or env.get(need)
    ]
    mapping = authored_for(setup, queries)
    out: dict[Query, int] = dict.fromkeys(queries, 0)
    for r in range(runs):
        candidates, _ = authored_candidates(
            setup.ctx.line.id, setup.questions, mapping, kinds=available, turn=turn + r
        )
        keyword = [(make_adapter(c.adapter, today=today), c.text) for c in candidates]
        plan = nets.plan(
            setup.nets,
            hf_date="",
            keyword_queries=keyword,
            positives=[],
            negatives=[],
            cited=[],
            topics=[],
        )
        for request in plan:
            if request.net == "keyword":
                key: Query = (request.adapter.kind, request.query)
                out[key] = out.get(key, 0) + 1
    return out


def turn_of(nodes: Mapping[str, GraphNodeType], line: str, today: date) -> int:
    """The line's earlier runs, as run.LineRun._queries counts them for the rotation."""
    return sum(
        1 for n in nodes.values() if isinstance(n, Report) and n.line == line and n.run_date < today
    )


# ---------------------------------------------------------------------- the frozen set


@dataclass(frozen=True)
class Fetch:
    """One recorded request of one day."""

    day: date
    net: str
    adapter: str
    query: Query | None
    """A keyword request's query; None for a code-built one (or one no text hashes to)."""
    outputs: tuple[str, ...]

    @property
    def source(self) -> str:
        return f"{self.net}/{self.adapter}"

    @property
    def via(self) -> str:
        if self.net == "keyword" and self.query is not None:
            return f"keyword/{query_line(self.query)}"
        return self.source


@dataclass(frozen=True)
class FrozenSet:
    slug: str
    sources: Mapping[str, SourceItem]
    fetches: tuple[Fetch, ...]
    keys: Mapping[str, str]
    """Source @id → paper key."""
    first: Mapping[str, date]
    """Paper key → the first day a fetch of this set returned one of its sources."""
    judged_on: Mapping[str, date]
    """Source @id → the first day a prefilter Judgment of it is dated."""

    def days(self, start: date, end: date) -> list[date]:
        return sorted({f.day for f in self.fetches if start <= f.day <= end})


def _keyword_key(query: Query, day: date) -> str:
    """adapters.collect's stage input for a keyword request."""
    return input_sha256(
        {"adapter": query[0], "net": "keyword", "query": query[1], "run_date": day.isoformat()}
    )


def frozen_set(slug: str, nodes: Mapping[str, GraphNodeType], texts: Iterable[Query]) -> FrozenSet:
    """The partition's fetches; `texts` are query lines beyond the stored QueryCandidates
    (the authored and the candidate's) whose keyword records should be named."""
    sources = {n.id: n for n in nodes.values() if isinstance(n, SourceItem)}
    records = sorted(
        (n for n in nodes.values() if isinstance(n, StageRecord) and n.stage.startswith("fetch_")),
        key=lambda r: (r.completed_at, r.id),
    )
    queries: set[Query] = set(texts)
    queries |= {(q.adapter, q.text) for q in nodes.values() if isinstance(q, QueryCandidate)}
    days = {r.completed_at.date() for r in records}
    named = {_keyword_key(q, d): q for q in queries for d in days}
    fetches: list[Fetch] = []
    for r in records:
        net, _, adapter = r.stage.removeprefix("fetch_").partition("_")
        fetches.append(
            Fetch(
                day=r.completed_at.date(),
                net=net,
                adapter=adapter,
                query=named.get(r.input_sha256) if net == "keyword" else None,
                outputs=tuple(o for o in r.outputs if o in sources),
            )
        )
    keys = {sid: paper_key(s) for sid, s in sources.items()}
    first: dict[str, date] = {}
    for f in fetches:
        for sid in f.outputs:
            k = keys[sid]
            if f.day < first.get(k, date.max):
                first[k] = f.day
    judged_on: dict[str, date] = {}
    for n in nodes.values():
        if isinstance(n, Judgment) and n.function == "question_prefilter":
            day = n.judged_at.date()
            sid = n.subjects[0]
            if day < judged_on.get(sid, date.max):
                judged_on[sid] = day
    return FrozenSet(slug, sources, tuple(fetches), keys, first, judged_on)


# ---------------------------------------------------------------------------- replay


@dataclass(frozen=True)
class Reach:
    """One configuration's replay took `source` on `day`, through `via`."""

    day: date
    source: str
    via: str


def _firehose(
    todays: Sequence[Fetch], frozen: FrozenSet, setup: LineSetup, arm: Arm
) -> tuple[list[tuple[str, str]], int]:
    """(source @id, via) the firehose keeps today, and the slots it used."""
    order = {"hf_papers": 0, "arxiv": 1}  # nets.plan sends HF daily first
    listings = sorted(
        (f for f in todays if f.net == "firehose"), key=lambda f: order.get(f.adapter, 2)
    )
    seen: set[str] = set()
    taken: list[tuple[str, str]] = []
    for f in listings:
        fresh = [frozen.sources[i] for i in f.outputs if i not in seen]
        query = setup.firehose_query if f.adapter == "arxiv" else ""
        kept, _ = nets.firehose_cut(fresh, max(arm.cap - len(seen), 0), query)
        seen.update(s.id for s in kept)
        taken += [(s.id, f.source) for s in kept]
    return taken, len(seen)


def _backlog(
    day: date,
    room: int,
    frozen: FrozenSet,
    setup: LineSetup,
    arm: Arm,
    *,
    reached: set[str],
    start: date,
) -> list[str]:
    """The room filled from the arXiv listings of the backlog days, newest first, ranked."""
    if room <= 0:
        return []
    since = day - timedelta(days=arm.backlog_days)
    listings = sorted(
        (
            f
            for f in frozen.fetches
            if f.net == "firehose" and f.adapter == "arxiv" and since <= f.day < day
        ),
        key=lambda f: f.day,
        reverse=True,
    )
    pool: dict[str, SourceItem] = {}
    for f in listings:
        for sid in f.outputs:
            s = frozen.sources[sid]
            if sid in reached or sid in pool or not arm.screenable(s):
                continue
            if f.day < start and frozen.judged_on.get(sid, date.max) < start:
                continue  # before the window: production prefiltered it then
            pool[sid] = s
    kept, _ = nets.firehose_cut(list(pool.values()), room, setup.firehose_query)
    return [s.id for s in kept]


def replay(
    frozen: FrozenSet, setup: LineSetup, arm: Arm, days: Sequence[date], *, start: date
) -> list[Reach]:
    """Every (day, source, via) the configuration reaches over `days` (module docstring)."""
    out: list[Reach] = []
    reached: set[str] = set()
    for day in sorted(days):
        todays = [f for f in frozen.fetches if f.day == day]
        got: list[tuple[str, str]] = []
        if "firehose" not in arm.off:
            kept, used = _firehose(todays, frozen, setup, arm)
            got += kept
            if arm.backlog_days:
                ids = {sid for sid, _ in kept}
                fill = _backlog(
                    day, arm.cap - used, frozen, setup, arm, reached=reached | ids, start=start
                )
                got += [(sid, BACKLOG) for sid in fill]
        for f in todays:
            if f.net == "firehose" or f.net in arm.off:
                continue
            if f.net == "keyword" and f.query is not None and f.query in arm.dropped:
                continue
            got += [(sid, f.via) for sid in f.outputs]
        for sid, via in dict.fromkeys(got):
            out.append(Reach(day, sid, via))
        reached |= {sid for sid, _ in got}
    return out


# ---------------------------------------------------------------------------- scoring


@dataclass(frozen=True)
class Verdict:
    """The prefilter's answer on one source for today's open questions."""

    passes: bool
    best: float
    """The highest on_topic over the questions."""
    margin: float
    """How far the answer is from the other side of the cut: for a pass, the highest
    passing on_topic's distance above it (every passing one must fall); for a fail, the
    highest one's distance below it."""
    fresh: bool = False
    """Asked by this eval (not in the store)."""


def verdict_of(probabilities: Sequence[float], *, fresh: bool = False) -> Verdict:
    best = max(probabilities)
    return Verdict(best >= CUT, best, abs(best - CUT), fresh)


@dataclass(frozen=True)
class SelfCheck:
    days: int
    matched: int
    """Days whose replayed baseline prefiltered exactly what production prefiltered."""
    off: tuple[tuple[date, int, int], ...]
    """(day, replayed only, production only) of the days that did not match."""


@dataclass(frozen=True)
class Score:
    arm: str
    reached: int
    """Distinct sources the configuration reached in the window."""
    screened: int
    """Of them, past the floor and never prefiltered before the window: the prefilter
    requests the window costs (a source judged earlier is answered by run.StoredJev, unless
    its text changed since)."""
    unjudged: int
    """Past the floor with no answer (no key, a failed request): N_ot is a lower bound."""
    keys: int
    keys_new: int
    n_ot: int
    per_day: Mapping[date, int]
    """N_ot by the day each paper first passed."""
    found: Mapping[str, frozenset[str]]
    """N_ot paper key → every via that reached a passing source of it."""
    first_day: Mapping[str, date]
    delay: Mapping[str, int]
    """N_ot paper key → days from its first fetch to its first pass (a backlog fill is late)."""
    chao_all: Chao2 | None
    chao_unseeded: Chao2 | None
    units: int


def screenable_reached(
    reaches: Iterable[Reach], frozen: FrozenSet, arm: Arm
) -> dict[str, SourceItem]:
    return {r.source: s for r in reaches if arm.screenable(s := frozen.sources[r.source])}


def _incidence(
    frozen: FrozenSet, arm: Arm, ot: set[str], days: Sequence[date], *, seeded: bool
) -> tuple[list[int], int]:
    """Chao2's input: per new on-topic key, the request-days of the query nets that
    returned a source of it; and the number of request-days (units)."""
    window = set(days)
    units = [
        f
        for f in frozen.fetches
        if f.day in window
        and f.net in QUERY_NETS
        and f.net not in arm.off
        and (seeded or f.net not in SEEDED)
        and not (f.net == "keyword" and f.query is not None and f.query in arm.dropped)
    ]
    counts: dict[str, int] = {}
    for unit in units:
        for k in {frozen.keys[sid] for sid in unit.outputs} & ot:
            counts[k] = counts.get(k, 0) + 1
    return list(counts.values()), len(units)


def score(
    frozen: FrozenSet,
    arm: Arm,
    reaches: Sequence[Reach],
    verdicts: Mapping[str, Verdict],
    *,
    known: frozenset[str],
    days: Sequence[date],
) -> Score:
    """`known`: paper keys fetched before the window (never new)."""
    start = min(days, default=date.max)
    screen = screenable_reached(reaches, frozen, arm)
    keys = {frozen.keys[r.source] for r in reaches}
    found: dict[str, set[str]] = {}
    first_day: dict[str, date] = {}
    for r in sorted(reaches, key=lambda r: (r.day, r.source, r.via)):
        key = frozen.keys[r.source]
        v = verdicts.get(r.source)
        if key in known or r.source not in screen or v is None or not v.passes:
            continue
        found.setdefault(key, set()).add(r.via)
        first_day.setdefault(key, r.day)
    per_day: dict[date, int] = dict.fromkeys(days, 0)
    for day in first_day.values():
        per_day[day] = per_day.get(day, 0) + 1
    delay = {k: (d - frozen.first.get(k, d)).days for k, d in first_day.items()}
    ot = set(found)
    counts, units = _incidence(frozen, arm, ot, days, seeded=True)
    counts_u, units_u = _incidence(frozen, arm, ot, days, seeded=False)
    return Score(
        arm=arm.name,
        reached=len({r.source for r in reaches}),
        screened=sum(1 for sid in screen if frozen.judged_on.get(sid, date.max) >= start),
        unjudged=sum(1 for sid in screen if sid not in verdicts),
        keys=len(keys),
        keys_new=len(keys - known),
        n_ot=len(found),
        per_day=per_day,
        found={k: frozenset(v) for k, v in found.items()},
        first_day=first_day,
        delay=delay,
        chao_all=chao2(counts, units),
        chao_unseeded=chao2(counts_u, units_u),
        units=units,
    )


def self_check(
    frozen: FrozenSet, reaches: Sequence[Reach], arm: Arm, days: Sequence[date]
) -> SelfCheck:
    """The baseline's replay against what production prefiltered (module docstring). A
    source production judged on an earlier day is not asked again (StoredJev), so a replayed
    source counts as matched when its first prefilter Judgment is that day or earlier."""
    off: list[tuple[date, int, int]] = []
    for day in days:
        replayed = {
            r.source for r in reaches if r.day == day and arm.screenable(frozen.sources[r.source])
        }
        today = {sid for f in frozen.fetches if f.day == day for sid in f.outputs}
        production = {sid for sid in today if frozen.judged_on.get(sid) == day}
        extra = {sid for sid in replayed - production if frozen.judged_on.get(sid, date.max) > day}
        missing = production - replayed
        if extra or missing:
            off.append((day, len(extra), len(missing)))
    return SelfCheck(len(days), len(days) - len(off), tuple(off))


@dataclass(frozen=True)
class SourceRow:
    """One net or one keyword query, under one configuration."""

    via: str
    found: int
    unique: int


def by_source(found: Mapping[str, frozenset[str]]) -> list[SourceRow]:
    """N_ot found through each via and through it alone; nets first (the via's head), then
    the vias under each, largest first."""
    rows: dict[str, list[int]] = {}
    for vias in found.values():
        heads = {v.split("/", 1)[0] for v in vias}
        for name in (*heads, *vias):
            row = rows.setdefault(name, [0, 0])
            row[0] += 1
        if len(heads) == 1:
            rows[next(iter(heads))][1] += 1
        if len(vias) == 1:
            rows[next(iter(vias))][1] += 1
    return sorted(
        (SourceRow(name, f, u) for name, (f, u) in rows.items()),
        key=lambda r: ("/" in r.via, -r.found, r.via),
    )


@dataclass(frozen=True)
class QueryYield:
    """One keyword query's sends in the history."""

    query: Query
    sends: int
    new: tuple[int, ...]
    """Keys new to the line per send (first fetched that day), oldest first."""
    ot: tuple[int, ...]
    """Of them, passing the prefilter, per send."""

    @property
    def exhausted(self) -> bool:
        """Its last EXHAUSTED_SENDS sends brought no key new to the line (the weekly
        review's definition)."""
        return len(self.new) >= EXHAUSTED_SENDS and not any(self.new[-EXHAUSTED_SENDS:])


EXHAUSTED_SENDS: Final = 3
YIELD_SENDS: Final = 5
"""The per-send yield of a query is read over its last this many sends."""


def query_yields(
    frozen: FrozenSet,
    verdicts: Mapping[str, Verdict],
    queries: Iterable[Query],
    *,
    until: date,
) -> list[QueryYield]:
    """Each query's sends up to `until`, in the history (all of it, not only the window)."""
    out: list[QueryYield] = []
    for query in queries:
        new: list[int] = []
        ot: list[int] = []
        for f in frozen.fetches:
            if f.net != "keyword" or f.query != query or f.day > until:
                continue
            fresh = {
                frozen.keys[sid]: sid
                for sid in f.outputs
                if frozen.first.get(frozen.keys[sid]) == f.day
            }
            new.append(len(fresh))
            ot.append(sum(1 for sid in fresh.values() if (v := verdicts.get(sid)) and v.passes))
        out.append(QueryYield(query, len(new), tuple(new), tuple(ot)))
    return out


@dataclass(frozen=True)
class RotationEstimate:
    """New on-topic papers per run the keyword net is expected to bring under one query set:
    Σ over queries of (sends per run) x (new on-topic per send over its last YIELD_SENDS
    sends). A model: a query's next send yields what its last sends did."""

    per_run: float
    missing: tuple[Query, ...]
    """Queries with no send in the history (an added one): not in the sum."""


@dataclass(frozen=True)
class RotationDiff:
    base: RotationEstimate
    cand: RotationEstimate
    delta: float
    low: float
    high: float
    """Poisson (normal approximation with a half count) over the yields' counts."""
    freed: float
    """Keyword requests per run the candidate sends fewer (negative: more)."""


def rotation(
    yields: Mapping[Query, QueryYield],
    base_sends: Mapping[Query, int],
    cand_sends: Mapping[Query, int],
    *,
    runs: int,
) -> RotationDiff:
    def estimate(rates: Mapping[Query, int]) -> RotationEstimate:
        total = 0.0
        missing: list[Query] = []
        for q, n in rates.items():
            y = yields.get(q)
            if y is None or not y.ot:
                if n:
                    missing.append(q)
                continue
            last = y.ot[-YIELD_SENDS:]
            total += n / runs * sum(last) / len(last)
        return RotationEstimate(total, tuple(missing))

    base, cand = estimate(base_sends), estimate(cand_sends)
    variance = 0.0
    for q in set(base_sends) | set(cand_sends):
        y = yields.get(q)
        if y is None or not y.ot:
            continue
        last = y.ot[-YIELD_SENDS:]
        weight = (cand_sends.get(q, 0) - base_sends.get(q, 0)) / runs / len(last)
        variance += weight * weight * (sum(last) + 0.5)
    half = 1.959963984540054 * variance**0.5
    delta = cand.per_run - base.per_run
    freed = (sum(base_sends.values()) - sum(cand_sends.values())) / runs
    return RotationDiff(base, cand, delta, delta - half, delta + half, freed)


@dataclass(frozen=True)
class SnapshotQuery:
    """One query in today's snapshot."""

    query: Query
    results: int
    new: int
    """Keys the store never fetched for the line."""
    ot: int


@dataclass
class Snapshot:
    day: date
    queries: list[SnapshotQuery] = field(default_factory=list[SnapshotQuery])
    base_next: int = 0
    cand_next: int = 0
    """New on-topic keys the next run's keyword sends would bring, today."""
    base_sent: int = 0
    cand_sent: int = 0
