"""`jrp eval gate freeze`: the S and X eval set, frozen from a store (research report
2026-10-20-sx-eval-loop).

Reads the store at JRP_STORE_DIR (point it at a copy: the production store is only read, but
the set is written under it, evals.paths), config.toml, questions/ and the git history of
questions/, and writes the set to bench_dir(env, "gate", <name>):

  manifest.json     counts, the rebuild rates, the parities, the strata
  judgments.jsonld  every Judgment an item refers to, as the store holds it (store.graph)
  s_pairs.jsonl     S: one row per (source, question) pair a prefilter Judgment judged
  x_days.jsonl      X: one row per line-day with a claim pool
  states.jsonl      the rebuilt state of each screening Judgment whose sha256 matched
  materials.jsonl   what the silver labeller and the author's check read, per sampled item
  sample.json       the labelled sample, kind → stratum → item ids

S. The pairs a current-version prefilter Judgment judged on or after `since`, whose source
clears the screening floor. A prefilter Judgment's questions are the run's open questions in
order; the order is the RunRecord's (LineRecord.questions, from 2026-10-21) or, before that,
the open questions of the questions/ version whose prefilter state hashes to the stored
state_sha256. A pair takes the first Judgment that judged it, its source's first triage and
trust Judgments, and its current-version screening Judgments within WINDOW_DAYS of its first.

X. A line-day's pool is every claim a novelty Judgment of that day judged (the run asks
novelty on the day it screens; a cached answer from an earlier day leaves no Judgment, so
such a claim is missing from the pool) that no earlier Report showed, with the claim's
claim_detection Judgment. `shown` is the day's QuestionLogs, `seen` the paper keys earlier
QuestionLogs listed.

Splits: an item's cluster is its question-day (S: the pair's question and day; X: the line
and day); a cluster is held out when its sha256, read as a number, is divisible by
HOLDOUT_EVERY (prose_bench.split_of's rule), so an item never moves when the set is refrozen.

Strata (S, from the baseline route and its weighted score): pf-far / pf-near (prefilter on_topic
below 0.3 / at least 0.3), safe (triage or trust rejected the source), unasked, gate (every
screening Judgment fails a gate), low / band-low / band-high / high (weighted below 0.5 /
0.5-0.6 / 0.6-0.7 / 0.7 and above). X, per (claim, question) on its first day: shown (the
baseline shows it), cut (novelty passed, the cap left it out), dup (novelty rejected it).
"""

import hashlib
import json
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import AwareDatetime, JsonValue

from jev_research_pipeline.jev import (
    claim_detection,
    judged_of,
    novelty,
    question_prefilter,
    question_screening,
    relevance_triage,
    source_trust,
)
from jev_research_pipeline.jev.context import LineContext, source_state
from jev_research_pipeline.jev.core import JevState
from jev_research_pipeline.model import (
    Claim,
    Decision,
    GraphNodeType,
    Judgment,
    Label,
    Question,
    QuestionLog,
    Report,
    RunRecord,
    SourceItem,
    Unit,
)
from jev_research_pipeline.pipeline.config import env_tracks, line_context
from jev_research_pipeline.pipeline.registry import read_snapshot
from jev_research_pipeline.pipeline.runner import claims_before, store_dir
from jev_research_pipeline.pipeline.wbr import paper_key
from jev_research_pipeline.questions import parse_questions, questions_path
from jev_research_pipeline.store import GraphStore, input_sha256
from jev_research_pipeline.store.graph import Partition

from .gate_policy import (
    BASELINE,
    WINDOW_DAYS,
    Frozen,
    Judged_,
    SPair,
    Split,
    XDay,
    XEntry,
    s_outcome,
    weighted_best,
    x_pool,
    x_shown,
)
from .paths import bench_dir
from .sampling import draw

KIND: Final = "gate"
SINCE: Final = date(2026, 10, 2)
"""question_screening v3's first run: the screen every S item is recomputed under."""
HOLDOUT_EVERY: Final = 3
S_SIZES: Final[Mapping[str, int]] = {
    "pf-far": 10,
    "pf-near": 20,
    "safe": 15,
    "unasked": 5,
    "gate": 15,
    "low": 25,
    "band-low": 30,
    "band-high": 30,
    "high": 10,
}
"""Labels per S stratum (160): most of them near the keep cut, where candidates disagree, and
a quarter in what the baseline drops, so a recall has a denominator (research report: Webber
puts most labels on the unretrieved side for a recall interval)."""
X_SIZES: Final[Mapping[str, int]] = {"shown": 30, "cut": 40, "dup": 10}
"""Labels per X stratum (80): a slot order moves claims between shown and cut."""
PF_NEAR: Final = 0.3

