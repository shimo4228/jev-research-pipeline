"""`jrp wbr`: the weekly review of one ISO week, from the store alone (plan quality-metrics
claim 5; research report 2026-10-20 §8; synthesis 2026-10-20, v0 scope).

The question it answers each week: which part of the pipeline, touched next week, would
bring the author the most new evidence. v0 stops at the breakdown: it reports the outputs,
the exceptions, the cohort breakdown, the questions, repetition, delivery and the
instruments, and it never picks the one change for next week (sections 4 and 8 say so).

Reads, never writes, the store: the partitions are loaded through registry.read_snapshot
(an additive @context is lifted in memory, an incompatible one raises StoreSchemaError,
which `jrp wbr` turns into one line and exit 2), plus metrics/opened.jsonl, questions/ and
config.toml. It writes the note `<out>/<Monday after the week>_jrp_wbr.md` (its name holds
`_jrp_`, so the used scan skips it by name, and the slug `wbr` is reserved, so no line's
`*_jrp_<slug>.md` glob harvests it) and one appended line of
`<store>/metrics/weekly.jsonl` with every number of the note, raw: a past week recomputed
from the store later drifts with every upsert, so the row keeps the week as it read then
(v0 writes it and reads nothing back; the six weeks of O1 are recomputed). Rerunning a week
appends another row. With ANTHROPIC_API_KEY set, the monitoring judge (pipeline.monitor)
also calls the Claude API on a seeded sample of the week and appends two lines per call to
`<store>/metrics/judge.jsonl` (its reservation at its bound, then its price), under the lock
file `judge.jsonl.lock` beside it; without it nothing is called and section 1 says 未測定 (key
なし). The note's body holds no source key (arXiv id, DOI, GitHub owner/repo, URL) and no
`jrp:` mark, and nothing in it executes or fetches in Obsidian: every string from outside jrp
it prints (DEGRADED reasons, an instrument's broken invariant; slugs and the note_text Msgs
are jrp's own) goes through printable, which replaces the keys and the mark, then sanitizes
(report.markdown.sanitize), then cuts.

Every number is read as of the week's last day: nodes dated later are left out. Numbers
are compared only where the instrument registry (pipeline.registry) calls them alive:
- a number an instrument reads directly is printed only when its status over the week is
  live or expected-zero, else the status word: O1 (o1, per line over that line's runs), the
  slots of section 6 (claims_posted), writer calls and Jev tokens per O1 (writer_calls,
  jev_tokens), new ticks (label.first_harvest), opened notes (opened);
- a cohort's intake factors (N_new, N_ot, p_sel) print the word of a failing firehose
  instrument, and its output factors (p_wri, O1_c) of a failing o1, over the cohort's week
  and its 7 days after.
Exceptions (section 2): the instruments whose status over the week is a failure
(registry.FAILURES: contradiction, missing, unexplained-zero, stuck; a declared, expected or
too-few reading is listed in section 9, not here), the open questions that did not move, and
the lines that ran in the week and first-cited no paper.

Definitions:
- paper key: one key per source, from SourceItem.url by the rules of reduction.used
  (keys_of_text): arXiv id, else DOI, else GitHub owner/repo, else the normalized URL. Two
  sources of one paper (an arXiv and an HF URL) are one paper.
- O1: papers whose first [n] citation in any line's prose falls in the week. A
  QuestionLog's [n] is claims[n-1] of that question-day (each section numbers its own
  claims), resolved Claim → Unit → SourceItem → paper key; Report.claims is never read. A
  paper cited by two lines counts once; the per-line rows count it for each line that cited
  it on that first day. Interval: Garwood's exact Poisson 95%.
- O2: Sightings first seen in the last 30 days, not baseline, not unsure, with an arXiv,
  DOI or GitHub key; a hit when jrp first cited that key before first_seen. k/n only below
  n = 20. The used scan reads graph.jsonld and ADRs only (author decision 2026-10-20), and
  the author reads jrp before writing, so it is an upper bound.
- Cohort: the (line, paper key) pairs first fetched in one ISO week (the first day a
  StageRecord(fetch_*) output holds one of the paper's sources). Each later stage counts the
  pairs of the stage before that reached it within 7 days of their first fetch: N_ot = the
  text clears the screening floor (question_screening.no_abstract) and the prefilter passes
  some question (question_prefilter.passing over the stored Judgment), p_sel = a screening
  Judgment routes keep (question_screening.route over judged_of), p_ext = a claim of the
  paper is on some QuestionLog.claims, p_wri = the paper is [n]-cited. O1_c = N_ot x
  p_sel x p_ext x p_wri exactly, so Δln O1_c is the sum of the factors' Δln. A cohort is
  mature 7 days after its week ends; the review compares the two latest. SE is the delta
  method on Poisson counts and binomial shares, provisional: papers of one run and one
  question are not independent, so it reads small.
- Slot-bound line: its notes of the week left at most 30% of their slots free, a note's
  slots being run.claims_per_question(k) x k at the run's k open questions.
- Question moved: it holds an O1 paper of the last 14 days (cited on that paper's first
  day). A question that did not is shown with the first stage at 0 over the same 14 days:
  sources screened for it, of those kept, sources of its claims, sources its prose cited.
  The open questions come from questions/ (questions.open_questions), never from Question
  nodes, which a run stores only when evidence grows.
- Monitoring samples (pipeline.monitor, monitor_sample): the week's sections with prose
  (QuestionLogs of the week with text; the question is the stored Question node, else the
  one of questions/), and the week's O1 papers, each with the claim of its first-day [n]
  (the first by line, question and claim when several cited it that day).
"""

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Final, Literal

import httpx2
from pydantic import AwareDatetime, JsonValue

from jev_research_pipeline import note_text as t
from jev_research_pipeline.generation.prose import citations
from jev_research_pipeline.jev import judged_of, question_prefilter, question_screening
from jev_research_pipeline.model import (
    Claim,
    GraphNodeType,
    Judgment,
    Label,
    Question,
    QuestionLog,
    Report,
    RunRecord,
    Sighting,
    SourceItem,
    StageRecord,
    Unit,
    kind_of,
)
from jev_research_pipeline.note_text import Lang, Msg, note_lang
from jev_research_pipeline.questions import NoQuestions, open_questions
from jev_research_pipeline.reduction.used import keys_of_text
from jev_research_pipeline.report.markdown import sanitize
from jev_research_pipeline.store import GraphStore

from . import monitor
from .config import config_path, env_tracks, line_context
from .metrics import append_row
from .monitor import FIDELITY_N, PRECISION_N, STOP_WORDS, MonitorResult, Tally
from .nets import for_line, load_nets, paper_id
from .prose_bench import case_of
from .registry import (
    FAILURES,
    REGISTRY,
    STATUS_WORDS,
    InstrumentStatus,
    Part,
    Snapshot,
    Status,
    line_runs,
    read_snapshot,
    status,
)
from .run import claims_per_question
from .runner import store_dir

NOTE_SLUG: Final = "wbr"
"""The note is `<date>_jrp_wbr.md`; config.RESERVED_SLUGS keeps any line off this slug."""
WEEKLY_FILE: Final = Path("metrics", "weekly.jsonl")
"""Under the store root; like metrics/opened.jsonl, no partition (store.migrate skips it)."""
WEEKS_SHOWN: Final = 6
COHORT_DAYS: Final = 7
QUESTION_DAYS: Final = 14
O2_DAYS: Final = 30
O2_MIN_N: Final = 20
"""Below this many new keys O2 is k/n with no rate (synthesis 2026-10-20, O2 guard)."""
SLOT_BOUND_FREE: Final = 0.30
NOISE_SE: Final = 2.0
"""|Δln| beyond this many SE is outside the noise."""
REASONS_SHOWN: Final = 8
Z95: Final = 1.959963984540054
PAPER_PREFIXES: Final = ("arxiv:", "doi:", "gh:", "url:")
"""The paper key's precedence (O2 counts the first three only)."""
USABLE: Final[frozenset[Status]] = frozenset({"live", "expected-zero"})
"""A number the review prints as a number; any other status prints its word."""
INTAKE: Final = ("firehose.arxiv", "firehose.hf")
"""The instruments under N_ot: a failing fetch hides the intake factors of a cohort."""
OUTPUT: Final = ("o1",)

