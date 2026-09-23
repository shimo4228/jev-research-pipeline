"""One line-run, anchored on the line's open questions (packet "Question-centric redesign").

    questions (author's file) → queries per question → fetch → per-source triage/trust
    → screening per (source, question) → Keep / Review / Drop / Incomplete
    → units → claim relation per (unit, question) → novelty against the question's
      evidence set → source support → question_movement per question
    → for every question that moved: prose + rubric ladder → QuestionLog → note section

A line with no open question does not run at all: NoQuestions ("問い未設定") is raised by
the questions module and the runner records it. Everything else is unchanged in spirit:
idempotent (decision 8) — fetches go through StageCache and every Jev judgment is looked
up by its @id before asking, so a same-day re-run asks nothing already answered; failures
never stop the run — Jev failures become "unjudged" items, fetch failures and query
fallbacks become operations lines; over the cost cap the remaining stages are skipped and
the report is written as partial.

Concurrency: within a stage every independent Jev request is in flight at once, up to
JRP_JEV_CONCURRENCY (pipeline.concurrency); Qwen calls up to JRP_PROSE_CONCURRENCY. Stages
still run one after another — novelty reads the evidence set the earlier stages settled,
question_movement reads what survived support. Three rules keep a parallel run equal to a
sequential one:
- the cost cap is read *after* a slot is taken (`_jev`), and JevClient counts a request's
  questions before its first await, so the overshoot is at most the requests already in
  flight when the cap trips — never a whole stage queued behind the semaphore;
- tasks return what they decided and the stage applies it afterwards in input order, so
  Decisions, notes, Review and the unjudged list do not depend on which request came
  back first (the store is written sorted by @id anyway);
- all of this is one event loop: a counter updated between two awaits needs no lock.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Collection, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, override

import httpx2
from pydantic import AwareDatetime, BaseModel

from jev_research_pipeline.adapters import (
    Adapter,
    arxiv,
    canary,
    firehose,
    github,
    hf_papers,
    openalex,
    web_search,
)
from jev_research_pipeline.jev import (
    Ask,
    JevClient,
    JevFailure,
    JevState,
    Judged,
    claim_detection,
    novelty,
    query_selection,
    question_movement,
    question_prefilter,
    question_screening,
    question_seeding,
    relevance_triage,
    rubric_claim,
    source_support,
    source_trust,
)
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.jev.core import BATCH_SUBJECT, JEV_MODEL, batches, output_of
from jev_research_pipeline.model import (
    AdapterKind,
    Claim,
    Decision,
    DiscoveryNet,
    GraphNodeType,
    Judgment,
    Label,
    Operations,
    QueryCandidate,
    Question,
    QuestionLog,
    Report,
    SourceItem,
    Unit,
)
from jev_research_pipeline.quality import agreement, axis_meters, build_report, rubric_ladder
from jev_research_pipeline.query_text import clean_query
from jev_research_pipeline.questions import AuthoredQueries, append_question
from jev_research_pipeline.qwen import (
    FLASH,
    MAX,
    GenerationMeter,
    Rendering,
    propose_questions,
    query_candidates,
    qwen_model,
)
from jev_research_pipeline.qwen.prose import prose_thinking, prose_timeout_s
from jev_research_pipeline.reduction import DecisionLog, RuleConfig, rule_candidates
from jev_research_pipeline.report import (
    CandidateEntry,
    ClaimEntry,
    QuestionSection,
    SourceEntry,
    render_report,
    write_note,
)
from jev_research_pipeline.store import ClaimIndex, Partition, StageCache, input_sha256
from jev_research_pipeline.telemetry import span

from . import meters, nets
from .concurrency import jev_concurrency, prose_concurrency
from .costs import Budget
from .units import split_units

QUERIES_PER_ADAPTER: Final = 3
GIST_CHARS: Final = 120
"""One evidence line shows this much of a source's text — enough to recognize it."""


def make_adapter(kind: AdapterKind, *, pacing: bool = True) -> Adapter:
    """`pacing=False` only for replayed runs (tests): no live request, no rate limit."""
    adapter = {
        "arxiv": arxiv.adapter,
        "hf_papers": hf_papers.adapter,
        "github": github.adapter,
        "web_search": web_search.adapter,
    }[kind]()
    return adapter if pacing else replace(adapter, min_interval_s=0.0)


def authored_candidates(
    line: str,
    questions: Sequence[Question],
    queries: Mapping[str, AuthoredQueries],
    *,
    kinds: Collection[AdapterKind],
    turn: int,
) -> tuple[list[QueryCandidate], list[str]]:
    """The questions' authored query lines as candidates, and the operations lines.

    Each adapter's list starts one query later on every run of the line (`turn` = the
    line's earlier runs, mod the list's length): the keyword budget and arXiv's
    one-search-a-line cap cut the list from the front, and a fixed order would send the
    first question's query every time and never the others. Counted in runs, not calendar
    days: a rotated line runs every few days, and a day ordinal would then land on the
    same start whenever that interval shares a factor with the list's length."""
    by_kind: dict[AdapterKind, dict[str, QueryCandidate]] = {}
    unusable: list[str] = []
    for question in questions:
        for kind, text in queries.get(question.id, ()):
            if kind not in kinds:
                continue
            cleaned = clean_query(text)
            if cleaned is None:
                unusable.append(text)
                continue
            c = QueryCandidate.new(line=line, adapter=kind, text=cleaned)
            by_kind.setdefault(kind, {})[c.id] = c
    out: list[QueryCandidate] = []
    for found in by_kind.values():
        listed = list(found.values())
        shift = turn % len(listed)
        out += listed[shift:] + listed[:shift]
    notes = [f"query: 問いファイルの {len(out)} 件を使用"] if out else []
    notes += [f"query: 検索語にならない行を skip ({text})" for text in unusable]
    return out, notes