type Kind = Literal["s", "x"]


class QuestionText(Frozen):
    title: str
    brief: str = ""
    method: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    not_: tuple[str, ...] = ()

    @classmethod
    def of(cls, q: Question) -> "QuestionText":
        return cls(
            title=q.title,
            brief=q.brief,
            method=q.method_constraints,
            evidence=q.evidence_constraints,
            not_=q.negative_topics,
        )


class Material(Frozen):
    """What a labeller reads for one sampled item: the question, and the source (S) or the
    claim with its paper's title (X). Third-party text: it stays in the private eval set."""

    kind: Kind
    item: str
    line: str
    stratum: str
    question: QuestionText
    title: str
    url: str = ""
    adapter: str = ""
    excerpt: str = ""
    claim: str = ""
    key: str = ""


class Manifest(Frozen):
    name: str
    created_at: AwareDatetime
    store: str
    since: date
    lines: tuple[str, ...]
    counts: Mapping[str, int]
    rebuild: Mapping[str, Mapping[str, tuple[int, int]]]
    """Line → function → (rebuilt, tried): prefilter question order, screening state."""
    parity: Mapping[str, tuple[int, int]]
    """screening: stored Decisions the rule reproduces; x_sections: QuestionLogs the
    baseline slot replay reproduces exactly."""
    strata: Mapping[str, Mapping[str, int]]
    sizes: Mapping[str, Mapping[str, int]]


def split_of(cluster: str) -> Split:
    return (
        "holdout"
        if int(hashlib.sha256(cluster.encode()).hexdigest(), 16) % HOLDOUT_EVERY == 0
        else "dev"
    )


def _of[N](nodes: Mapping[str, GraphNodeType], kind: type[N]) -> list[N]:
    return [n for n in nodes.values() if isinstance(n, kind)]