PRINTABLE_CHARS: Final = 160
"""The most characters of one outside string the note prints (printable)."""

_PREFILTER: Final = "question_prefilter"
_SCREENING: Final = "question_screening"
_WEEK_RE: Final = re.compile(r"^(\d{4})-W(\d{2})$")
_ON_TOPIC: Final = re.compile(r"^q\d+_on_topic$")
_SCRUB: Final = re.compile(
    r"https?://\S+"
    r"|\b10\.\d{4,9}/\S+"
    r"|(?:arxiv(?:\.org)?[:/.\s]*(?:(?:abs|pdf)/)?|/(?:abs|pdf|papers)/)"
    r"\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}\S*"
    r"|github\.com/[\w.-]+/[\w.-]+\S*",
    re.IGNORECASE,
)
"""A source key in any case: a URL, a DOI, an arXiv id with the context reduction.used reads
it by (`arXiv:`, `arxiv.org/abs/`, `/papers/`), a GitHub owner/repo; scheme or none."""
_MARK: Final = re.compile(r"(jrp):", re.IGNORECASE)
_HALF: Final = re.compile(r"(?:\\+|&[#\w]*)$")
"""What a cut can leave half-written at the end: an escape's backslash, an entity before
its `;`."""

type FactorName = Literal["N_new", "N_ot", "p_sel", "p_ext", "p_wri", "O1_c"]
type GroupKind = Literal["all", "slot", "supply"]
type Stage = Literal["screening", "keep", "claim", "cite", "delivered"]


# ------------------------------------------------------------------------------- the week


@dataclass(frozen=True, order=True)
class Week:
    """One ISO week, Monday to Sunday."""

    start: date

    @classmethod
    def parse(cls, text: str) -> "Week":
        """`YYYY-Www`; ValueError for anything else, or a week the year does not have."""
        m = _WEEK_RE.match(text)
        if m is None:
            raise ValueError(f"not an ISO week (YYYY-Www): {text!r}")
        return cls(date.fromisocalendar(int(m[1]), int(m[2]), 1))

    @classmethod
    def of(cls, day: date) -> "Week":
        return cls(day - timedelta(days=day.weekday()))

    @classmethod
    def last_complete(cls, today: date) -> "Week":
        """The latest week that ended before `today`: on a Monday, the week before it."""
        return cls.of(today).shifted(-1)

    @property
    def end(self) -> date:
        return self.start + timedelta(days=6)

    @property
    def label(self) -> str:
        year, week, _ = self.start.isocalendar()
        return f"{year}-W{week:02d}"

    @property
    def short(self) -> str:
        return f"W{self.start.isocalendar()[1]:02d}"

    @property
    def note_date(self) -> date:
        """The Monday after the week: the morning the review is made."""
        return self.start + timedelta(days=7)

    def shifted(self, weeks: int) -> "Week":
        return Week(self.start + timedelta(weeks=weeks))

    def holds(self, day: date) -> bool:
        return self.start <= day <= self.end


def note_name(week: Week) -> str:
    return f"{week.note_date.isoformat()}_jrp_{NOTE_SLUG}.md"


# ----------------------------------------------------------------------------- statistics


def _poisson_cdf(k: int, mean: float) -> float:
    """P(X ≤ k) for X ~ Poisson(mean)."""
    if k < 0:
        return 0.0
    if mean <= 0:
        return 1.0
    log_mean = math.log(mean)
    return math.fsum(math.exp(i * log_mean - mean - math.lgamma(i + 1)) for i in range(k + 1))


def _root(f: Callable[[float], float], high: float) -> float:
    """The root on [0, high] of an f that falls from positive to negative (bisection)."""
    low = 0.0
    for _ in range(200):
        mid = (low + high) / 2
        if f(mid) > 0:
            low = mid
        else:
            high = mid
        if high - low < 1e-9:
            break
    return (low + high) / 2


def poisson_interval(k: int, confidence: float = 0.95) -> tuple[float, float]:
    """Garwood's exact interval for a count k: the means at which a count of k or more
    (lower end) and of k or fewer (upper end) each has probability (1 - confidence) / 2."""
    tail = (1.0 - confidence) / 2.0
    top = k + 10.0 * math.sqrt(k + 1.0) + 10.0
    lower = 0.0 if k == 0 else _root(lambda m: tail - (1.0 - _poisson_cdf(k - 1, m)), top)
    upper = _root(lambda m: _poisson_cdf(k, m) - tail, top)
    return lower, upper


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson's interval for a share k/n (n > 0)."""
    p = k / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denominator
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class Measure:
    """One factor of one cohort: a count (n None, Poisson) or a share k/n (binomial)."""

    k: int
    n: int | None = None

    @property
    def value(self) -> float | None:
        if self.n is None:
            return float(self.k)
        return self.k / self.n if self.n else None

    @property
    def ln_var(self) -> float | None:
        """Delta-method variance of ln(value): 1/k for a count, 1/k - 1/n for a share;
        None at k = 0 (no logarithm)."""
        if self.k == 0:
            return None
        return 1.0 / self.k if self.n is None else 1.0 / self.k - 1.0 / self.n


def shift(old: Measure, new: Measure) -> tuple[float, float] | None:
    """(Δln, SE) from old to new; None when either has no logarithm."""
    a, b, va, vb = old.value, new.value, old.ln_var, new.ln_var
    if a is None or b is None or va is None or vb is None:
        return None
    return math.log(b / a), math.sqrt(va + vb)


# ----------------------------------------------------------------------------- paper keys


def paper_key(source: SourceItem) -> str:
    """One key per source (module docstring): the first of arXiv id, DOI, GitHub
    owner/repo and normalized URL that keys_of_text finds in its URL."""
    keys = keys_of_text(source.url)
    for prefix in PAPER_PREFIXES:
        found = sorted(k for k in keys if k.startswith(prefix))
        if found:
            return found[0]
    return f"url:{source.url.lower()}"


def printable(text: str, limit: int = PRINTABLE_CHARS) -> str:
    """Text from outside jrp (a DEGRADED reason, which may quote an exception about a
    third-party excerpt; an instrument's broken invariant, which may name a listed note),
    printable in the note. First every source key becomes `<url>` and a `jrp:` becomes
    `jrp :`, then report.markdown.sanitize(one_line=True) leaves nothing Obsidian executes or
    fetches (embed, remote image, HTML and comments, inline Dataview, wikilink, `%%`), then
    the result is cut to `limit` characters. The cut comes after sanitize and drops an escape
    or an entity it split, so it cannot reopen what sanitize closed."""
    scrubbed = _MARK.sub(r"\1 :", _SCRUB.sub("<url>", text))
    out = sanitize(scrubbed, one_line=True)
    if len(out) <= limit:
        return out
    out = out[:limit]
    while (shorter := _HALF.sub("", out)) != out:
        out = shorter
    return out


# ------------------------------------------------------------------------------ the store


@dataclass(frozen=True)
class LineSpec:
    """One configured line as questions/ has it."""

    slug: str
    questions: tuple[Question, ...] | None
    """Its open questions (questions.open_questions); None = 問い未設定."""
    name: str = ""
    """The line's name and vocabulary (config.line_context), as the writer was given them:
    the monitoring judge's materials name the line by them ("" = the slug)."""
    vocabulary: tuple[str, ...] = ()


@dataclass(frozen=True)
class Inputs:
    snapshot: Snapshot
    lines: tuple[LineSpec, ...]
    """Every configured line, in config order."""


def read_inputs(env: Mapping[str, str], *, now: AwareDatetime) -> Inputs:
    """config.toml, questions/ and the store, writing nothing."""
    tracks = env_tracks(env)
    cfg = config_path(env)
    nets = load_nets(cfg)
    specs: list[LineSpec] = []
    for track in tracks:
        ctx = line_context(track)
        try:
            questions = tuple(open_questions(env, track.slug, line=ctx.line.id, now=now))
        except NoQuestions:
            questions = None
        specs.append(LineSpec(track.slug, questions, ctx.line.name, ctx.vocabulary))
    firehose = {t.slug: for_line(cfg, t.slug, nets).budget("firehose") for t in tracks}
    snapshot = read_snapshot(
        GraphStore(store_dir(env)), [t.slug for t in tracks], firehose=firehose
    )
    return Inputs(snapshot=snapshot, lines=tuple(specs))