class StoredJev(JevClient):
    """JevClient that answers from the store when the same judgment already exists — or
    is being asked right now: the same claim accepted for two questions reaches support
    twice in one stage, and a sequential run found the first answer in the store. A
    parallel one joins the request in flight (single-flight) instead of sending it again."""

    def __init__(
        self, http_client: httpx2.AsyncClient, *, api_key: str, known: dict[str, GraphNodeType]
    ) -> None:
        super().__init__(http_client, api_key=api_key)
        self.known = known
        self.fresh: list[Judgment] = []
        self._in_flight: dict[str, asyncio.Future[Any]] = {}

    @override
    async def judge[OutputT: BaseModel](
        self, ask: Ask[OutputT], subjects: tuple[str, ...], state: JevState, *, now: AwareDatetime
    ) -> Judged[OutputT] | JevFailure:
        jid = Judgment.id_for(ask.function, subjects, JEV_MODEL, input_sha256(state), ask.sha256)
        hit = self.known.get(jid)
        if isinstance(hit, Judgment):
            return Judged(output=output_of(ask.output, hit), judgment=hit)
        pending = self._in_flight.get(jid)
        if pending is not None:
            joined: Judged[OutputT] | JevFailure = await asyncio.shield(pending)
            return joined
        asked = asyncio.ensure_future(super().judge(ask, subjects, state, now=now))
        self._in_flight[jid] = asked
        try:
            result = await asked
        finally:
            del self._in_flight[jid]
        self._remember(result)
        return result

    @override
    async def judge_batch[OutputT: BaseModel](
        self,
        ask: Ask[OutputT],
        items: Sequence[tuple[tuple[str, ...], JevState]],
        *,
        subject: str,
        now: AwareDatetime,
    ) -> list[Judged[OutputT] | JevFailure]:
        """Only the items with no stored answer are sent. An answer counts whether it was
        asked alone or in a batch (either bundle): the item is the same question."""
        bundles = (ask.sha256, ask.batched(subject).sha256)
        found: dict[int, Judged[OutputT]] = {}
        for i, (subjects, state) in enumerate(items):
            for bundle in bundles:
                jid = Judgment.id_for(
                    ask.function, subjects, JEV_MODEL, input_sha256(state), bundle
                )
                hit = self.known.get(jid)
                if isinstance(hit, Judgment):
                    found[i] = Judged(output=output_of(ask.output, hit), judgment=hit)
                    break
        missing = [item for i, item in enumerate(items) if i not in found]
        asked = iter(await super().judge_batch(ask, missing, subject=subject, now=now))
        out: list[Judged[OutputT] | JevFailure] = []
        for i in range(len(items)):
            if i in found:
                out.append(found[i])
            else:
                result = next(asked)
                self._remember(result)
                out.append(result)
        return out

    def _remember(self, result: Judged[Any] | JevFailure) -> None:
        # A batch of one goes through judge(), which already remembered it.
        if isinstance(result, Judged) and result.judgment.id not in self.known:
            self.fresh.append(result.judgment)
            self.known[result.judgment.id] = result.judgment


@dataclass
class Keys:
    typesafe: str
    dashscope: str


@dataclass
class LineOutcome:
    report: Report
    note: Path
    operations: list[str]


@dataclass
class _Accepted:
    """One accepted claim, with the question it was accepted for."""

    claim: Claim
    source: SourceItem
    question: Question
    contradicts: bool = False
    """The claim counts against the answer the evidence set supports (claim_detection)."""
    bears_on: float = 0.0
    """claim_detection's combined advances-or-contradicts probability — the order in which
    claims are kept when a question has more than CLAIMS_PER_QUESTION."""


@dataclass
class _State:
    decisions: list[Decision] = field(default_factory=list[Decision])
    nodes: list[GraphNodeType] = field(default_factory=list[GraphNodeType])
    notes: list[str] = field(default_factory=list[str])
    unjudged: dict[str, str] = field(default_factory=dict[str, str])
    units: dict[str, Unit] = field(default_factory=dict[str, Unit])
    similar: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    review: list[SourceEntry] = field(default_factory=list[SourceEntry])
    bridges: list[SourceEntry] = field(default_factory=list[SourceEntry])
    candidates: list[Question] = field(default_factory=list[Question])
    per_net: dict[DiscoveryNet, int] = field(default_factory=dict[DiscoveryNet, int])
    discovery: list[str] = field(default_factory=list[str])
    openalex_credits: int = 0
    partial: bool = False
    pairs: int = 0
    """(source, question) pairs the prefilter asked about."""
    pairs_screened: int = 0
    failed_pairs: int = 0
    """Pairs whose Jev request failed (prefilter or full screen) — the 未判定 share."""
    routes: dict[str, int] = field(default_factory=dict[str, int])
    """Full-screen routes of the day (keep / review / drop / unjudged), for the empty-day line."""
    seconds: dict[str, float] = field(default_factory=dict[str, float])
    """Wall time per stage (operations section: where a slow run spent it)."""
    fetched: set[str] = field(default_factory=set[str])
    """URLs the nets brought today (canaries among them are judged by the screen itself)."""
    incomplete: int = 0
    """Sources with too little text to screen: counted, not listed."""


@dataclass
class _SectionDay:
    """What one question's section decided, applied by execute() in question order."""

    decisions: list[tuple[Decision, str]] = field(default_factory=list[tuple[Decision, str]])
    rubric: list[Decision] = field(default_factory=list[Decision])
    nodes: list[GraphNodeType] = field(default_factory=list[GraphNodeType])
    notes: list[str] = field(default_factory=list[str])
    made: tuple[QuestionSection, QuestionLog, Rendering] | None = None


CLAIMS_PER_QUESTION: Final = 5
CLAIMS_PER_SOURCE: Final = 2
CLAIMS_PER_NOTE: Final = 9
"""Spread over the questions that have claims: 1 → 5, 2 → 4, 3 → 3, 4+ → 2 each."""
NOTE_MAX_BYTES: Final = 12_000
"""A note above this drops question proposals, then the Review lines farthest from the
cut, until it fits (author mandate: note ≤ 12 KB = 12,288 bytes; margin for the line
that says what was dropped)."""
"""Reported claims per question section, and from one source within it (note ≤ 12 KB,
author mandate 2026-09-23)."""
REVIEW_MAX: Final = 10
"""Review lines per note (author mandate 2026-09-23); nearest the cut first."""
BRIDGES_PER_QUESTION: Final = 3
BRIDGES_MAX: Final = 5
"""橋渡し per question and per note (author mandate 2026-09-23: 2,509 of 2,570 pairs
accepted on the first pilot); likeliest first."""


def _top_bridges(found: list[tuple[str, float, SourceItem]]) -> list[SourceEntry]:
    """The likeliest BRIDGES_PER_QUESTION per question, then the likeliest BRIDGES_MAX of
    those, each source once."""
    per_question: dict[str, list[tuple[float, SourceItem]]] = {}
    for qid, p, s in found:
        per_question.setdefault(qid, []).append((p, s))
    shortlist = [
        pair
        for pairs in per_question.values()
        for pair in sorted(pairs, key=lambda x: -x[0])[:BRIDGES_PER_QUESTION]
    ]
    seen: set[str] = set()
    out: list[SourceEntry] = []
    for _p, s in sorted(shortlist, key=lambda x: -x[0]):
        if s.id not in seen and len(out) < BRIDGES_MAX:
            seen.add(s.id)
            out.append(_entry(s))
    return out


type _Screened = dict[tuple[str, str], Judged[question_screening.Answers] | JevFailure | None]
"""(source id, question id) → its screening answer; None where the cost cap stopped it."""