def _git(cwd: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(  # fixed git subcommands, no shell
            ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def question_versions(path: Path, *, line: str) -> list[list[Question]]:
    """Every version of a line's questions file, newest first: the file as it is, then each
    committed version (git log of the file). Outside a git checkout, the file alone."""
    now = datetime.now(UTC)
    texts = [path.read_text(encoding="utf-8")] if path.is_file() else []
    top = _git(path.parent, "rev-parse", "--show-toplevel")
    if top:
        rel = path.resolve().relative_to(Path(top.strip()).resolve()).as_posix()
        for sha in (_git(Path(top.strip()), "log", "--format=%H", "--", rel) or "").split():
            text = _git(Path(top.strip()), "show", f"{sha}:{rel}")
            if text is not None:
                texts.append(text)
    return [parse_questions(text, line=line, opened_at=now) for text in texts]


@dataclass
class _Out:
    pairs: list[SPair] = field(default_factory=list[SPair])
    days: list[XDay] = field(default_factory=list[XDay])
    judgments: dict[str, Judgment] = field(default_factory=dict[str, Judgment])
    states: list[dict[str, JsonValue]] = field(default_factory=list[dict[str, JsonValue]])
    rebuild: dict[str, dict[str, tuple[int, int]]] = field(
        default_factory=dict[str, dict[str, tuple[int, int]]]
    )
    parity: dict[str, tuple[int, int]] = field(default_factory=dict[str, tuple[int, int]])
    questions: dict[str, Question] = field(default_factory=dict[str, Question])
    sources: dict[str, SourceItem] = field(default_factory=dict[str, SourceItem])
    claims: dict[str, str] = field(default_factory=dict[str, str])

    def tally(self, name: str, hit: int, tried: int) -> None:
        k, n = self.parity.get(name, (0, 0))
        self.parity[name] = (k + hit, n + tried)


class _Line:
    """One line's partition, indexed for the freeze."""

    def __init__(
        self,
        slug: str,
        nodes: Mapping[str, GraphNodeType],
        ctx: LineContext,
        versions: Sequence[Sequence[Question]],
        records: Sequence[RunRecord],
    ) -> None:
        self.slug, self.nodes, self.ctx = slug, nodes, ctx
        self.sources = {s.id: s for s in _of(nodes, SourceItem)}
        self.claims = {c.id: c for c in _of(nodes, Claim)}
        self.units = {u.id: u for u in _of(nodes, Unit)}
        self.reports = sorted(_of(nodes, Report), key=lambda r: r.run_date)
        self.logs = _of(nodes, QuestionLog)
        self.judgments = sorted(_of(nodes, Judgment), key=lambda j: (j.judged_at, j.id))
        self.stored = {q.id: q for q in _of(nodes, Question)}
        self.variants: dict[str, list[Question]] = defaultdict(list[Question])
        for version in versions:
            for q in version:
                if q not in self.variants[q.id]:
                    self.variants[q.id].append(q)
        self.orders = [tuple(q for q in version if q.status == "open") for version in versions]
        self.recorded = {
            (r.run_date, len(lr.questions)): lr.questions
            for r in records
            for lr in r.line_records
            if lr.slug == slug and lr.questions
        }
        correct = {lb.subject for lb in _of(nodes, Label) if lb.verdict == "correct"}
        wrong = {lb.subject for lb in _of(nodes, Label) if lb.verdict == "incorrect"}
        self.gold_claims: dict[tuple[str, str], bool] = {}
        self.gold_pairs: dict[tuple[str, str], bool] = {}
        for log in self.logs:
            for claim in log.claims:
                verdict = _verdict(claim, log.id, correct, wrong)
                if verdict is not None:
                    self.gold_claims[(claim, log.question)] = verdict
                    source = self.source_of(claim)
                    if source is not None:
                        self._gold_pair(source, log.question, verdict)
            for source in log.sources:
                verdict = _verdict(source, log.id, correct, wrong)
                if verdict is not None:
                    self._gold_pair(source, log.question, verdict)

    def _gold_pair(self, source: str, question: str, verdict: bool) -> None:
        self.gold_pairs[(source, question)] = (
            self.gold_pairs.get((source, question), False) or verdict
        )

    def source_of(self, claim: str) -> str | None:
        c = self.claims.get(claim)
        u = self.units.get(c.unit) if c is not None else None
        return u.source if u is not None else None

    def question(self, qid: str) -> Question | None:
        return self.stored.get(qid) or next(iter(self.variants.get(qid, [])), None)

    def order(self, j: Judgment, source: SourceItem, n: int) -> tuple[str, ...] | None:
        """The question ids behind q0..q{n-1} of a prefilter Judgment, or None."""
        recorded = self.recorded.get((j.judged_at.date(), n))
        if recorded is not None:
            return recorded
        for qs in self.orders:
            if (
                len(qs) == n
                and input_sha256(question_prefilter.state(self.ctx, source, qs)) == j.state_sha256
            ):
                return tuple(q.id for q in qs)
        return None


def _verdict(subject: str, log: str, correct: set[str], wrong: set[str]) -> bool | None:
    if subject in correct or log in correct:
        return True
    if subject in wrong or log in wrong:
        return False
    return None


def _first(judgments: Iterable[Judgment], fn: str) -> dict[str, Judgment]:
    """The first Judgment of `fn` per source, of the current version, from any day: a run
    replays a stored answer, so a source triaged before `since` was not triaged again."""
    out: dict[str, Judgment] = {}
    ask = relevance_triage.ASK if fn == "relevance_triage" else source_trust.ASK
    for j in judgments:
        if j.function == fn and j.subjects[0] not in out:
            if judged_of(ask, j) is not None:
                out[j.subjects[0]] = j
    return out


def _screens(judgments: Iterable[Judgment], since: date) -> dict[tuple[str, str], list[Judgment]]:
    """Current-version screening Judgments per (source, question), within WINDOW_DAYS of the
    pair's first."""
    out: dict[tuple[str, str], list[Judgment]] = defaultdict(list[Judgment])
    for j in judgments:
        if j.function != "question_screening" or j.judged_at.date() < since:
            continue
        if judged_of(question_screening.ASK, j) is None:
            continue
        pair = (j.subjects[0], j.subjects[1])
        first = out[pair][0].judged_at.date() if out[pair] else j.judged_at.date()
        if (j.judged_at.date() - first).days <= WINDOW_DAYS:
            out[pair].append(j)
    return out


def _s_pairs(line: _Line, out: _Out, since: date) -> None:
    triage = _first(line.judgments, "relevance_triage")
    trust = _first(line.judgments, "source_trust")
    screens = _screens(line.judgments, since)
    seen: set[tuple[str, str]] = set()
    mapped = tried = 0
    for j in line.judgments:
        source = line.sources.get(j.subjects[0]) if j.function == "question_prefilter" else None
        if source is None or j.judged_at.date() < since or question_screening.no_abstract(source):
            continue
        n = sum(1 for a in j.answers if a.key.endswith("_on_topic"))
        if judged_of(question_prefilter.ask(n), j) is None:
            continue
        tried += 1
        order = line.order(j, source, n)
        if order is None:
            continue
        mapped += 1
        for index, qid in enumerate(order):
            if (source.id, qid) in seen:
                continue
            seen.add((source.id, qid))
            refs = [
                x
                for x in (
                    j,
                    triage.get(source.id),
                    trust.get(source.id),
                    *screens.get((source.id, qid), []),
                )
                if x is not None
            ]
            out.judgments.update({x.id: x for x in refs})
            day = j.judged_at.date()
            q = line.question(qid)
            out.pairs.append(
                SPair(
                    id=hashlib.sha256(f"{source.id}|{qid}".encode()).hexdigest()[:32],
                    line=line.slug,
                    source=source.id,
                    question=qid,
                    day=day,
                    split=split_of(f"{qid}|{day.isoformat()}"),
                    prefilter=j.id,
                    index=index,
                    triage=triage[source.id].id if source.id in triage else None,
                    trust=trust[source.id].id if source.id in trust else None,
                    trust_level=q.trust_level if q is not None else "report",
                    screening=tuple(x.id for x in screens.get((source.id, qid), [])),
                    stratum="",
                    gold=line.gold_pairs.get((source.id, qid)),
                )
            )
            out.sources[source.id] = source
            if q is not None:
                out.questions[qid] = q
    out.rebuild.setdefault(line.slug, {})["prefilter"] = (mapped, tried)


def _states(line: _Line, out: _Out, since: date) -> None:
    """Rebuild every screening state of the line's pairs; keep the ones whose hash matches."""
    before: dict[date, set[str]] = {}
    hit = tried = 0
    for j in line.judgments:
        if j.function != "question_screening" or j.judged_at.date() < since:
            continue
        source = line.sources.get(j.subjects[0])
        if source is None or judged_of(question_screening.ASK, j) is None:
            continue
        tried += 1
        day = j.judged_at.date()
        if day not in before:
            before[day] = claims_before(line.nodes, day)
        state = _screen_state(line, j, source, before[day])
        if state is not None:
            hit += 1
            out.states.append({"judgment": j.id, "subjects": list(j.subjects), "state": state})
    out.rebuild.setdefault(line.slug, {})["screening"] = (hit, tried)


def _screen_state(line: _Line, j: Judgment, source: SourceItem, scope: set[str]) -> JevState | None:
    qid = j.subjects[1]
    node = line.stored.get(qid)
    evidence = [
        line.claims[i].text
        for i in (node.evidence if node else ())
        if i in scope and i in line.claims
    ]
    for q in ([node] if node else []) + line.variants.get(qid, []):
        state = question_screening.state(line.ctx, source, q, evidence)
        if input_sha256(state) == j.state_sha256:
            return state
    return None


def _by_function(
    line: _Line,
) -> tuple[dict[tuple[str, str], list[Judgment]], dict[date, list[Judgment]]]:
    """claim_detection Judgments per (unit, question) in time order; novelty's per day."""
    detections: dict[tuple[str, str], list[Judgment]] = defaultdict(list[Judgment])
    novel: dict[date, list[Judgment]] = defaultdict(list[Judgment])
    for j in line.judgments:  # in time order
        if j.function == "claim_detection" and judged_of(claim_detection.ASK, j) is not None:
            detections[(j.subjects[0], j.subjects[1])].append(j)
        elif j.function == "novelty" and judged_of(novelty.ASK, j) is not None:
            novel[j.judged_at.date()].append(j)
    return detections, novel


def _parity(read: Judged_, x: XDay, out: _Out) -> None:
    """The baseline replay against the day's QuestionLogs, per question that has either."""
    replay: dict[str, set[str]] = {q: set() for q in x.shown}
    for e in x_shown(read, x, BASELINE):
        replay.setdefault(e.question, set()).add(e.claim)
    exact = sum(1 for q, cs in replay.items() if cs == set(x.shown.get(q, ())))
    out.tally("x_sections", exact, len(replay))


def _x_days(line: _Line, out: _Out, since: date) -> None:
    detections, novel = _by_function(line)
    read = Judged_(out.judgments)
    earlier: set[str] = set()
    seen: dict[str, set[str]] = defaultdict(set[str])
    seen_line: set[str] = set()
    for report in line.reports:
        day = report.run_date
        logs = {lg.question: lg.claims for lg in line.logs if lg.run_date == day}
        entries = (
            _entries(line, day, novel.get(day, []), detections, earlier=earlier, out=out)
            if day >= since
            else []
        )
        if entries or (logs and day >= since):
            x = XDay(
                id=f"{line.slug}|{day.isoformat()}",
                line=line.slug,
                day=day,
                split=split_of(f"{line.slug}|{day.isoformat()}"),
                entries=tuple(sorted(entries, key=lambda e: (e.question, e.claim))),
                shown={q: tuple(c) for q, c in logs.items()},
                seen={q: tuple(sorted(keys)) for q, keys in seen.items()},
                seen_line=tuple(sorted(seen_line)),
            )
            out.days.append(x)
            _parity(read, x, out)
        earlier |= set(report.claims)
        for q, cs in logs.items():
            for sid in (line.source_of(c) for c in cs):
                if sid is not None and sid in line.sources:
                    seen[q].add(paper_key(line.sources[sid]))
                    seen_line.add(paper_key(line.sources[sid]))


def _entries(
    line: _Line,
    day: date,
    judgments: Sequence[Judgment],
    detections: Mapping[tuple[str, str], Sequence[Judgment]],
    *,
    earlier: set[str],
    out: _Out,
) -> list[XEntry]:
    """The day's pool; each claim with the latest claim_detection Judgment asked by that day
    (a later one, after a question was reworded, is not what the run read)."""
    entries: list[XEntry] = []
    for j in judgments:
        cid, qid = j.subjects[0], j.subjects[1]
        claim = line.claims.get(cid)
        if cid in earlier or claim is None:
            continue
        unit = line.units.get(claim.unit)
        asked = [x for x in detections.get((claim.unit, qid), ()) if x.judged_at.date() <= day]
        cd = asked[-1] if asked else None
        source = line.sources.get(unit.source) if unit is not None else None
        if cd is None or source is None:
            continue
        out.judgments.update({j.id: j, cd.id: cd})
        out.sources[source.id] = source
        out.claims[cid] = claim.text
        if (q := line.question(qid)) is not None:
            out.questions[qid] = q
        entries.append(
            XEntry(
                claim=cid,
                question=qid,
                source=source.id,
                key=paper_key(source),
                detection=cd.id,
                novelty=j.id,
                gold=line.gold_claims.get((cid, qid)),
            )
        )
    return entries


def _screening_parity(line: _Line, out: _Out) -> None:
    """Stored screening Decisions whose outcome today's rule reproduces from their Judgment."""
    policies = {question_screening.ASK.policy, question_screening.BATCH_ASK.policy}
    by_id = {j.id: j for j in line.judgments}
    hit = tried = 0
    for d in _of(line.nodes, Decision):
        if d.policy not in policies or d.outcome == "unjudged" or d.judgments[0] not in by_id:
            continue
        judged = judged_of(question_screening.ASK, by_id[d.judgments[0]])
        if judged is None:
            continue
        tried += 1
        hit += question_screening.rule(judged)[0] == (d.outcome == "accept")
    out.tally("screening", hit, tried)


def s_stratum(read: Judged_, pair: SPair) -> str:
    outcome = s_outcome(read, pair, BASELINE)
    if outcome == "prefilter":
        pf = read.get("question_prefilter", pair.prefilter)
        p = float(getattr(pf.output, question_prefilter.field(pair.index))) if pf else 0.0
        return "pf-near" if p >= PF_NEAR else "pf-far"
    if outcome in ("safe", "unasked"):
        return outcome
    w = weighted_best(read, pair)
    if w is None:
        return "gate"
    for cut, name in ((0.7, "high"), (0.6, "band-high"), (0.5, "band-low")):
        if w >= cut:
            return name
    return "low"


def x_strata(read: Judged_, days: Sequence[XDay]) -> dict[str, str]:
    """(claim, question) item → its stratum on the first day it is in a pool."""
    out: dict[str, str] = {}
    for day in sorted(days, key=lambda d: d.day):
        shown = {e.item for e in x_shown(read, day, BASELINE)}
        pool = {e.item for e in x_pool(read, day, BASELINE)}
        for e in day.entries:
            if e.item not in out:
                out[e.item] = "shown" if e.item in shown else "cut" if e.item in pool else "dup"
    return out


@dataclass(frozen=True)
class Frozen_:
    root: Path
    manifest: Manifest


def freeze(env: Mapping[str, str], name: str, *, since: date = SINCE) -> Frozen_:
    """Freeze the set (module docstring) and return where it went."""
    tracks = env_tracks(env)
    store = GraphStore(store_dir(env))
    snapshot = read_snapshot(store, [t.slug for t in tracks])
    records = _of(snapshot.pipeline, RunRecord)
    out = _Out()
    for track in tracks:
        ctx = line_context(track)
        line = _Line(
            track.slug,
            snapshot.lines[track.slug],
            ctx,
            question_versions(questions_path(env, track.slug), line=ctx.line.id),
            records,
        )
        _s_pairs(line, out, since)
        _states(line, out, since)
        _x_days(line, out, since)
        _screening_parity(line, out)
    return _write(env, name, since, [t.slug for t in tracks], out)


DERIVED: Final = ("jitter.jsonl", "scores.jsonl", "results")
"""What later commands write beside a set: a refreeze moves them under superseded/<time>/, so
a noise floor or a score never describes a set it was not measured on."""


def _set_aside(root: Path, now: datetime) -> None:
    old = [root / n for n in DERIVED if (root / n).exists()]
    if old:
        dest = root / "superseded" / now.strftime("%Y%m%dT%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)
        for path in old:
            path.rename(dest / path.name)


def _write(env: Mapping[str, str], name: str, since: date, slugs: list[str], out: _Out) -> Frozen_:
    root = bench_dir(env, KIND, name)
    root.mkdir(parents=True, exist_ok=True)
    _set_aside(root, datetime.now(UTC))
    read = Judged_(out.judgments)
    pairs = [p.model_copy(update={"stratum": s_stratum(read, p)}) for p in out.pairs]
    items = x_strata(read, out.days)
    out.days = [
        d.model_copy(
            update={
                "entries": tuple(e.model_copy(update={"stratum": items[e.item]}) for e in d.entries)
            }
        )
        for d in out.days
    ]
    s_strata: dict[str, list[str]] = defaultdict(list[str])
    for p in pairs:
        s_strata[p.stratum].append(p.id)
    x_groups: dict[str, list[str]] = defaultdict(list[str])
    for item, stratum in items.items():
        x_groups[stratum].append(item)
    sample = {"s": draw(s_strata, S_SIZES, f"{name}/s"), "x": draw(x_groups, X_SIZES, f"{name}/x")}
    materials = _materials(pairs, out, sample, items)
    Partition(root / "judgments.jsonld").write_all(list(out.judgments.values()))
    _lines(root / "s_pairs.jsonl", (p.model_dump_json() for p in pairs))
    _lines(root / "x_days.jsonl", (d.model_dump_json() for d in out.days))
    _lines(root / "states.jsonl", (json.dumps(s, ensure_ascii=False) for s in out.states))
    _lines(root / "materials.jsonl", (m.model_dump_json() for m in materials))
    (root / "sample.json").write_text(
        json.dumps({k: {s: list(v) for s, v in d.items()} for k, d in sample.items()}, indent=1)
        + "\n",
        encoding="utf-8",
    )
    manifest = Manifest(
        name=name,
        created_at=datetime.now(UTC),
        store=str(store_dir(env)),
        since=since,
        lines=tuple(slugs),
        counts={
            "s_pairs": len(pairs),
            "s_dev": sum(1 for p in pairs if p.split == "dev"),
            "s_holdout": sum(1 for p in pairs if p.split == "holdout"),
            "x_dev": sum(1 for d in out.days if d.split == "dev"),
            "x_holdout": sum(1 for d in out.days if d.split == "holdout"),
            "x_days": len(out.days),
            "x_entries": sum(len(d.entries) for d in out.days),
            "judgments": len(out.judgments),
            "states": len(out.states),
            "materials": len(materials),
        },
        rebuild=out.rebuild,
        parity=out.parity,
        strata={
            "s": {k: len(v) for k, v in sorted(s_strata.items())},
            "x": {k: len(v) for k, v in sorted(x_groups.items())},
        },
        sizes={"s": dict(S_SIZES), "x": dict(X_SIZES)},
    )
    (root / "manifest.json").write_text(manifest.model_dump_json(indent=1) + "\n", encoding="utf-8")
    return Frozen_(root, manifest)


def _materials(
    pairs: Sequence[SPair],
    out: _Out,
    sample: Mapping[str, Mapping[str, Sequence[str]]],
    items: Mapping[str, str],
) -> list[Material]:
    by_id = {p.id: p for p in pairs}
    found: list[Material] = []
    for stratum, ids in sample["s"].items():
        for pid in ids:
            p = by_id[pid]
            q, s = out.questions.get(p.question), out.sources.get(p.source)
            if q is None or s is None:
                continue
            view = source_state(s)
            found.append(
                Material(
                    kind="s",
                    item=pid,
                    line=p.line,
                    stratum=stratum,
                    question=QuestionText.of(q),
                    title=s.title,
                    url=s.url,
                    adapter=s.adapter,
                    excerpt=str(view["excerpt"]),
                    key=paper_key(s),
                )
            )
    entries = {e.item: (d, e) for d in out.days for e in d.entries}
    for stratum, ids in sample["x"].items():
        for item in ids:
            d, e = entries[item]
            q, s = out.questions.get(e.question), out.sources.get(e.source)
            if q is None or s is None or items.get(item) != stratum:
                continue
            found.append(
                Material(
                    kind="x",
                    item=item,
                    line=d.line,
                    stratum=stratum,
                    question=QuestionText.of(q),
                    title=s.title,
                    claim=out.claims.get(e.claim, ""),
                    key=e.key,
                )
            )
    return found


def _lines(path: Path, rows: Iterable[str]) -> None:
    path.write_text("".join(f"{r}\n" for r in rows), encoding="utf-8")


@dataclass(frozen=True)
class GateSet:
    """A frozen set read back."""

    root: Path
    manifest: Manifest
    pairs: tuple[SPair, ...]
    days: tuple[XDay, ...]
    judgments: Mapping[str, Judgment]
    sample: Mapping[str, Mapping[str, tuple[str, ...]]]
    materials: Mapping[str, Material]

    def states(self) -> dict[str, tuple[tuple[str, ...], JevState]]:
        """Screening Judgment @id → (subjects, its rebuilt state)."""
        out: dict[str, tuple[tuple[str, ...], JevState]] = {}
        for raw in _read_lines(self.root / "states.jsonl"):
            row = json.loads(raw)
            out[row["judgment"]] = (tuple(row["subjects"]), row["state"])
        return out


class NoSet(FileNotFoundError):
    pass


def _read_lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def load(env: Mapping[str, str], name: str) -> GateSet:
    root = bench_dir(env, KIND, name)
    if not (root / "manifest.json").is_file():
        raise NoSet(f"no gate eval set {name!r} at {root}: run `jrp eval gate freeze` first")
    judgments = {
        i: n
        for i, n in Partition(root / "judgments.jsonld").load().items()
        if isinstance(n, Judgment)
    }
    sample_raw = json.loads((root / "sample.json").read_text(encoding="utf-8"))
    return GateSet(
        root=root,
        manifest=Manifest.model_validate_json((root / "manifest.json").read_text(encoding="utf-8")),
        pairs=tuple(SPair.model_validate_json(r) for r in _read_lines(root / "s_pairs.jsonl")),
        days=tuple(XDay.model_validate_json(r) for r in _read_lines(root / "x_days.jsonl")),
        judgments=judgments,
        sample={k: {s: tuple(v) for s, v in d.items()} for k, d in sample_raw.items()},
        materials={
            m.item: m
            for m in (
                Material.model_validate_json(r) for r in _read_lines(root / "materials.jsonl")
            )
        },
    )