def _of[N](nodes: Mapping[str, GraphNodeType], kind: type[N]) -> list[N]:
    return [n for n in nodes.values() if isinstance(n, kind)]


@dataclass(frozen=True)
class _Cite:
    day: date
    line: str
    question: str
    claim: str
    source: str
    key: str


@dataclass(frozen=True)
class _Post:
    day: date
    question: str
    source: str
    key: str


class _Line:
    """One line's partition as of a day, indexed once for every count of the review."""

    def __init__(self, slug: str, nodes: Mapping[str, GraphNodeType], as_of: date) -> None:
        self.slug = slug
        self.sources = {s.id: s for s in _of(nodes, SourceItem)}
        self.keys = {sid: paper_key(s) for sid, s in self.sources.items()}
        units = {u.id: u.source for u in _of(nodes, Unit)}
        self.claim_source = {
            c.id: units[c.unit]
            for c in _of(nodes, Claim)
            if c.unit in units and units[c.unit] in self.sources
        }
        logs = sorted(
            (q for q in _of(nodes, QuestionLog) if q.run_date <= as_of), key=lambda q: q.id
        )
        self.reports = sorted(
            (r for r in _of(nodes, Report) if r.run_date <= as_of), key=lambda r: r.run_date
        )
        self.judgments = [j for j in _of(nodes, Judgment) if j.judged_at.date() <= as_of]
        self.labels = _of(nodes, Label)
        fetches = [
            r
            for r in _of(nodes, StageRecord)
            if r.stage.startswith("fetch_") and r.completed_at.date() <= as_of
        ]
        self.keyword = [r for r in fetches if r.stage.startswith("fetch_keyword_")]
        self.first_fetch: dict[str, date] = {}
        for record in fetches:
            day = record.completed_at.date()
            for sid in record.outputs:
                if sid in self.sources and day < self.first_fetch.get(sid, date.max):
                    self.first_fetch[sid] = day
        self.cites = tuple(self._cites(logs))
        self.posts = tuple(self._posts(logs))
        self._by_key: dict[str, list[str]] = {}
        for sid, key in self.keys.items():
            self._by_key.setdefault(key, []).append(sid)
        self._by_source: dict[str, list[Judgment]] = {}
        for j in self.judgments:
            if j.function in (_PREFILTER, _SCREENING):
                self._by_source.setdefault(j.subjects[0], []).append(j)
        self._routes: dict[str, question_screening.Route | None] = {}
        self._on_topic: dict[str, date] = {}
        self._kept: dict[str, date] = {}

    def _cites(self, logs: Sequence[QuestionLog]) -> Iterator[_Cite]:
        """Every [n] of the line's prose that resolves to a source: [n] is claims[n-1] of
        its own question-day (generation.prose.citations)."""
        for log in logs:
            for n in sorted(citations(log.text)):
                claim = log.claims[n - 1] if 1 <= n <= len(log.claims) else ""
                if (sid := self.claim_source.get(claim)) is not None:
                    yield _Cite(log.run_date, self.slug, log.question, claim, sid, self.keys[sid])

    def _posts(self, logs: Sequence[QuestionLog]) -> Iterator[_Post]:
        """Every claim of a QuestionLog that resolves to a source."""
        for log in logs:
            for claim in log.claims:
                if (sid := self.claim_source.get(claim)) is not None:
                    yield _Post(log.run_date, log.question, sid, self.keys[sid])

    def units(self) -> dict[str, date]:
        """Paper key → the first day a fetch of this line returned one of its sources."""
        out: dict[str, date] = {}
        for sid, day in self.first_fetch.items():
            key = self.keys[sid]
            if day < out.get(key, date.max):
                out[key] = day
        return out

    def route(self, judgment: Judgment) -> question_screening.Route | None:
        """Today's route over a stored screening Judgment; None for one asked by another
        version of the screen, or whose source is not in the partition (a canary probe)."""
        if judgment.id not in self._routes:
            source = self.sources.get(judgment.subjects[0])
            judged = judged_of(question_screening.ASK, judgment)
            self._routes[judgment.id] = (
                None
                if judged is None or source is None
                else question_screening.route(judged, source=source)
            )
        return self._routes[judgment.id]

    def _first(self, key: str, function: str, hit: Callable[[SourceItem, Judgment], bool]) -> date:
        days = [
            j.judged_at.date()
            for sid in self._by_key.get(key, [])
            for j in self._by_source.get(sid, [])
            if j.function == function and hit(self.sources[sid], j)
        ]
        return min(days, default=date.max)

    def on_topic_day(self, key: str) -> date:
        """First day a source of the paper with text above the screening floor passed the
        prefilter for some question; date.max = never."""
        if key not in self._on_topic:
            self._on_topic[key] = self._first(
                key, _PREFILTER, lambda s, j: not question_screening.no_abstract(s) and _passes(j)
            )
        return self._on_topic[key]

    def kept_day(self, key: str) -> date:
        """First day a screening Judgment of a source of the paper routes keep."""
        if key not in self._kept:
            self._kept[key] = self._first(key, _SCREENING, lambda _, j: self.route(j) == "keep")
        return self._kept[key]


def _passes(judgment: Judgment) -> bool:
    """The prefilter, re-applied: the stored answers pass some question's on_topic cut."""
    n = sum(1 for a in judgment.answers if _ON_TOPIC.match(a.key))
    judged = judged_of(question_prefilter.ask(n), judgment) if n else None
    return judged is not None and bool(question_prefilter.passing(judged, n))


# -------------------------------------------------------------------------- the registry


class _Registry:
    """Instrument statuses over windows, computed once each."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self._cache: dict[tuple[str, date, date, str | None], InstrumentStatus] = {}

    def of(self, ident: str, start: date, end: date, line: str | None = None) -> Status:
        return self.full(ident, start, end, line).status

    def full(self, ident: str, start: date, end: date, line: str | None = None) -> InstrumentStatus:
        key = (ident, start, end, line)
        if key not in self._cache:
            snapshot = self.snapshot
            if line is not None:
                snapshot = replace(snapshot, lines={line: snapshot.lines.get(line, {})})
            instrument = next(i for i in REGISTRY if i.id == ident)
            self._cache[key] = status(instrument, snapshot, start=start, end=end)
        return self._cache[key]

    def failing(self, idents: Sequence[str], start: date, end: date) -> Status | None:
        """The most severe failure among the instruments over [start, end], if any."""
        found = {self.of(i, start, end) for i in idents}
        return next((s for s in FAILURES if s in found), None)


# ------------------------------------------------------------------------------ results


@dataclass(frozen=True)
class O1Week:
    week: Week
    total: int
    interval: tuple[float, float]
    status: Status
    """o1's status over the week (all lines)."""
    lines: Mapping[str, tuple[int, Status]]
    """Line slug → (its O1, o1's status over its own line-runs)."""


@dataclass(frozen=True)
class O2:
    k: int
    n: int


@dataclass(frozen=True)
class Funnel:
    new: int = 0
    on_topic: int = 0
    kept: int = 0
    posted: int = 0
    cited: int = 0

    def measure(self, name: FactorName) -> Measure:
        match name:
            case "N_new":
                return Measure(self.new)
            case "N_ot":
                return Measure(self.on_topic)
            case "p_sel":
                return Measure(self.kept, self.on_topic)
            case "p_ext":
                return Measure(self.posted, self.kept)
            case "p_wri":
                return Measure(self.cited, self.posted)
            case "O1_c":
                return Measure(self.cited)


FACTORS: Final[tuple[tuple[Part, FactorName], ...]] = (
    ("I", "N_new"),
    ("I", "N_ot"),
    ("S", "p_sel"),
    ("X", "p_ext"),
    ("W", "p_wri"),
    ("OUT", "O1_c"),
)
"""The breakdown's rows. N_ot x p_sel x p_ext x p_wri = O1_c; N_new is N_ot's supply."""
IDENTITY: Final[tuple[FactorName, ...]] = ("N_ot", "p_sel", "p_ext", "p_wri")
_GATED: Final[Mapping[FactorName, Literal["intake", "output"]]] = {
    "N_new": "intake",
    "N_ot": "intake",
    "p_sel": "intake",
    "p_wri": "output",
    "O1_c": "output",
}