def _gist(text: str) -> str:
    """The first GIST_CHARS of a source, cut at a word (or, for Japanese, a character)
    boundary with an ellipsis — a line that stops mid-word reads as broken."""
    flat = " ".join(text.split())
    if len(flat) <= GIST_CHARS:
        return flat
    cut = flat[:GIST_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > GIST_CHARS // 2 else cut).rstrip(" ,;:—-") + "…"


def _entry(source: SourceItem, gist: str = "") -> SourceEntry:
    text = gist or _gist(source.text)
    return SourceEntry(source_id=source.id, title=source.title, gist=text, url=source.url)


class LineRun:
    def __init__(
        self,
        *,
        ctx: LineContext,
        questions: list[Question],
        seeds: list[str],
        partition: Partition,
        index_path: Path,
        vault: Path,
        http: httpx2.AsyncClient,
        keys: Keys,
        env: Mapping[str, str],
        now: AwareDatetime,
        harvest_notes: list[str],
        net_config: nets.NetConfig | None = None,
        day_budget: nets.DayBudget | None = None,
        pacing: bool = True,
        queries: Mapping[str, AuthoredQueries] | None = None,
    ) -> None:
        self.ctx, self.partition, self.index_path, self.vault = ctx, partition, index_path, vault
        self.questions, self.seeds = questions, seeds
        self.queries: Mapping[str, AuthoredQueries] = queries or {}
        """Authored query lines per Question @id (questions.question_queries)."""
        self.http, self.env, self.now = http, env, now
        self.known = partition.load()
        self.jev = StoredJev(http, api_key=keys.typesafe, known=self.known)
        self.keys = keys
        self.flash = qwen_model(FLASH, http, api_key=keys.dashscope)
        thinking = prose_thinking(env)
        self.max = qwen_model(MAX, http, api_key=keys.dashscope, thinking=thinking == "always")
        self.max_rewrite = (
            qwen_model(MAX, http, api_key=keys.dashscope, thinking=True)
            if thinking == "rewrite"
            else None
        )
        self.meters = {FLASH: GenerationMeter(), MAX: GenerationMeter()}
        self.budget = Budget(env)
        self.nets = net_config or nets.NetConfig()
        self.day = day_budget or nets.DayBudget()
        self.st = _State(notes=list(harvest_notes))
        self.pacing = pacing
        self.slots = asyncio.Semaphore(jev_concurrency(env))
        self.prose_slots = asyncio.Semaphore(prose_concurrency(env))

    # --- helpers ------------------------------------------------------------------------

    @contextmanager
    def _stage(self, name: str, **attributes: int) -> Generator[None]:
        """One stage: its OTel span, and its wall time for the operations section."""
        start = time.monotonic()
        with span(f"jrp.stage.{name}", line=self.ctx.line.slug, **attributes):
            yield
        self.st.seconds[name] = self.st.seconds.get(name, 0.0) + time.monotonic() - start

    def _over_budget(self) -> bool:
        if self.budget.exceeded(jev_questions=self.jev.questions_asked, meters=self.meters):
            self.st.partial = True
        return self.st.partial

    async def _jev[T](self, call: Callable[[], Awaitable[T]]) -> T | None:
        """One Jev step under the concurrency cap; None when the cost cap has tripped.

        The cap is read once the slot is held: read before, every task queued behind the
        semaphore would already have passed it."""
        async with self.slots:
            if self._over_budget():
                return None
            return await call()

    def _decide(self, d: Decision, label: str) -> Decision:
        self.st.decisions.append(d)
        if d.outcome == "unjudged":
            self.st.unjudged[d.subjects[0]] = label
        return d

    def _evidence_texts(self, question: Question) -> list[str]:
        """The question's running answer: the texts of the claims already accepted for it."""
        claims = (self.known.get(i) for i in question.evidence)
        return [c.text for c in claims if isinstance(c, Claim)]

    # --- stages -------------------------------------------------------------------------

    async def _query_candidates(
        self, kind: AdapterKind, question: Question
    ) -> tuple[tuple[QueryCandidate, ...], str | None] | None:
        """Qwen query candidates, cached per (adapter, question, day): a same-day re-run
        reuses them instead of generating (and paying for) different ones. The second
        value is the operations line for a fallback, applied by the caller in order. None
        when the cost cap has tripped by the time a Qwen slot is free."""
        cache = StageCache(self.partition)
        key = input_sha256(
            {"adapter": kind, "question": question.id, "day": self.now.date().isoformat()}
        )
        done = cache.lookup("query_candidates", key)
        if done is not None:
            loaded = self.partition.load()
            return tuple(n for i in done if isinstance(n := loaded[i], QueryCandidate)), None
        async with self.prose_slots:
            if self._over_budget():
                return None
            qr = await query_candidates(
                self.flash,
                self.ctx,
                kind,
                question,
                n=QUERIES_PER_ADAPTER,
                meter=self.meters[FLASH],
            )
        note = (
            f"{kind}: query 候補は fallback (問いと語彙から生成, {qr.failure})"
            if qr.fallback
            else None
        )
        self.partition.put(qr.candidates)
        cache.record("query_candidates", key, tuple(c.id for c in qr.candidates), self.now)
        return qr.candidates, note

    async def _selected(
        self, kind: AdapterKind, question: Question
    ) -> tuple[tuple[QueryCandidate, ...], list[Decision], list[str]] | None:
        """One (question, adapter): candidates, their ranked Decisions and the notes to
        apply. None when the cost cap stopped it before every candidate was judged."""
        generated = await self._query_candidates(kind, question)
        if generated is None:
            return None
        candidates, fallback = generated
        judged = await asyncio.gather(
            *(
                self._jev(
                    lambda c=c: query_selection.judge(self.jev, self.ctx, c, question, now=self.now)
                )
                for c in candidates
            )
        )
        results = [r for r in judged if r is not None]
        if len(results) != len(candidates):
            return None
        decisions = query_selection.rank(list(zip(candidates, results, strict=True)))
        notes = [fallback] if fallback else []
        if any(d.policy == query_selection.FLOOR_FALLBACK_POLICY for d in decisions):
            notes.append(
                f"{kind}: query 選択は floor fallback (どの候補も floor 未満のため上位を採用)"
            )
        return candidates, decisions, notes

    async def _queries(self) -> list[QueryCandidate]:
        """The authored queries of the questions that have them (no Qwen, no Jev), then
        the generated-and-selected ones for the questions that do not."""
        available: list[AdapterKind] = []
        for kind in self.ctx.line.adapters:
            needed = make_adapter(kind).required_env
            if needed is not None and not self.env.get(needed):
                self.st.notes.append(f"{kind}: key 未設定のため skip")
                continue
            available.append(kind)
        authored, authored_notes = authored_candidates(
            self.ctx.line.id,
            self.questions,
            self.queries,
            kinds=available,
            turn=sum(
                1
                for n in self.known.values()
                if isinstance(n, Report)
                and n.line == self.ctx.line.id
                and n.run_date < self.now.date()
            ),
        )
        self.st.notes += authored_notes
        self.partition.put(authored)
        runnable: list[tuple[Question, AdapterKind]] = [
            (question, kind)
            for question in self.questions
            if question.id not in self.queries
            for kind in available
        ]
        selected = await asyncio.gather(*(self._selected(k, q) for q, k in runnable))
        kept: list[QueryCandidate] = list(authored)
        for result in selected:
            if result is None:
                continue
            candidates, decisions, notes = result
            self.st.notes += notes
            for c, d in zip(candidates, decisions, strict=True):
                if self._decide(d, f"query: {c.text}").outcome == "accept":
                    kept.append(c)
        return kept

    def _positives_and_negatives(self) -> tuple[list[str], list[str]]:
        """What the recommender learns from: the author's ⭕ (and the papers behind the
        claims accepted so far) against the ❌, plus seeded random negatives."""
        labels = [n for n in self.known.values() if isinstance(n, Label)]
        by_verdict: dict[str, set[str]] = {"correct": set(), "incorrect": set()}
        for label in labels:
            source = self._source_of(label.subject)
            if source is not None:
                by_verdict[label.verdict].add(source.url)
        positives = [
            i for url in sorted(by_verdict["correct"]) if (i := nets.paper_id(url)) is not None
        ]
        negatives = [
            i for url in sorted(by_verdict["incorrect"]) if (i := nets.paper_id(url)) is not None
        ]
        if not negatives:
            # Drawn from what was stored *before today*: today's own fetches grow the pool
            # as the run goes, and a re-run would then send a different request to a pool
            # that is shared and rate-limited.
            pool = [
                i
                for n in self.known.values()
                if isinstance(n, SourceItem)
                and n.fetched_at.date() < self.now.date()
                and (i := nets.paper_id(n.url)) is not None
                and i not in positives
            ]
            negatives = nets.seeded_negatives(pool, seed=self.ctx.line.id)
        return positives, negatives

    def _source_of(self, subject: str) -> SourceItem | None:
        node = self.known.get(subject)
        if isinstance(node, SourceItem):
            return node
        if isinstance(node, Claim):
            unit = self.known.get(node.unit)
            if isinstance(unit, Unit):
                source = self.known.get(unit.source)
                return source if isinstance(source, SourceItem) else None
        return None

    def _cited_works(self) -> list[str]:
        """Papers this line already accepted, as OpenAlex `cites:` filter values."""
        urls: list[str] = []
        for question in self.questions:
            for claim_id in reversed(question.evidence):
                source = self._source_of(claim_id)
                if source is not None:
                    urls.append(source.url)
        works = [w for url in dict.fromkeys(urls) if (w := nets.openalex_work(url)) is not None]
        return works

    async def _fetch(
        self,
        queries: list[QueryCandidate],
        on_sources: Callable[[list[SourceItem]], None] | None = None,
    ) -> list[SourceItem]:
        """Every net, in the code-fixed order, within its budget (packet "Discovery").
        `on_sources` sees each request's new sources as they arrive (nets.fetch_nets)."""
        keyword = [(make_adapter(q.adapter, pacing=self.pacing), q.text) for q in queries]
        positives, negatives = self._positives_and_negatives()
        plan = nets.plan(
            self.nets,
            hf_date=firehose.hf_date(self.now),
            keyword_queries=keyword,
            positives=positives,
            negatives=negatives,
            cited=self._cited_works(),
            topics=self._topics(),
        )
        outcome = await nets.fetch_nets(
            plan,
            self.http,
            self.partition,
            self.ctx.line,
            now=self.now,
            env=self.env,
            config=self.nets,
            day=self.day,
            on_sources=on_sources,
        )
        self.st.notes += outcome.notes
        self.st.per_net = outcome.per_net
        self.st.openalex_credits = outcome.openalex_credits
        return outcome.sources

    def _topics(self) -> list[str]:
        """Topics next to this line's own: the ones its OpenAlex sources sit in, which the
        exploration net then walks out from. Empty until the citation net has run once."""
        seen = [
            topic
            for n in self.known.values()
            if isinstance(n, SourceItem)
            and n.adapter == "openalex"
            and (topic := openalex.topic_of(n.text)) is not None
        ]
        return list(dict.fromkeys(seen))

    async def _batched[OutputT: BaseModel](
        self, ask: Ask[OutputT], items: Sequence[tuple[tuple[str, ...], JevState]]
    ) -> list[Judged[OutputT] | JevFailure | None]:
        """One Jev function over many sources, several sources per request (core.batches),
        results back in item order; None where the cost cap stopped it."""
        chunks = batches([st for _, st in items], BATCH_SUBJECT)
        results = await asyncio.gather(
            *(
                self._jev(
                    lambda c=c: self.jev.judge_batch(
                        ask, [items[i] for i in c], subject=BATCH_SUBJECT, now=self.now
                    )
                )
                for c in chunks
            )
        )
        out: list[Judged[OutputT] | JevFailure | None] = [None] * len(items)
        for chunk, judged in zip(chunks, results, strict=True):
            if judged is not None:
                for j, i in enumerate(chunk):
                    out[i] = judged[j]
        return out

    def _screenable(self, s: SourceItem) -> bool:
        return not question_screening.no_abstract(s)

    async def _fetch_and_prefilter(
        self, queries: list[QueryCandidate]
    ) -> tuple[list[SourceItem], dict[str, list[int]]]:
        """Fetch every net and prefilter what they bring, overlapped: each net's sources are
        prefiltered as soon as its request is in, while later requests sit out their pacing
        gap. Returns the sources and, per source id, the indices of the questions it passed.
        The prefilter reads nothing a later fetch writes and its Decisions are applied in
        fetch order afterwards, so the overlap changes when, not what."""
        n = len(self.questions)
        ask = question_prefilter.ask(n)
        started: list[tuple[list[SourceItem], asyncio.Task[list[Any]]]] = []

        def start(fresh: list[SourceItem]) -> None:
            screen = [s for s in fresh if self._screenable(s)]
            items = question_prefilter.items(self.ctx, screen, self.questions)
            started.append((screen, asyncio.ensure_future(self._batched(ask, items))))

        with self._stage("fetch", queries=len(queries)):
            try:
                sources = await self._fetch(queries, on_sources=start)
            except BaseException:
                for _, task in started:
                    task.cancel()  # nothing is waiting on them any more
                raise
        with self._stage("prefilter", sources=len(sources)):
            passing: dict[str, list[int]] = {}
            for screen, task in started:
                for s, result in zip(screen, await task, strict=True):
                    if result is None:
                        continue
                    self._decide(question_prefilter.decision(result, n), s.title)
                    self.st.pairs += n
                    if isinstance(result, JevFailure):
                        self.st.failed_pairs += n
                    if hits := question_prefilter.passing(result, n):
                        passing[s.id] = hits
        self.st.incomplete = sum(1 for s in sources if not self._screenable(s))
        self.st.fetched = {s.url for s in sources}
        return sources, passing

    async def _safe_sources(self, sources: list[SourceItem]) -> list[SourceItem]:
        """The question-free pass on the sources some question is about: evidence and
        injection, then trust, each batched. Nothing is accepted before this pass."""
        tri = await self._batched(
            relevance_triage.ASK,
            [((s.id,), relevance_triage.state(self.ctx, s)) for s in sources],
        )
        evidenced: list[SourceItem] = []
        for s, result in zip(sources, tri, strict=True):
            if result is not None:
                if self._decide(relevance_triage.decision(result), s.title).outcome == "accept":
                    evidenced.append(s)
        trust = await self._batched(
            source_trust.ASK, [((s.id,), source_trust.state(s)) for s in evidenced]
        )
        kept: list[SourceItem] = []
        for s, result in zip(evidenced, trust, strict=True):
            if result is not None:
                if self._decide(source_trust.decision(result), s.title).outcome == "accept":
                    kept.append(s)
        return kept

    async def _screened(
        self, sources: list[SourceItem], passing: Mapping[str, list[int]]
    ) -> _Screened:
        """The full bundle for every (source, question) pair the prefilter passed. One
        request per (question, batch of sources): the question and its evidence set go
        once, the sources as slots (question_screening.BATCH_ASK)."""
        work: list[tuple[Question, list[SourceItem]]] = [
            (q, [s for s in sources if i in passing.get(s.id, [])])
            for i, q in enumerate(self.questions)
        ]
        results = await asyncio.gather(
            *(
                self._batched(
                    question_screening.ASK,
                    question_screening.items(self.ctx, chosen, q, self._evidence_texts(q)),
                )
                for q, chosen in work
            )
        )
        screened: _Screened = {}
        for (q, chosen), judged in zip(work, results, strict=True):
            for s, result in zip(chosen, judged, strict=True):
                screened[(s.id, q.id)] = result
        return screened

    async def _probe_canaries(self) -> list[str]:
        """Every canary the nets did not bring today is fetched by its URL and screened
        against its own question alone (a probe: SAFE's canaries must screen Keep). The
        answer is not stored and the source goes no further — it measures the screen, it
        does not feed the note. It goes through the run's own Jev client, so its questions
        count toward the cost cap as they are asked and a same-day re-run finds the answer
        stored; an arXiv canary is not fetched once arXiv is rate-limited today."""
        wanted = [
            (q, url)
            for q in self.questions
            for url in q.canary_papers
            if url not in self.st.fetched
        ]

        async def one(question: Question, url: str) -> str:
            planned = canary.plan(url)
            if planned is not None and any(
                key.endswith(f"/{planned[0].kind}") for key in self.day.quiet
            ):
                return (
                    f"canary 未取得: {question.slug} / {url} ({planned[0].kind} は本日 rate limit)"
                )
            got = await canary.fetch(self.http, self.ctx.line, url, now=self.now, env=self.env)
            if isinstance(got, str):
                return f"canary 取得失敗: {question.slug} / {url} ({got})"
            state = question_screening.state(
                self.ctx, got, question, self._evidence_texts(question)
            )
            result = await self._jev(
                lambda: self.jev.judge(
                    question_screening.ASK, (got.id, question.id), state, now=self.now
                )
            )
            if result is None:
                return f"canary 未判定 (費用上限): {question.slug} / {url}"
            return (
                f"canary: {question.slug} / {url} → {question_screening.route(result, source=got)}"
            )

        return list(await asyncio.gather(*(one(q, url) for q, url in wanted)))

    async def _screen(
        self, sources: list[SourceItem], passing: Mapping[str, list[int]]
    ) -> dict[str, list[SourceItem]]:
        """Screening per (source, question). Code routes: Keep goes on to claims, Review
        (judged borderlines only, capped) into the note, Drop nowhere, a Jev failure to
        未判定. bridges_line decides separately; the note shows the likeliest few."""
        screened = await self._screened(sources, passing)
        kept: dict[str, list[SourceItem]] = {q.id: [] for q in self.questions}
        review: dict[str, tuple[float, SourceEntry]] = {}
        bridges: list[tuple[str, float, SourceItem]] = []
        for (sid, qid), result in screened.items():
            if result is None:
                continue  # the cost cap stopped it
            s = next(x for x in sources if x.id == sid)
            question = next(q for q in self.questions if q.id == qid)
            self.st.pairs_screened += 1
            self._decide(question_screening.decision(result), s.title)
            bridged = self._decide(question_screening.bridges_decision(result), s.title)
            if bridged.outcome == "accept" and isinstance(result, Judged):
                bridges.append((qid, result.output.bridges_line, s))
            route = question_screening.route(result, source=s)
            self.st.routes[route] = self.st.routes.get(route, 0) + 1
            if route == "keep":
                kept[qid].append(s)
            elif route == "unjudged":
                self.st.failed_pairs += 1
            elif route == "review" and isinstance(result, Judged):
                distance = question_screening.review_distance(result)
                reason = f"「{question.title}」: {question_screening.review_reason(result)}"
                if sid not in review or distance < review[sid][0]:
                    review[sid] = (distance, _entry(s, reason))
        ranked = sorted(review.values(), key=lambda r: r[0])
        self.st.review += [entry for _, entry in ranked[:REVIEW_MAX]]
        if len(ranked) > REVIEW_MAX:
            self.st.notes.append(f"Review: {len(ranked)} 件のうち境界に近い {REVIEW_MAX} 件を表示")
        self.st.bridges += _top_bridges(bridges)
        if len({s.id for _, _, s in bridges}) > len(self.st.bridges):
            self.st.notes.append(
                f"橋渡し: {len(bridges)} 対が閾値を超え、確率上位 {len(self.st.bridges)} 件を表示"
            )
        return kept

    async def _claims(self, screened: Mapping[str, list[SourceItem]]) -> list[_Accepted]:
        work = [
            (question, s, u)
            for question in self.questions
            for s in screened.get(question.id, [])
            for u in split_units(s)
        ]
        results = await asyncio.gather(
            *(
                self._jev(
                    lambda q=q, s=s, u=u: claim_detection.judge(self.jev, q, u, s, now=self.now)
                )
                for q, s, u in work
            )
        )
        out: list[_Accepted] = []
        for (question, s, u), result in zip(work, results, strict=True):
            if result is None:
                continue  # the cost cap stopped it: the unit was never judged, so not stored
            self.st.nodes.append(u)
            self.st.units[u.id] = u
            d = self._decide(claim_detection.decision(result), u.text)
            if d.outcome == "accept":
                out.append(
                    _Accepted(
                        Claim.from_unit(u, line=self.ctx.line.id),
                        s,
                        question,
                        contradicts=isinstance(result, Judged)
                        and claim_detection.contradicts(result),
                        bears_on=d.score or 0.0,
                    )
                )
        return out

    async def _novel(self, accepted: list[_Accepted]) -> list[_Accepted]:
        # "Known" = claims reported on an EARLIER day. Today's own report (a same-day
        # re-run) is neither a duplicate source nor a novelty reference — otherwise a
        # re-run would empty today's report.
        earlier = {
            c
            for n in self.known.values()
            if isinstance(n, Report) and n.line == self.ctx.line.id and n.run_date < self.now.date()
            for c in n.claims
        }
        stored = {i: n for i, n in self.known.items() if isinstance(n, Claim) and i in earlier}
        index = ClaimIndex.rebuild(self.index_path, self.partition)
        fresh = [i for i in accepted if i.claim.id not in stored]  # else reported earlier
        for item in fresh:
            self.st.similar[item.claim.id] = [
                stored[i].text for i in novelty.similar_claims(index, item.claim) if i in stored
            ]
        results = await asyncio.gather(
            *(
                self._jev(
                    lambda item=item: novelty.judge(
                        self.jev,
                        item.question,
                        item.claim,
                        self._evidence_texts(item.question) + self.st.similar[item.claim.id],
                        now=self.now,
                    )
                )
                for item in fresh
            )
        )
        kept: list[_Accepted] = []
        for item, result in zip(fresh, results, strict=True):
            if result is None:
                continue  # no budget left to check it
            d = self._decide(novelty.decision(result), item.claim.text)
            if d.outcome == "accept":
                kept.append(item)
            elif d.outcome == "unjudged":
                self.st.unjudged[item.claim.id] = item.claim.text
        return kept

    async def _supported(self, accepted: list[_Accepted]) -> list[_Accepted]:
        """A claim stays only if its own source says it (code string match, else Jev)."""
        results = await asyncio.gather(
            *(
                self._jev(
                    lambda item=item: source_support.check(
                        self.jev, item.claim, item.source, now=self.now
                    )
                )
                for item in accepted
            )
        )
        kept: list[_Accepted] = []
        for item, support in zip(accepted, results, strict=True):
            if support is None:
                continue
            if support.decision is not None:
                self._decide(support.decision, item.claim.text)
            if support.verdict == "supports":
                kept.append(item)
        return kept

    async def _section(
        self, report_id: str, question: Question, items: list[_Accepted]
    ) -> "_SectionDay":
        """One question's day: did it move, and if so what the note says about it. Runs
        beside the other questions' days, so it only returns what it decided; execute()
        applies the days in question order."""
        day = _SectionDay()
        today = [i.claim.text for i in items]
        evidence = self._evidence_texts(question)
        result = await self._jev(
            lambda: question_movement.judge(self.jev, question, today, evidence, now=self.now)
        )
        if result is None:
            return day
        moved = question_movement.decision(result)
        day.decisions.append((moved, question.title))
        if moved.outcome != "accept":
            return day
        done = self.known.get(QuestionLog.id_for(question.id, self.now.date()))
        if (
            isinstance(done, QuestionLog)
            and done.text
            and done.claims == tuple(i.claim.id for i in items)
        ):
            # Same question-day over the same claims: reuse the text rather than paying
            # for a second draft that the author would then have to re-read.
            day.made = (
                QuestionSection(
                    question_id=question.id,
                    title=question.title,
                    prose=done.text,
                    evidence=tuple(
                        _entry(s) for s in {i.source.id: i.source for i in items}.values()
                    ),
                    contradictions=tuple(i.claim.text for i in items if i.contradicts),
                ),
                done,
                Rendering(rendering="prose", prose=done.text, rubric=()),
            )
            return day
        async with self.prose_slots:
            if self._over_budget():
                return day
            rendering, drafts = await rubric_ladder(
                jev=self.jev,
                model=self.max,
                rewrite_model=self.max_rewrite,
                ctx=self.ctx,
                question=question,
                report_id=report_id,
                claims=today,
                meter=self.meters[MAX],
                now=self.now,
                timeout_s=prose_timeout_s(self.env),
                evidence_set=evidence,
            )
        day.rubric += rendering.rubric
        day.nodes += drafts
        for i, attempt in enumerate(rendering.drafts, start=1):
            state = "生成" if attempt.prose else f"失敗 ({attempt.failure})"
            day.notes.append(f"{question.slug} prose 第{i}稿: {state} {attempt.seconds:.1f}s")
            if attempt.invalid_citations:
                cited = ", ".join(str(n) for n in attempt.invalid_citations)
                day.notes.append(f"{question.slug}: 存在しない引用 [{cited}] を削除")
        sources = list({i.source.id: i.source for i in items}.values())
        log = QuestionLog.new(
            question=question.id,
            report=report_id,
            run_date=self.now.date(),
            movement=question_movement.movement_of(result)
            if isinstance(result, Judged)
            else "none",
            text=rendering.prose or "",
            claims=tuple(i.claim.id for i in items),
            sources=tuple(s.id for s in sources),
            logged_at=self.now,
        )
        section = QuestionSection(
            question_id=question.id,
            title=question.title,
            prose=rendering.prose,
            evidence=tuple(_entry(s) for s in sources),
            contradictions=tuple(i.claim.text for i in items if i.contradicts),
        )
        day.made = (section, log, rendering)
        return day

    async def _rubric_claims(
        self, report_id: str, prose: Mapping[str, str | None], accepted: list[_Accepted]
    ) -> None:
        """Dense labels (decision 5): every accepted claim scored in its section's context."""

        def state(item: _Accepted) -> JevState:
            unit = self.st.units.get(item.claim.unit)
            return rubric_claim.state(
                self.ctx,
                item.claim,
                item.source,
                prose.get(item.question.id),
                self.st.similar.get(item.claim.id, []),
                span=(unit.start, unit.end) if unit is not None else None,
            )

        results = await asyncio.gather(
            *(
                self._jev(
                    lambda item=item: rubric_claim.judge(
                        self.jev, report_id, item.claim, state(item), now=self.now
                    )
                )
                for item in accepted
            )
        )
        for item, result in zip(accepted, results, strict=True):
            if result is not None:
                self._decide(rubric_claim.decision(result), item.claim.text)

    async def _propose(self) -> None:
        """Question candidates for the author to adopt (or not). One round per run, and
        only what Jev accepts: a wall of proposals is as unreadable as the claim wall was."""
        if self._over_budget():
            return
        cache = StageCache(self.partition)
        key = input_sha256({"line": self.ctx.line.id, "day": self.now.date().isoformat()})
        done = cache.lookup("question_proposals", key)
        if done is not None:
            loaded = self.partition.load()
            self.st.candidates += [n for i in done if isinstance(n := loaded.get(i), Question)]
            return
        result = await propose_questions(
            self.flash,
            self.ctx,
            self.seeds,
            meter=self.meters[FLASH],
            now=self.now,
            existing=self.questions,
        )
        if result.failure is not None:
            self.st.notes.append(f"問いの候補: 生成なし ({result.failure})")
            return
        known = {q.slug for q in self.questions}
        fresh = [c for c in result.questions if c.slug not in known]
        judged = await asyncio.gather(
            *(
                self._jev(
                    lambda c=c: question_seeding.judge(
                        self.jev, self.ctx, c, self.seeds, now=self.now
                    )
                )
                for c in fresh
            )
        )
        for candidate, j in zip(fresh, judged, strict=True):
            if j is None:
                continue
            if self._decide(question_seeding.decision(j), candidate.title).outcome == "accept":
                self.st.candidates.append(candidate)
        self.partition.put(self.st.candidates)
        cache.record("question_proposals", key, tuple(q.id for q in self.st.candidates), self.now)

    # --- run ----------------------------------------------------------------------------

    def _empty_day(self, claims: int) -> str:
        """One sentence on how far the day's sources got, for a note with no section."""
        silenced = [n.split(":")[0] for n in self.st.notes if "rate limit のため" in n]
        tail = f" {', '.join(silenced)} は rate limit で打ち切り。" if silenced else ""
        routes = self.st.routes
        where = (
            f" (Keep {routes.get('keep', 0)} / Review {routes.get('review', 0)} / "
            f"Drop {routes.get('drop', 0)})"
            if self.st.pairs_screened
            else ""
        )
        return (
            f"取得 {len(self.st.fetched)} 件のうち、問いに関係しそうな (source, 問い) 対が "
            f"{self.st.pairs_screened}{where}、採用された claim が {claims} 件。{tail}"
        )

    def _discovery_lines(self, accepted: list[_Accepted]) -> list[str]:
        """Which net earned its budget, and whether the search is narrowing."""
        loaded = self.partition.load()
        # Today's units and claims are still in flight (they are stored after the note is
        # rendered), so the maps have to carry them or every share reads zero.
        units = {i: n for i, n in loaded.items() if isinstance(n, Unit)} | self.st.units
        sources = {i: n for i, n in loaded.items() if isinstance(n, SourceItem)}
        sources |= {i.source.id: i.source for i in accepted}
        shares = meters.share_per_net([i.claim for i in accepted], units, sources)
        today = [s for s in sources.values() if s.fetched_at.date() == self.now.date()]
        before = [s for s in sources.values() if s.fetched_at.date() < self.now.date()]
        reports = sorted(
            (
                n
                for n in loaded.values()
                if isinstance(n, Report)
                and n.line == self.ctx.line.id
                and n.run_date < self.now.date()  # today's own report is `accepted` below
            ),
            key=lambda r: r.run_date,
        )
        cumulative = [len(r.claims) for r in reports] + [len(accepted)]
        running = [sum(cumulative[: i + 1]) for i in range(len(cumulative))]
        claims = {i: n for i, n in loaded.items() if isinstance(n, Claim)}
        claims |= {i.claim.id: i.claim for i in accepted}
        labels = [n for n in loaded.values() if isinstance(n, Label)]
        return meters.lines(
            self.st.per_net,
            shares,
            clusters=meters.topic_clusters(today),
            previous_clusters=meters.topic_clusters(before) if before else None,
            fit=meters.convergence(running),
            openalex_credits=self.st.openalex_credits,
            ttd=meters.time_to_discovery(labels, sources, claims, units),
        )

    def _operations(self, today_judgments: list[Judgment]) -> tuple[Operations, list[str]]:
        log = DecisionLog.from_nodes(
            [*self.partition.load().values(), *self.st.nodes, *self.jev.fresh, *self.st.decisions]
        )
        agreements = agreement(log.judgments, log.labels)
        meters = axis_meters(today_judgments, agreements)
        cost = self.budget.cost(jev_questions=self.jev.questions_asked, meters=self.meters)
        fill = fill_rate_previous(self.known, self.ctx.line.id, self.now)
        ops = Operations(
            jev_questions=self.jev.questions_asked,
            generation_input_tokens=sum(m.input_tokens for m in self.meters.values()),
            generation_output_tokens=sum(m.output_tokens for m in self.meters.values()),
            claude_calls=0,
            cost_usd=cost,
            rubric=meters,
            fill_rate_previous=fill,
        )
        lines = [
            f"Jev 質問数: {ops.jev_questions}",
            f"生成 token: in {ops.generation_input_tokens} / out {ops.generation_output_tokens}",
            "claude_calls: 0",
            f"cost: ${cost:.4f}" + ("" if self.budget.jev_price_known else " (Jev 単価未設定)"),
            f"記入率 (前回・問い日): {fill:.2f}" if fill is not None else "記入率 (前回): なし",
            f"open な問い: {len(self.questions)} 件",
            *(
                f"rubric {m.axis}: 平均 {m.mean_score:.2f} / gold 一致 "
                + (f"{m.gold_agreement:.2f}" if m.gold_agreement is not None else "未計測")
                if m.mean_score is not None
                else f"rubric {m.axis}: データなし"
                for m in meters
            ),
            *self.st.discovery,
            *rule_candidates(log, RuleConfig(), today=self.now.date()),
        ]
        if self.jev.retries:
            lines.append(f"Jev 再試行: {self.jev.retries} 回 (一時的な失敗を 2 秒後に 1 回)")
        if self.st.pairs:
            share = self.st.failed_pairs / self.st.pairs
            lines.append(
                f"(source, 問い) 対の Jev 失敗: {self.st.failed_pairs} / {self.st.pairs}"
                f" ({share:.1%}); full screen {self.st.pairs_screened} 対"
            )
        if self.st.incomplete:
            lines.append(f"本文なし: {self.st.incomplete} 件 (screening 対象外)")
        if self.st.seconds:
            lines.append(
                "段の所要: " + " / ".join(f"{k} {v:.0f}s" for k, v in self.st.seconds.items())
            )
        if self.st.partial:
            lines.append("partial: 費用上限に達したため以降の判定を省略")
        # The same line from several (question, adapter) pairs says one thing once.
        return ops, list(dict.fromkeys(lines + self.st.notes))

    async def _gather(self) -> tuple[list[_Accepted], dict[str, list[SourceItem]]]:
        if self._over_budget():
            return [], {}
        with self._stage("queries", questions=len(self.questions)):
            queries = await self._queries()
        sources, passing = await self._fetch_and_prefilter(queries)
        with self._stage("triage", sources=len(passing)):
            safe = await self._safe_sources([s for s in sources if s.id in passing])
        with self._stage("screen", sources=len(safe)):
            screened = await self._screen(safe, passing)
        with self._stage("claims"):
            detected = await self._claims(screened)
        with self._stage("novelty", claims=len(detected)):
            novel = await self._novel(detected)
        with self._stage("support", claims=len(novel)):
            supported = await self._supported(novel)
        return self._capped_claims(supported), screened

    def _capped_claims(self, accepted: list[_Accepted]) -> list[_Accepted]:
        """At most CLAIMS_PER_QUESTION per question, and at most CLAIMS_PER_SOURCE from one
        source, the likeliest to bear on the question first (scratch run 3: 31 claims under
        one question made a 24.6 KB note; the prose cannot use 31 anyway). The rest keep
        their Decisions and Claim nodes in the store but are not reported, so they do not
        join the evidence set and may be judged again on a later day."""
        kept: list[_Accepted] = []
        with_claims = len({i.question.id for i in accepted})
        # The note-wide budget shared by the questions that have claims (scratch run 10:
        # three sections of five claims made a 16.4 KB note).
        per_question = min(CLAIMS_PER_QUESTION, max(2, CLAIMS_PER_NOTE // max(with_claims, 1)))
        for question in self.questions:
            mine = sorted(
                (i for i in accepted if i.question.id == question.id), key=lambda i: -i.bears_on
            )
            per_source: dict[str, int] = {}
            chosen: list[_Accepted] = []
            for item in mine:
                if len(chosen) >= per_question:
                    break
                if per_source.get(item.source.id, 0) < CLAIMS_PER_SOURCE:
                    per_source[item.source.id] = per_source.get(item.source.id, 0) + 1
                    chosen.append(item)
            if len(mine) > len(chosen):
                self.st.notes.append(
                    f"{question.slug}: claim {len(mine)} 件のうち {len(chosen)} 件を掲載"
                )
            kept += chosen
            self.st.nodes += [i.claim for i in mine if i not in chosen]
        return kept

    async def execute(self) -> LineOutcome:
        report_id = Report.id_for(self.ctx.line.id, self.now.date())
        sections: list[QuestionSection] = []
        logs: list[QuestionLog] = []
        rendering = Rendering(rendering="template", prose=None, rubric=())
        slug = self.ctx.line.slug
        with span("jrp.line", line=slug, date=self.now.date().isoformat()) as line:
            accepted, screened = await self._gather()
            if not self.st.partial:
                # A run cut short by the cost cap never screened everything, so a missing
                # canary would say the screen drifted when the budget simply ran out.
                self.st.notes += canary_lines(self.questions, screened, self.st.fetched)
                with self._stage("canary"):
                    self.st.notes += await self._probe_canaries()
            self.st.discovery = self._discovery_lines(accepted)
            with self._stage("sections", claims=len(accepted)):
                moving = [
                    (q, items)
                    for q in self.questions
                    if (items := [i for i in accepted if i.question.id == q.id])
                ]
                days = await asyncio.gather(
                    *(self._section(report_id, q, items) for q, items in moving)
                )
                for day in days:
                    for d, label in day.decisions:
                        self._decide(d, label)
                    self.st.decisions += day.rubric
                    self.st.nodes += day.nodes
                    self.st.notes += day.notes
                    if day.made is not None:
                        section, log, rendering = day.made
                        sections.append(section)
                        logs.append(log)
            with self._stage("rubric", claims=len(accepted)):
                prose = {s.question_id: s.prose for s in sections}
                await self._rubric_claims(report_id, prose, accepted)
            with self._stage("propose"):
                await self._propose()
            line.set_attribute(
                "jrp.cost_usd",
                self.budget.cost(jev_questions=self.jev.questions_asked, meters=self.meters),
            )
            line.set_attribute("jrp.jev_questions", self.jev.questions_asked)
            line.set_attribute("jrp.sections", len(sections))
        ops, lines = self._operations(self.jev.fresh)
        claims = tuple(dict.fromkeys(i.claim.id for i in accepted))
        report = build_report(
            line=self.ctx.line.id,
            run_date=self.now.date(),
            rendering=_joined(rendering, sections),
            claims=claims,
            unjudged=tuple(i for i in self.st.unjudged if i not in set(claims)),
            partial=self.st.partial,
            operations=ops,
        )
        self.partition.put(
            [
                *self.st.nodes,
                *self.jev.fresh,
                *self.st.decisions,
                *(i.claim for i in accepted),
                *logs,
                *_with_evidence(self.questions, accepted),
                *self.st.candidates,
                report,
            ]
        )
        review = list(self.st.review)
        candidates = [
            CandidateEntry(slug=q.slug, title=q.title, brief=q.brief) for q in self.st.candidates
        ]

        def rendered(ops: list[str]) -> str:
            return render_report(
                report=report,
                ctx=self.ctx,
                sections=sections,
                claims=_claim_entries(accepted, {s.question_id for s in sections}),
                review=review,
                candidates=candidates,
                bridges=self.st.bridges,
                unjudged=[self.st.unjudged[i] for i in report.unjudged],
                operations=ops,
                empty_day=self._empty_day(len(accepted)),
            )

        text, lines = _fitted(rendered, lines, candidates, review)
        return LineOutcome(
            report=report,
            note=write_note(self.vault, slug, self.now.date(), text),
            operations=lines,
        )


def _fitted(
    rendered: Callable[[list[str]], str],
    lines: list[str],
    candidates: list[CandidateEntry],
    review: list[SourceEntry],
) -> tuple[str, list[str]]:
    """The note within NOTE_MAX_BYTES, and the operations lines it was rendered with. The
    body and the claims stay; what goes is what the author finds again tomorrow (proposals
    repeat) and then Review, farthest from the cut first. `candidates` and `review` are
    shortened in place (the renderer reads them)."""
    text = rendered(lines)
    dropped = {"候補": 0, "Review": 0}
    ops = lines
    while len(text.encode()) > NOTE_MAX_BYTES and (candidates or review):
        if candidates:
            candidates.pop()
            dropped["候補"] += 1
        else:
            review.pop()
            dropped["Review"] += 1
        said = " / ".join(f"{k} {v} 件" for k, v in dropped.items() if v)
        ops = [*lines, f"note 12 KB のため省略: {said}"]
        text = rendered(ops)
    return text, ops


def canary_lines(
    questions: list[Question],
    screened: Mapping[str, list[SourceItem]],
    fetched: Collection[str] | None = None,
) -> list[str]:
    """A canary paper the author named must survive screening on a day it was fetched
    (SAFE): a drop means the screen drifted, and the note says so. A canary the nets did
    not bring is not a drop — _probe_canaries() fetches and judges it instead."""
    lines: list[str] = []
    for question in questions:
        kept = {s.url for s in screened.get(question.id, [])}
        lines += [
            f"canary 落下: {question.slug} / {url}"
            for url in question.canary_papers
            if url not in kept and (fetched is None or url in fetched)
        ]
    return lines


def _claim_entries(accepted: list[_Accepted], with_prose: set[str]) -> list[ClaimEntry]:
    """The folded claim list, each claim keyed to the [n] its section's prose uses — the
    same order _section() hands the claims to the prose call: accepted order within a
    question."""
    n: dict[str, int] = {}
    out: list[ClaimEntry] = []
    for item in accepted:
        qid = item.question.id
        n[qid] = n.get(qid, 0) + 1
        cite = f"{item.question.slug} [{n[qid]}]" if qid in with_prose else ""
        out.append(ClaimEntry(claim=item.claim, source_url=item.source.url, cite=cite))
    return out


def _joined(rendering: Rendering, sections: list[QuestionSection]) -> Rendering:
    """The Report keeps the day's prose as one text (the note and the QuestionLogs keep it
    per question). Its rendering is "template" only when no section has prose."""
    joined = "\n\n".join(f"### {s.title}\n\n{s.prose}" for s in sections if s.prose)
    if not joined:
        return rendering.model_copy(update={"rendering": "template", "prose": None})
    # A later section on the template must not make the day "template" while an earlier
    # one has prose (scratch run 9: akc failed on Report's rendering/prose invariant).
    kind = rendering.rendering if rendering.rendering != "template" else "prose"
    return rendering.model_copy(update={"rendering": kind, "prose": joined})


def _with_evidence(questions: list[Question], accepted: list[_Accepted]) -> list[Question]:
    """The questions whose evidence set grew today, with today's claims appended. The @id
    does not move (evidence is not identity), so this updates the stored node in place —
    and because `questions` was loaded with the stored evidence merged in, the set grows
    rather than being replaced by the day's claims."""
    out: list[Question] = []
    for question in questions:
        fresh = [
            i
            for i in dict.fromkeys(a.claim.id for a in accepted if a.question.id == question.id)
            if i not in question.evidence
        ]
        if fresh:
            out.append(question.model_copy(update={"evidence": (*question.evidence, *fresh)}))
    return out


def adopt_candidates(
    env: Mapping[str, str], slug: str, adopted: tuple[str, ...], known: Mapping[str, Question]
) -> list[str]:
    """Append every proposal the author ticked to the line's question file. The proposals
    were stored when they were written into the note, so a tick needs no re-generation."""
    lines: list[str] = []
    for candidate in adopted:
        question = known.get(candidate)
        if question is not None:
            append_question(env, slug, question)
            lines.append(f"問いを採用: {question.title}")
    return lines


def fill_rate_previous(
    nodes: Mapping[str, GraphNodeType], line: str, now: AwareDatetime
) -> float | None:
    """Primary metric (decision 7), now counted over question-days: ticked question-days
    of the line's latest earlier report."""
    reports = [
        n
        for n in nodes.values()
        if isinstance(n, Report) and n.line == line and n.run_date < now.date()
    ]
    if not reports:
        return None
    last = max(reports, key=lambda r: r.run_date)
    days = [n.id for n in nodes.values() if isinstance(n, QuestionLog) and n.report == last.id]
    if not days:
        return None
    ticked = {
        n.subject
        for n in nodes.values()
        if isinstance(n, Label) and n.report == last.id and n.provenance == "question_day"
    }
    return len(ticked & set(days)) / len(days)