@dataclass(frozen=True)
class Gate:
    """Why a cohort's factors are not shown: the worst failing intake (firehose) and output
    (o1) instrument over the cohort's window, None when they are usable."""

    intake: Status | None = None
    output: Status | None = None

    def of(self, name: FactorName) -> Status | None:
        which = _GATED.get(name)
        return None if which is None else (self.intake if which == "intake" else self.output)


@dataclass(frozen=True)
class Group:
    kind: GroupKind
    lines: tuple[str, ...]
    old: Funnel
    new: Funnel


@dataclass(frozen=True)
class Row:
    """One factor of the breakdown between the two cohorts."""

    part: Part
    name: FactorName
    old: Measure
    new: Measure
    hidden: Status | None
    """The status word shown in place of the values (a failing instrument), or None."""

    @property
    def shift(self) -> tuple[float, float] | None:
        return None if self.hidden is not None else shift(self.old, self.new)

    @property
    def beyond_noise(self) -> bool:
        moved = self.shift
        return moved is not None and abs(moved[0]) > NOISE_SE * moved[1]


@dataclass(frozen=True)
class Slots:
    line: str
    free: int
    capacity: int

    @property
    def slot_bound(self) -> bool:
        return self.capacity > 0 and self.free / self.capacity <= SLOT_BOUND_FREE


@dataclass(frozen=True)
class QuestionState:
    line: str
    slug: str
    moved: bool
    screened: int = 0
    kept: int = 0
    claimed: int = 0
    cited: int = 0

    @property
    def stopped(self) -> Stage | None:
        """The first stage at 0 for a question that did not move; `delivered` when every
        stage has a source and the prose cited only papers delivered before."""
        if self.moved:
            return None
        counts: tuple[tuple[Stage, int], ...] = (
            ("screening", self.screened),
            ("keep", self.kept),
            ("claim", self.claimed),
            ("cite", self.cited),
        )
        for stage, n in counts:
            if n == 0:
                return stage
        return "delivered"


@dataclass(frozen=True)
class Repeats:
    slots: tuple[int, int]
    """(slots of the week's notes taken by a paper posted on an earlier day, all slots)."""
    review: tuple[int, int] | None
    """(Review entries shown on an earlier note, all entries); None = no RunRecord of the
    week holds a Review."""
    keyword: tuple[int, int]
    """(keyword fetch results no fetch returned on an earlier day, all results)."""


@dataclass(frozen=True)
class Delivery:
    runs: Mapping[str, int]
    """Line slug → its line-runs in the week."""
    reports: int
    records: int
    """Line-runs with a Report / known from a RunRecord."""
    reasons: tuple[tuple[str, int], ...]
    """DEGRADED reasons of the week's RunRecords, most frequent first."""
    answers: int
    """Jev answers stored in the week (Σ len(Judgment.answers) by judged_at)."""
    writer_calls: int | None
    tokens_in: int | None
    tokens_out: int | None
    """Sums over the week's Reports; None when one of them predates the meter."""


@dataclass(frozen=True)
class AuthorSignal:
    ticks: int
    """New question-day ticks: Labels on a QuestionLog first harvested in the week."""
    opened: int
    """jrp notes first seen opened in the week (metrics/opened.jsonl)."""
    positives: int
    """The recommendation net's positives: papers of correct Labels on a source or claim."""
    added: int
    """Of the positives, first harvested in the last 14 days."""
    unknown: int
    """Of the positives, with no recorded first harvest (Labels from before the field)."""


@dataclass(frozen=True)
class WeeklyReview:
    week: Week
    lines: tuple[str, ...]
    o1: tuple[O1Week, ...]
    """WEEKS_SHOWN weeks, oldest first, the review's week last."""
    o2: O2
    cohorts: tuple[Week, Week]
    """(older, newer): the two latest mature cohorts."""
    gates: tuple[Gate, Gate]
    groups: tuple[Group, ...]
    slots: tuple[Slots, ...]
    questions: tuple[QuestionState, ...]
    unset: tuple[str, ...]
    """Lines without an open question."""
    repeats: Repeats
    delivery: Delivery
    instruments: tuple[InstrumentStatus, ...]
    author: AuthorSignal
    status: Mapping[str, Status]
    """Instrument id → its status over the week (the instruments, by id)."""
    monitor: MonitorResult | None = None
    """The monitoring judge's answers (pipeline.monitor). weekly_review is pure and leaves it
    None, and the note then has no monitor lines; write_weekly_review always sets it."""

    def rows(self, group: Group) -> tuple[Row, ...]:
        old_gate, new_gate = self.gates
        return tuple(
            Row(
                part=part,
                name=name,
                old=group.old.measure(name),
                new=group.new.measure(name),
                hidden=old_gate.of(name) or new_gate.of(name),
            )
            for part, name in FACTORS
        )

    def worst(self) -> Row | None:
        """The identity factor of all lines that fell most, beyond noise; None if none."""
        rows = [r for r in self.rows(self.groups[0]) if r.name in IDENTITY and r.beyond_noise]
        fallen = [(moved[0], r) for r in rows if (moved := r.shift) is not None and moved[0] < 0]
        return min(fallen, key=lambda pair: pair[0])[1] if fallen else None

    def zero_lines(self) -> tuple[str, ...]:
        """Lines that ran in the week and first-cited no paper."""
        last = self.o1[-1]
        return tuple(
            slug
            for slug in self.lines
            if self.delivery.runs.get(slug, 0) and last.lines.get(slug, (0, "live"))[0] == 0
        )

    def failing(self) -> tuple[InstrumentStatus, ...]:
        return tuple(i for i in self.instruments if i.status in FAILURES)

    def stuck(self) -> tuple[QuestionState, ...]:
        return tuple(q for q in self.questions if not q.moved)

    def exceptions(self) -> int:
        return len(self.failing()) + len(self.stuck()) + len(self.zero_lines())


# ---------------------------------------------------------------------------- computing

type _Firsts = Mapping[str, tuple[date, Sequence[_Cite]]]
"""Paper key → its first citation day, and that day's citations."""


def _first_cites(lines: Iterable[_Line]) -> dict[str, tuple[date, list[_Cite]]]:
    out: dict[str, tuple[date, list[_Cite]]] = {}
    for line in lines:
        for cite in line.cites:
            day, firsts = out.get(cite.key, (date.max, []))
            if cite.day < day:
                out[cite.key] = (cite.day, [cite])
            elif cite.day == day:
                firsts.append(cite)
    return out


def _o1(week: Week, firsts: _Firsts, slugs: Sequence[str], registry: _Registry) -> O1Week:
    days = [{c.line for c in cs} for day, cs in firsts.values() if week.holds(day)]
    return O1Week(
        week=week,
        total=len(days),
        interval=poisson_interval(len(days)),
        status=registry.of("o1", week.start, week.end),
        lines={
            slug: (
                sum(1 for lines in days if slug in lines),
                registry.of("o1", week.start, week.end, slug),
            )
            for slug in slugs
        },
    )


def _o2(snapshot: Snapshot, firsts: _Firsts, as_of: date) -> O2:
    since = as_of - timedelta(days=O2_DAYS)
    fresh = [
        s
        for s in _of(snapshot.pipeline, Sighting)
        if since < s.first_seen <= as_of
        and not s.baseline
        and not s.unsure
        and s.key.startswith(PAPER_PREFIXES[:3])
    ]
    hits = sum(1 for s in fresh if s.key in firsts and firsts[s.key][0] < s.first_seen)
    return O2(k=hits, n=len(fresh))


def _earliest[K](pairs: Iterable[tuple[K, date]]) -> dict[K, date]:
    out: dict[K, date] = {}
    for key, day in pairs:
        if day < out.get(key, date.max):
            out[key] = day
    return out


def _funnel(lines: Sequence[_Line], cohort: Week) -> Funnel:
    """The cohort's pairs (line, paper) through the stages, each within COHORT_DAYS of the
    pair's first fetch and among the pairs of the stage before."""
    counts = [0, 0, 0, 0, 0]
    for line in lines:
        posted = _earliest((p.key, p.day) for p in line.posts)
        cited = _earliest((c.key, c.day) for c in line.cites)
        for key, first in line.units().items():
            if not cohort.holds(first):
                continue
            until = first + timedelta(days=COHORT_DAYS)
            reached = (
                line.on_topic_day(key),
                line.kept_day(key),
                posted.get(key, date.max),
                cited.get(key, date.max),
            )
            counts[0] += 1
            for i, day in enumerate(reached, start=1):
                if day > until:
                    break
                counts[i] += 1
    return Funnel(*counts)


def _asked(snapshot: Snapshot) -> dict[str, int]:
    """Report @id → how many open questions the run that wrote it asked (its LineRecord;
    the latest RunRecord wins, as the Report is the latest run's)."""
    out: dict[str, int] = {}
    for record in sorted(_of(snapshot.pipeline, RunRecord), key=lambda r: r.started_at):
        for line_record in record.line_records:
            out[line_record.report] = len(line_record.questions)
    return out


def _slots(line: _Line, week: Week, asked: Mapping[str, int], open_now: int) -> Slots:
    """The week's notes' slots: claims_per_question(k) x k each, at the run's k open
    questions (questions/ today for a Report no RunRecord names)."""
    free = capacity = 0
    for report in line.reports:
        if week.holds(report.run_date):
            k = asked.get(report.id, open_now)
            cap = claims_per_question(k) * k
            free += max(cap - len(report.claims), 0)
            capacity += cap
    return Slots(line=line.slug, free=free, capacity=capacity)


def _moved(line: _Line, question: Question, window: tuple[date, date], firsts: _Firsts) -> bool:
    start, end = window
    return any(
        start <= day <= end and any((c.line, c.question) == (line.slug, question.id) for c in cs)
        for day, cs in firsts.values()
    )


def _question(
    line: _Line, question: Question, window: tuple[date, date], firsts: _Firsts
) -> QuestionState:
    if _moved(line, question, window, firsts):
        return QuestionState(line=line.slug, slug=question.slug, moved=True)
    start, end = window
    screened: set[str] = set()
    kept: set[str] = set()
    for j in line.judgments:
        if j.function != _SCREENING or j.subjects[1:] != (question.id,):
            continue
        if not start <= j.judged_at.date() <= end or (route := line.route(j)) is None:
            continue
        screened.add(j.subjects[0])
        if route == "keep":
            kept.add(j.subjects[0])
    mine = question.id
    return QuestionState(
        line=line.slug,
        slug=question.slug,
        moved=False,
        screened=len(screened),
        kept=len(kept),
        claimed=len({p.source for p in line.posts if p.question == mine and start <= p.day <= end}),
        cited=len({c.source for c in line.cites if c.question == mine and start <= c.day <= end}),
    )


def _slot_repeats(lines: Iterable[_Line], week: Week) -> tuple[tuple[int, int], dict[str, date]]:
    """((slots taken by a paper posted earlier, slots), paper → first day it was posted)."""
    slots: list[tuple[date, str]] = []
    for line in lines:
        for report in line.reports:
            for claim in report.claims:
                if (sid := line.claim_source.get(claim)) is not None:
                    slots.append((report.run_date, line.keys[sid]))
    posted = _earliest((key, day) for day, key in slots)
    week_slots = [(day, key) for day, key in slots if week.holds(day)]
    return (sum(1 for day, key in week_slots if posted[key] < day), len(week_slots)), posted


def _review_repeats(
    lines: Mapping[str, _Line], snapshot: Snapshot, week: Week, posted: Mapping[str, date]
) -> tuple[int, int] | None:
    """(Review entries of the week whose paper an earlier note showed, in its Review or its
    claims; all entries), or None when no RunRecord of the week holds a Review."""
    shown: list[tuple[date, str]] = []
    for record in _of(snapshot.pipeline, RunRecord):
        for line_record in record.line_records if record.run_date <= week.end else ():
            line = lines.get(line_record.slug)
            known = line.keys if line is not None else {}
            shown += [(record.run_date, known[sid]) for sid in line_record.review if sid in known]
    first = _earliest((key, day) for day, key in shown)
    entries = [(day, key) for day, key in shown if week.holds(day)]
    if not entries:
        return None
    before = sum(1 for day, key in entries if min(first[key], posted.get(key, day)) < day)
    return before, len(entries)


def _keyword_new(lines: Iterable[_Line], week: Week) -> tuple[int, int]:
    """(keyword fetch results of the week that no fetch returned on an earlier day, all
    results); one result per (line, day, source)."""
    results = {
        (line.slug, day, sid): line.first_fetch[sid] == day
        for line in lines
        for record in line.keyword
        if week.holds(day := record.completed_at.date())
        for sid in record.outputs
        if sid in line.first_fetch
    }
    return sum(results.values()), len(results)


def _sum(values: Sequence[int | None]) -> int | None:
    return None if any(v is None for v in values) else sum(v or 0 for v in values)


def _delivery(lines: Iterable[_Line], snapshot: Snapshot, week: Week) -> Delivery:
    indexed = list(lines)
    runs = [r for r in line_runs(snapshot) if week.holds(r.run_date)]
    reasons = Counter(
        printable(reason)
        for record in _of(snapshot.pipeline, RunRecord)
        if week.holds(record.run_date)
        for reason in record.reasons
    )
    reports = [r for line in indexed for r in line.reports if week.holds(r.run_date)]
    return Delivery(
        runs=dict(Counter(r.slug for r in runs)),
        reports=sum(1 for r in runs if r.report is not None),
        records=sum(1 for r in runs if r.started_at is not None),
        reasons=tuple(sorted(reasons.items(), key=lambda pair: (-pair[1], pair[0]))),
        answers=sum(
            len(j.answers)
            for line in indexed
            for j in line.judgments
            if week.holds(j.judged_at.date())
        ),
        writer_calls=_sum([r.operations.writer_calls for r in reports]),
        tokens_in=_sum([r.operations.jev_input_tokens for r in reports]),
        tokens_out=_sum([r.operations.jev_output_tokens for r in reports]),
    )


def _positive(line: _Line, label: Label) -> str | None:
    """The paper a correct Label on a source or a claim feeds the recommendation net
    (run.LineRun._positives_and_negatives), or None."""
    if label.verdict != "correct":
        return None
    sid = label.subject if label.subject in line.sources else line.claim_source.get(label.subject)
    return paper_id(line.sources[sid].url) if sid is not None else None


def _author(lines: Iterable[_Line], snapshot: Snapshot, week: Week) -> AuthorSignal:
    ticks = 0
    firsts: dict[tuple[str, str], date | None] = {}
    for line in lines:
        for label in line.labels:
            first = label.first_harvested_at.date() if label.first_harvested_at else None
            if first is not None and first > week.end:
                continue  # not ticked yet as of the week's end
            question_day = label.provenance == "question_day"
            if first is not None and week.holds(first) and question_day:
                ticks += kind_of(label.subject) == "question_log"
            if (paper := _positive(line, label)) is not None:
                known = firsts.get((line.slug, paper), date.max)
                firsts[(line.slug, paper)] = (
                    None if known is None or first is None else min(known, first)
                )
    recent = week.end - timedelta(days=QUESTION_DAYS)
    return AuthorSignal(
        ticks=ticks,
        opened=sum(1 for day in snapshot.opened.values() if week.holds(day)),
        positives=len(firsts),
        added=sum(1 for day in firsts.values() if day is not None and day > recent),
        unknown=sum(1 for day in firsts.values() if day is None),
    )


def _groups(
    indexed: Sequence[_Line], cohorts: tuple[Week, Week], slots: Sequence[Slots]
) -> tuple[Group, ...]:
    """All lines, the slot-bound lines and the supply-bound lines (by the review week's
    free slots; a line with no note that week is in neither)."""
    bound = {s.line for s in slots if s.slot_bound}
    supplied = {s.line for s in slots if s.capacity and not s.slot_bound}
    members: tuple[tuple[GroupKind, Callable[[str], bool]], ...] = (
        ("all", lambda _: True),
        ("slot", lambda slug: slug in bound),
        ("supply", lambda slug: slug in supplied),
    )
    out: list[Group] = []
    for kind, member in members:
        chosen = [line for line in indexed if member(line.slug)]
        out.append(
            Group(
                kind=kind,
                lines=tuple(line.slug for line in chosen),
                old=_funnel(chosen, cohorts[0]),
                new=_funnel(chosen, cohorts[1]),
            )
        )
    return tuple(out)


def _gate(registry: _Registry, cohort: Week) -> Gate:
    end = cohort.end + timedelta(days=COHORT_DAYS)
    return Gate(
        intake=registry.failing(INTAKE, cohort.start, end),
        output=registry.failing(OUTPUT, cohort.start, end),
    )


def _index(inputs: Inputs, as_of: date) -> list[_Line]:
    """Every configured line's partition as of a day, in config order."""
    return [_Line(s.slug, inputs.snapshot.lines.get(s.slug, {}), as_of) for s in inputs.lines]


def weekly_review(inputs: Inputs, week: Week) -> WeeklyReview:
    """Every number of one week's review, as of the week's last day (module docstring)."""
    return _review(inputs, week, _index(inputs, week.end))


def _review(inputs: Inputs, week: Week, indexed: Sequence[_Line]) -> WeeklyReview:
    as_of = week.end
    snapshot = inputs.snapshot
    registry = _Registry(snapshot)
    slugs = tuple(spec.slug for spec in inputs.lines)
    lines = {line.slug: line for line in indexed}
    firsts = _first_cites(indexed)
    older, newer = week.shifted(-2), week.shifted(-1)
    asked = _asked(snapshot)
    open_now = {spec.slug: len(spec.questions or ()) for spec in inputs.lines}
    slots = [_slots(line, week, asked, open_now[line.slug]) for line in indexed]
    window = (as_of - timedelta(days=QUESTION_DAYS - 1), as_of)
    instruments = tuple(registry.full(i.id, week.start, week.end) for i in REGISTRY)
    slot_repeats, posted = _slot_repeats(indexed, week)
    first_week = week.shifted(1 - WEEKS_SHOWN)
    return WeeklyReview(
        week=week,
        lines=slugs,
        o1=tuple(_o1(first_week.shifted(i), firsts, slugs, registry) for i in range(WEEKS_SHOWN)),
        o2=_o2(snapshot, firsts, as_of),
        cohorts=(older, newer),
        gates=(_gate(registry, older), _gate(registry, newer)),
        groups=_groups(indexed, (older, newer), slots),
        slots=tuple(s for s in slots if s.capacity),
        questions=tuple(
            _question(lines[spec.slug], q, window, firsts)
            for spec in inputs.lines
            for q in spec.questions or ()
        ),
        unset=tuple(spec.slug for spec in inputs.lines if spec.questions is None),
        repeats=Repeats(
            slots=slot_repeats,
            review=_review_repeats(lines, snapshot, week, posted),
            keyword=_keyword_new(indexed, week),
        ),
        delivery=_delivery(indexed, snapshot, week),
        instruments=instruments,
        author=_author(indexed, snapshot, week),
        status={i.id: i.status for i in instruments},
    )


# ---------------------------------------------------------------------- the monitor sample


def _question_of(spec: LineSpec, nodes: Mapping[str, GraphNodeType], ident: str) -> Question | None:
    """The question a section or a citation was asked under: the stored node (its evidence
    is what the writer was told was known), else the open question of questions/."""
    node = nodes.get(ident)
    if isinstance(node, Question):
        return node
    return next((q for q in spec.questions or () if q.id == ident), None)


def _sections(inputs: Inputs, week: Week) -> list[monitor.Section]:
    """Every section of the week with prose whose question and claims are stored."""
    out: list[monitor.Section] = []
    for spec in inputs.lines:
        nodes = inputs.snapshot.lines.get(spec.slug, {})
        reports = _of(nodes, Report)
        name = spec.name or spec.slug
        for log in _of(nodes, QuestionLog):
            question = _question_of(spec, nodes, log.question)
            if not log.text or not week.holds(log.run_date) or question is None:
                continue
            case = case_of(
                spec.slug,
                log,
                question,
                nodes,
                reports=reports,
                line_name=name,
                vocabulary=spec.vocabulary or (name,),
            )
            if case is not None:
                out.append(monitor.Section(log.id, spec.slug, question.slug, case))
    return out


def _papers(inputs: Inputs, week: Week, indexed: Sequence[_Line]) -> list[monitor.Paper]:
    """Every O1 paper of the week, with the claim of its first-day [n] (the first by line,
    question and claim when several cited it that day)."""
    specs = {spec.slug: spec for spec in inputs.lines}
    lines = {line.slug: line for line in indexed}
    out: list[monitor.Paper] = []
    for key, (day, cites) in _first_cites(indexed).items():
        if not week.holds(day):
            continue
        cite = min(cites, key=lambda c: (c.line, c.question, c.claim))
        nodes = inputs.snapshot.lines.get(cite.line, {})
        question = _question_of(specs[cite.line], nodes, cite.question)
        claim = nodes.get(cite.claim)
        if question is None or not isinstance(claim, Claim):
            continue
        title = lines[cite.line].sources[cite.source].title
        out.append(monitor.Paper(key, cite.line, question, claim.text, title))
    return out


def monitor_sample(inputs: Inputs, week: Week, lang: Lang) -> monitor.Sample:
    """The monitoring judge's seeded sample of the week (module docstring, pipeline.monitor):
    nothing is called here."""
    return _monitor_sample(inputs, week, lang, _index(inputs, week.end))


def _monitor_sample(
    inputs: Inputs, week: Week, lang: Lang, indexed: Sequence[_Line]
) -> monitor.Sample:
    return monitor.draw(week.label, lang, _sections(inputs, week), _papers(inputs, week, indexed))


# ---------------------------------------------------------------------------- rendering

PART_WORDS: Final[Mapping[Part, Msg]] = {
    "M": t.PART_M,
    "Q": t.PART_Q,
    "I": t.PART_I,
    "S": t.PART_S,
    "X": t.PART_X,
    "W": t.PART_W,
    "D": t.PART_D,
    "OUT": t.PART_OUT,
}
FACTOR_WORDS: Final[Mapping[FactorName, Msg]] = {
    "N_new": t.FACTOR_N_NEW,
    "N_ot": t.FACTOR_N_OT,
    "p_sel": t.FACTOR_P_SEL,
    "p_ext": t.FACTOR_P_EXT,
    "p_wri": t.FACTOR_P_WRI,
    "O1_c": t.FACTOR_O1_C,
}
STAGE_WORDS: Final[Mapping[Stage, Msg]] = {
    "screening": t.STAGE_SCREENING,
    "keep": t.STAGE_KEEP,
    "claim": t.STAGE_CLAIM,
    "cite": t.STAGE_CITE,
    "delivered": t.STAGE_DELIVERED,
}
DASH: Final = "—"


def _shown(text: str, status: Status, lang: Lang) -> str:
    """The number, or the status word when its instrument is not usable."""
    return text if status in USABLE else STATUS_WORDS[status](lang)


def _signed(x: float) -> str:
    return f"{x:+.2f}"


def _share(pair: tuple[int, int]) -> str:
    k, n = pair
    return f"{k}/{n} ({k / n:.0%})" if n else f"{k}/{n}"


def _measure(m: Measure) -> str:
    if m.n is None:
        return str(m.k)
    value = m.value
    return f"{value:.2f} ({m.k}/{m.n})" if value is not None else f"{DASH} (0/0)"


def _where(instrument: InstrumentStatus, lang: Lang) -> str:
    """The first cell that gave the instrument its status: line and day, and the broken
    invariant if one is named."""
    cell = next((c for c in instrument.cells if c.status == instrument.status), None)
    if cell is None:
        return ""
    obs = cell.observation
    where = f"{obs.line or t.WBR_TICK(lang)} {obs.run_date.isoformat()}"
    return f"{where}: {printable(obs.conflict)}" if obs.conflict else where


def _counts(review: WeeklyReview, lang: Lang) -> str:
    counts: Counter[Status] = Counter(i.status for i in review.instruments)
    return " · ".join(f"{word(lang)} {counts[s]}" for s, word in STATUS_WORDS.items() if counts[s])


def _conclusion(review: WeeklyReview, lang: Lang) -> list[str]:
    worst = review.worst()
    if worst is not None and (moved := worst.shift) is not None:
        head = t.WBR_WORST(
            lang,
            part=PART_WORDS[worst.part](lang),
            factor=worst.name,
            delta=_signed(moved[0]),
            se=f"{moved[1]:.2f}",
        )
    elif any(r.shift is not None for r in review.rows(review.groups[0]) if r.name in IDENTITY):
        head = t.WBR_NO_WORST(lang)
    else:
        head = t.WBR_NO_BREAKDOWN(lang)
    return [
        f"## {t.WBR_CONCLUSION(lang)}",
        "",
        f"- {head}",
        f"- {t.WBR_EXCEPTION_COUNT(lang, n=review.exceptions())}",
        f"- {t.WBR_INSTRUMENT_SUMMARY(lang, counts=_counts(review, lang))}",
        f"- {t.WBR_V0(lang)}",
    ]


def _o2_text(o2: O2, lang: Lang) -> str:
    if o2.n == 0:
        return t.WBR_MEASURING(lang)
    if o2.n < O2_MIN_N:
        return t.WBR_O2_KN(lang, k=o2.k, n=o2.n)
    low, high = wilson(o2.k, o2.n)
    return t.WBR_O2_RATE(
        lang, rate=f"{o2.k / o2.n:.2f}", low=f"{low:.2f}", high=f"{high:.2f}", k=o2.k, n=o2.n
    )


def _output(review: WeeklyReview, lang: Lang) -> list[str]:
    weeks = review.o1
    out = [
        f"## {t.WBR_OUTPUT(lang)}",
        "",
        "| | " + " | ".join(w.week.short for w in weeks) + " |",
        "|---|" + "---|" * len(weeks),
    ]
    totals = [
        _shown(f"{w.total} ({w.interval[0]:.1f}-{w.interval[1]:.1f})", w.status, lang)
        for w in weeks
    ]
    out.append(f"| {t.WBR_O1_ROW(lang)} | " + " | ".join(totals) + " |")
    for slug in review.lines:
        cells = [_shown(str(w.lines[slug][0]), w.lines[slug][1], lang) for w in weeks]
        out.append(f"| └ {slug} | " + " | ".join(cells) + " |")
    out += [
        "",
        f"- {t.WBR_O2(lang, value=_o2_text(review.o2, lang))}",
        *_monitor_lines(review.monitor, lang),
        f"- {t.WBR_O1_NOTE(lang)}",
    ]
    return out


def _tally_text(tally: Tally, head: Msg, lang: Lang) -> str:
    """`head` k/n of what was judged, then how many are unmeasured and why; the reason
    alone when nothing was judged; 対象なし for an empty sample nothing stopped."""
    why = STOP_WORDS[tally.stop or "error"](lang)
    if not tally.judged:
        if tally.asked or tally.stop is not None:
            return t.WBR_UNMEASURED(lang, why=why)
        return t.WBR_NO_TARGET(lang)
    parts = [head(lang, k=tally.passed, n=tally.judged)]
    if tally.unmeasured:
        parts.append(t.WBR_UNMEASURED_REST(lang, m=tally.unmeasured, why=why))
    if tally.failed:
        parts.append(t.WBR_FAILED_SECTIONS(lang, sections=", ".join(tally.failed)))
    return " · ".join(parts)


def _monitor_lines(result: MonitorResult | None, lang: Lang) -> list[str]:
    """Section 1's monitor lines (pipeline.monitor); none for a review computed without it."""
    if result is None:
        return []
    out = [
        "- "
        + t.WBR_PRECISION(
            lang, n=PRECISION_N, value=_tally_text(result.precision, t.WBR_ADVANCED, lang)
        ),
        "- "
        + t.WBR_FIDELITY(
            lang, n=FIDELITY_N, value=_tally_text(result.fidelity, t.WBR_PASSED, lang)
        ),
    ]
    if result.week_usd:
        cap = DASH if result.budget is None else f"{result.budget:.2f}"
        out.append(
            "- "
            + t.WBR_MONITOR_COST(
                lang,
                model=monitor.MODEL.name,
                usd=f"{result.usd:.2f}",
                week=f"{result.week_usd:.2f}",
                cap=cap,
            )
        )
    return out


def _exceptions(review: WeeklyReview, lang: Lang) -> list[str]:
    items = [
        t.WBR_EX_INSTRUMENT(
            lang, id=i.id, status=STATUS_WORDS[i.status](lang), where=_where(i, lang)
        )
        for i in review.failing()
    ]
    items += [
        t.WBR_EX_QUESTION(
            lang, line=q.line, question=q.slug, stage=STAGE_WORDS[q.stopped or "delivered"](lang)
        )
        for q in review.stuck()
    ]
    items += [
        t.WBR_EX_LINE(lang, line=slug, runs=review.delivery.runs[slug])
        for slug in review.zero_lines()
    ]
    return [f"## {t.WBR_EXCEPTIONS(lang)}", "", *(f"- {i}" for i in items or [t.NONE_WORD(lang)])]


def _table(review: WeeklyReview, group: Group, lang: Lang) -> list[str]:
    old, new = review.cohorts
    out = [
        t.WBR_HEAD_BREAKDOWN(lang, old=old.short, new=new.short),
        "|---|---|---|---|---|---|",
    ]
    for row in review.rows(group):
        if row.hidden is not None:
            word = STATUS_WORDS[row.hidden](lang)
            cells = [word, word, DASH, DASH]
        elif (moved := row.shift) is None:
            cells = [_measure(row.old), _measure(row.new), DASH, DASH]
        else:
            delta = _signed(moved[0])
            cells = [
                _measure(row.old),
                _measure(row.new),
                f"**{delta}**" if row.beyond_noise else delta,
                f"{moved[1]:.2f}",
            ]
        part = "" if row.name == "N_new" else PART_WORDS[row.part](lang)
        out.append(f"| {part} | {FACTOR_WORDS[row.name](lang)} | " + " | ".join(cells) + " |")
    return out


def _breakdown(review: WeeklyReview, lang: Lang) -> list[str]:
    old, new = review.cohorts
    out = [f"## {t.WBR_BREAKDOWN(lang, old=old.short, new=new.short)}"]
    for group in review.groups:
        listed = ", ".join(group.lines) or t.NONE_WORD(lang)
        match group.kind:
            case "all":
                title = t.WBR_GROUP_ALL(lang)
            case "slot":
                title = t.WBR_GROUP_SLOT(lang, lines=listed)
            case "supply":
                title = t.WBR_GROUP_SUPPLY(lang, lines=listed)
        out += ["", f"**{title}**", ""]
        out += _table(review, group, lang) if group.lines else [f"- {t.WBR_GROUP_EMPTY(lang)}"]
    slots = " · ".join(f"{s.line} {s.free}/{s.capacity}" for s in review.slots)
    out += [
        "",
        f"- {t.WBR_SLOTS(lang, week=review.week.short, slots=slots or t.NONE_WORD(lang))}",
        f"- {t.WBR_SE_NOTE(lang)}",
        f"- {t.WBR_COHORT_NOTE(lang)}",
    ]
    return out


def _questions(review: WeeklyReview, lang: Lang) -> list[str]:
    moved = sum(1 for q in review.questions if q.moved)
    out = [f"## {t.WBR_QUESTIONS(lang, k=moved, n=len(review.questions))}", ""]
    stuck = review.stuck()
    if stuck:
        out += [t.WBR_HEAD_QUESTIONS(lang), "|---|---|---|---|"]
        for q in stuck:
            chain = f"{q.screened} → {q.kept} → {q.claimed} → {q.cited}"
            stage = STAGE_WORDS[q.stopped or "delivered"](lang)
            out.append(f"| {q.line} | {q.slug} | {stage} | {chain} |")
    else:
        out.append(f"- {t.WBR_ALL_MOVING(lang)}")
    if review.unset:
        out += ["", f"- {t.WBR_NO_QUESTIONS(lang, lines=', '.join(review.unset))}"]
    return out


def _repetition(review: WeeklyReview, lang: Lang) -> list[str]:
    repeats = review.repeats
    slots = _shown(_share(repeats.slots), review.status["claims_posted"], lang)
    shown = _share(repeats.review) if repeats.review else t.WBR_REVIEW_UNMEASURED(lang)
    return [
        f"## {t.WBR_REPEATS(lang)}",
        "",
        f"- {t.WBR_REPEAT_SLOTS(lang, value=slots)}",
        f"- {t.WBR_REPEAT_REVIEW(lang, value=shown)}",
        f"- {t.WBR_KEYWORD_NEW(lang, value=_share(repeats.keyword))}",
    ]


def _per_o1(value: int | None, o1: int | None, status: Status, lang: Lang) -> str:
    if status not in USABLE and status != "insufficient-n":
        return STATUS_WORDS[status](lang)
    if value is None:
        return t.WBR_NOT_MEASURED(lang)
    return f"{value / o1:,.1f}" if o1 else DASH


def _resources(review: WeeklyReview, lang: Lang) -> list[str]:
    d = review.delivery
    last = review.o1[-1]
    o1 = last.total if last.status in USABLE else None
    out = [
        f"## {t.WBR_DELIVERY(lang)}",
        "",
        f"- {t.WBR_LINE_RUNS(lang, n=sum(d.runs.values()), reports=d.reports, records=d.records)}",
    ]
    if d.reasons:
        out.append(f"- {t.WBR_DEGRADED(lang)}")
        out += [f"  - {reason} ({n})" for reason, n in d.reasons[:REASONS_SHOWN]]
        if len(d.reasons) > REASONS_SHOWN:
            out.append(f"  - {t.WBR_MORE(lang, n=len(d.reasons) - REASONS_SHOWN)}")
    tokens = review.status["jev_tokens"]
    out.append(
        "- "
        + t.WBR_PER_O1(
            lang,
            answers=_per_o1(d.answers, o1, "live", lang),
            writer=_per_o1(d.writer_calls, o1, review.status["writer_calls"], lang),
            tokens_in=_per_o1(d.tokens_in, o1, tokens, lang),
            tokens_out=_per_o1(d.tokens_out, o1, tokens, lang),
        )
    )
    return out


def _why(instrument: InstrumentStatus, lang: Lang) -> str:
    declared = next(i.declared for i in REGISTRY if i.id == instrument.id)
    if instrument.status == "declared-degenerate" and declared is not None:
        return f" — {declared.reason(lang)}"
    if instrument.status in FAILURES and (where := _where(instrument, lang)):
        return f" — {where}"
    return ""


def _positives(author: AuthorSignal, lang: Lang) -> str:
    if author.positives and author.unknown == author.positives:
        return t.WBR_POSITIVES_UNKNOWN(lang, n=author.positives)
    if author.added:
        return t.WBR_POSITIVES_ADDED(lang, n=author.positives, added=author.added)
    return t.WBR_POSITIVES_FROZEN(lang, n=author.positives)


def _instruments(review: WeeklyReview, lang: Lang) -> list[str]:
    out = [f"## {t.WBR_INSTRUMENTS(lang)}", "", f"- {_counts(review, lang)}"]
    out += [
        "- "
        + t.WBR_INSTRUMENT_LINE(
            lang,
            id=i.id,
            part=PART_WORDS[i.part](lang),
            status=STATUS_WORDS[i.status](lang),
            why=_why(i, lang),
        )
        for i in review.instruments
        if i.status != "live"
    ]
    author = review.author
    out.append(
        "- "
        + t.WBR_AUTHOR(
            lang,
            ticks=_shown(str(author.ticks), review.status["label.first_harvest"], lang),
            opened=_shown(str(author.opened), review.status["opened"], lang),
            positives=_positives(author, lang),
        )
    )
    return out


def render(review: WeeklyReview, lang: Lang) -> str:
    """The note: sections 0 to 9 (plan quality-metrics claim 5). Every fixed text is a
    note_text Msg; nothing in it is a source key or a `jrp:` mark."""
    week = review.week
    title = t.WBR_TITLE(
        lang, week=week.label, start=week.start.isoformat(), end=week.end.isoformat()
    )
    sections = [
        _conclusion(review, lang),
        _output(review, lang),
        _exceptions(review, lang),
        _breakdown(review, lang),
        [f"## {t.WBR_FIX(lang)}", "", f"- {t.WBR_NOT_IN_V0(lang)}"],
        _questions(review, lang),
        _repetition(review, lang),
        _resources(review, lang),
        [f"## {t.WBR_LAST(lang)}", "", f"- {t.WBR_NOT_IN_V0(lang)}"],
        _instruments(review, lang),
    ]
    return "\n\n".join([f"# {title}", *("\n".join(s) for s in sections)]) + "\n"


# ----------------------------------------------------------------------- the metrics row


def _funnel_row(funnel: Funnel) -> dict[str, JsonValue]:
    return {
        "new": funnel.new,
        "on_topic": funnel.on_topic,
        "kept": funnel.kept,
        "posted": funnel.posted,
        "cited": funnel.cited,
    }


def _pair(pair: tuple[int, int] | None) -> JsonValue:
    return None if pair is None else [pair[0], pair[1]]


def row(review: WeeklyReview, *, generated_at: AwareDatetime) -> dict[str, JsonValue]:
    """The week's line of metrics/weekly.jsonl: every number of the note, raw. Rerunning a
    week appends another line; a reader takes the latest line of a week."""
    d, author = review.delivery, review.author
    return {
        "week": review.week.label,
        "generated_at": generated_at.isoformat(),
        "o1": [
            {
                "week": w.week.label,
                "count": w.total,
                "low": round(w.interval[0], 3),
                "high": round(w.interval[1], 3),
                "status": w.status,
                "lines": {slug: {"count": n, "status": st} for slug, (n, st) in w.lines.items()},
            }
            for w in review.o1
        ],
        "o2": {"k": review.o2.k, "n": review.o2.n},
        "cohorts": [c.label for c in review.cohorts],
        "gates": [{"intake": g.intake, "output": g.output} for g in review.gates],
        "breakdown": {
            g.kind: {"lines": list(g.lines), "old": _funnel_row(g.old), "new": _funnel_row(g.new)}
            for g in review.groups
        },
        "slots": {s.line: {"free": s.free, "capacity": s.capacity} for s in review.slots},
        "questions": {
            "open": len(review.questions),
            "moved": sum(1 for q in review.questions if q.moved),
            "stopped": [
                {
                    "line": q.line,
                    "question": q.slug,
                    "stage": q.stopped,
                    "chain": [q.screened, q.kept, q.claimed, q.cited],
                }
                for q in review.stuck()
            ],
            "unset": list(review.unset),
        },
        "repeats": {
            "slots": _pair(review.repeats.slots),
            "review": _pair(review.repeats.review),
            "keyword": _pair(review.repeats.keyword),
        },
        "delivery": {
            "runs": dict(d.runs),
            "reports": d.reports,
            "records": d.records,
            "reasons": {reason: n for reason, n in d.reasons},
            "answers": d.answers,
            "writer_calls": d.writer_calls,
            "jev_input_tokens": d.tokens_in,
            "jev_output_tokens": d.tokens_out,
        },
        "instruments": dict(review.status),
        "author": {
            "ticks": author.ticks,
            "opened": author.opened,
            "positives": author.positives,
            "added": author.added,
            "unknown": author.unknown,
        },
        "exceptions": review.exceptions(),
        "monitor": None if review.monitor is None else monitor.as_row(review.monitor),
    }


# ------------------------------------------------------------------------------ writing


@dataclass(frozen=True)
class Written:
    note: Path
    row: dict[str, JsonValue]
    review: WeeklyReview
    """What the note renders, the monitoring judge's answers included."""


async def write_weekly_review(
    env: Mapping[str, str],
    *,
    week: Week,
    out: Path,
    now: AwareDatetime,
    http: httpx2.AsyncClient,
) -> Written:
    """Read the store, run the monitoring judge over the week's sample (pipeline.monitor:
    nothing is called without ANTHROPIC_API_KEY), then write `<out>/<note_name(week)>`
    (replacing a note of the same week) and append the week's row to
    `<store>/metrics/weekly.jsonl`. The judge's calls append to `<store>/metrics/judge.jsonl`
    under its lock file `judge.jsonl.lock`; nothing else is written."""
    lang = note_lang(env)
    inputs = read_inputs(env, now=now)
    indexed = _index(inputs, week.end)
    checked = await monitor.monitor_judge(
        _monitor_sample(inputs, week, lang, indexed),
        env,
        store_dir(env) / monitor.LEDGER_FILE,
        http=http,
        now=now,
        rubric=monitor.read_rubric(lang),
    )
    review = replace(_review(inputs, week, indexed), monitor=checked)
    out.mkdir(parents=True, exist_ok=True)
    note = out / note_name(week)
    note.write_text(render(review, lang), encoding="utf-8")
    line = row(review, generated_at=now)
    append_row(store_dir(env) / WEEKLY_FILE, line)
    return Written(note=note, row=line, review=review)
