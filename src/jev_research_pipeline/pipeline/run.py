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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, override

import httpx2
from pydantic import AwareDatetime, BaseModel

from jev_research_pipeline.adapters import (
    Adapter,
    arxiv,
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
    question_screening,
    question_seeding,
    relevance_triage,
    rubric_claim,
    source_support,
    source_trust,
)
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.jev.core import JEV_MODEL, batches, output_of
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
from jev_research_pipeline.questions import append_question
from jev_research_pipeline.qwen import (
    FLASH,
    MAX,
    GenerationMeter,
    Rendering,
    propose_questions,
    query_candidates,
    qwen_model,
)
from jev_research_pipeline.qwen.prose import prose_timeout_s
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
GIST_CHARS: Final = 160
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


@dataclass
class _SectionDay:
    """What one question's section decided, applied by execute() in question order."""

    decisions: list[tuple[Decision, str]] = field(default_factory=list[tuple[Decision, str]])
    rubric: list[Decision] = field(default_factory=list[Decision])
    nodes: list[GraphNodeType] = field(default_factory=list[GraphNodeType])
    notes: list[str] = field(default_factory=list[str])
    made: tuple[QuestionSection, QuestionLog, Rendering] | None = None


type _Screened = dict[tuple[str, str], Judged[question_screening.Answers] | JevFailure | None]
"""(source id, question id) → its screening answer; None where the cost cap stopped it."""


def _entry(source: SourceItem, gist: str = "") -> SourceEntry:
    text = gist or " ".join(source.text.split())[:GIST_CHARS]
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
    ) -> None:
        self.ctx, self.partition, self.index_path, self.vault = ctx, partition, index_path, vault
        self.questions, self.seeds = questions, seeds
        self.http, self.env, self.now = http, env, now
        self.known = partition.load()
        self.jev = StoredJev(http, api_key=keys.typesafe, known=self.known)
        self.flash = qwen_model(FLASH, http, api_key=keys.dashscope)
        self.max = qwen_model(MAX, http, api_key=keys.dashscope)
        self.meters = {FLASH: GenerationMeter(), MAX: GenerationMeter()}
        self.budget = Budget(env)
        self.nets = net_config or nets.NetConfig()
        self.day = day_budget or nets.DayBudget()
        self.st = _State(notes=list(harvest_notes))
        self.pacing = pacing
        self.slots = asyncio.Semaphore(jev_concurrency(env))
        self.prose_slots = asyncio.Semaphore(prose_concurrency(env))

    # --- helpers ------------------------------------------------------------------------

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
        runnable: list[tuple[Question, AdapterKind]] = []
        skipped: set[AdapterKind] = set()
        for question in self.questions:
            for kind in self.ctx.line.adapters:
                needed = make_adapter(kind).required_env
                if needed is not None and not self.env.get(needed):
                    if kind not in skipped:
                        skipped.add(kind)
                        self.st.notes.append(f"{kind}: key 未設定のため skip")
                    continue
                runnable.append((question, kind))
        selected = await asyncio.gather(*(self._selected(k, q) for q, k in runnable))
        kept: list[QueryCandidate] = []
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
            run_date=self.now.date().isoformat(),
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

    async def _triaged(self, s: SourceItem) -> list[Decision]:
        """Evidence and injection, then trust — the Decisions made, in that order. The
        source is safe when there are two and the last accepts."""
        tri = await self._jev(lambda: relevance_triage.judge(self.jev, self.ctx, s, now=self.now))
        if tri is None:
            return []
        first = relevance_triage.decision(tri)
        if first.outcome != "accept":
            return [first]
        trust = await self._jev(lambda: source_trust.judge(self.jev, s, now=self.now))
        return [first] if trust is None else [first, source_trust.decision(trust)]

    def _apply_triage(self, sources: Sequence[SourceItem], results: Sequence[list[Decision]]):
        kept: list[SourceItem] = []
        for s, decisions in zip(sources, results, strict=True):
            for d in decisions:
                self._decide(d, s.title)
            if len(decisions) == 2 and decisions[1].outcome == "accept":
                kept.append(s)
        return kept

    async def _fetch_and_triage(self, queries: list[QueryCandidate]) -> list[SourceItem]:
        """Fetch every net and run the question-free pass (triage, trust) on what they
        bring, overlapped: a source is triaged as soon as its request is in, while the
        later requests still sit out their pacing gap (arXiv 3 s, GitHub and HF 6 s).
        Whether a source is relevant is a per-question judgment, and happens in _screen().
        Triage reads nothing that a later fetch writes, and the Decisions are applied in
        fetch order afterwards, so the overlap changes when, not what."""
        triage: list[asyncio.Task[list[Decision]]] = []

        def start(fresh: list[SourceItem]) -> None:
            triage.extend(asyncio.ensure_future(self._triaged(s)) for s in fresh)

        slug = self.ctx.line.slug
        with span("jrp.stage.fetch", line=slug, queries=len(queries)):
            try:
                sources = await self._fetch(queries, on_sources=start)
            except BaseException:
                for task in triage:
                    task.cancel()  # nothing is waiting on them any more
                raise
        with span("jrp.stage.triage", line=slug, sources=len(sources)):
            return self._apply_triage(sources, await asyncio.gather(*triage))

    async def _screened(self, sources: list[SourceItem]) -> _Screened:
        """Every (source, question) answer, None where the cost cap stopped it. One request
        per (question, batch of sources): the question and its evidence set go once, the
        sources as slots (question_screening.BATCH_ASK)."""
        screenable = [s for s in sources if not question_screening.no_abstract(s)]
        work: list[tuple[Question, list[SourceItem], list[tuple[tuple[str, ...], JevState]]]] = []
        for q in self.questions:
            items = question_screening.items(self.ctx, screenable, q, self._evidence_texts(q))
            for idx in batches([st for _, st in items], question_screening.SUBJECT):
                work.append((q, [screenable[i] for i in idx], [items[i] for i in idx]))
        results = await asyncio.gather(
            *(
                self._jev(
                    lambda chunk=chunk: self.jev.judge_batch(
                        question_screening.ASK,
                        chunk,
                        subject=question_screening.SUBJECT,
                        now=self.now,
                    )
                )
                for _, _, chunk in work
            )
        )
        screened: _Screened = {}
        for (q, chunk_sources, _), judged in zip(work, results, strict=True):
            for i, s in enumerate(chunk_sources):
                screened[(s.id, q.id)] = None if judged is None else judged[i]
        return screened

    async def _screen(self, sources: list[SourceItem]) -> dict[str, list[SourceItem]]:
        """Screening per (source, question). Code routes: Keep goes on to claims, Review
        into the note for the author, Drop and Incomplete nowhere. bridges_line decides
        separately, so a source from outside the vocabulary still reaches 橋渡し."""
        screened = await self._screened(sources)
        kept: dict[str, list[SourceItem]] = {q.id: [] for q in self.questions}
        reviewed: set[str] = set()
        bridged: set[str] = set()
        for s in sources:
            if question_screening.no_abstract(s):
                # Decided by len(source.text): asking Jev seven questions per open question
                # about a title would pay for a route that is already known. It still
                # reaches the author, in Review, rather than being dropped in silence.
                if s.id not in reviewed:
                    reviewed.add(s.id)
                    self.st.review.append(_entry(s, "本文が取得できず未判定"))
                continue
            for question in self.questions:
                result = screened[(s.id, question.id)]
                if result is None:
                    continue  # the cost cap stopped it
                self._decide(question_screening.decision(result), s.title)
                bridges = self._decide(question_screening.bridges_decision(result), s.title)
                if bridges.outcome == "accept" and s.id not in bridged:
                    bridged.add(s.id)
                    self.st.bridges.append(_entry(s))
                route = question_screening.route(result, source=s)
                if route == "keep":
                    kept[question.id].append(s)
                elif route == "review" and s.id not in reviewed:
                    reviewed.add(s.id)
                    self.st.review.append(_entry(s, f"「{question.title}」に対して判定保留"))
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
            self.flash, self.ctx, self.seeds, meter=self.meters[FLASH], now=self.now
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
        if self.st.partial:
            lines.append("partial: 費用上限に達したため以降の判定を省略")
        return ops, lines + self.st.notes

    async def _gather(self) -> tuple[list[_Accepted], dict[str, list[SourceItem]]]:
        slug = self.ctx.line.slug
        if self._over_budget():
            return [], {}
        with span("jrp.stage.queries", line=slug, questions=len(self.questions)):
            queries = await self._queries()
        safe = await self._fetch_and_triage(queries)
        with span("jrp.stage.screen", line=slug, sources=len(safe)):
            screened = await self._screen(safe)
        with span("jrp.stage.claims", line=slug):
            detected = await self._claims(screened)
        with span("jrp.stage.novelty", line=slug, claims=len(detected)):
            novel = await self._novel(detected)
        with span("jrp.stage.support", line=slug, claims=len(novel)):
            return await self._supported(novel), screened

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
                self.st.notes += canary_lines(self.questions, screened)
            self.st.discovery = self._discovery_lines(accepted)
            with span("jrp.stage.sections", line=slug, claims=len(accepted)):
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
            with span("jrp.stage.rubric", line=slug, claims=len(accepted)):
                prose = {s.question_id: s.prose for s in sections}
                await self._rubric_claims(report_id, prose, accepted)
            with span("jrp.stage.propose", line=slug):
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
        text = render_report(
            report=report,
            ctx=self.ctx,
            sections=sections,
            claims=[ClaimEntry(claim=i.claim, source_url=i.source.url) for i in accepted],
            review=self.st.review,
            candidates=[
                CandidateEntry(slug=q.slug, title=q.title, brief=q.brief)
                for q in self.st.candidates
            ],
            bridges=self.st.bridges,
            unjudged=[self.st.unjudged[i] for i in report.unjudged],
            operations=lines,
        )
        return LineOutcome(
            report=report,
            note=write_note(self.vault, slug, self.now.date(), text),
            operations=lines,
        )


def canary_lines(questions: list[Question], screened: Mapping[str, list[SourceItem]]) -> list[str]:
    """A canary paper the author named must survive screening on a day it was fetched
    (SAFE): a drop means the screen drifted, and the note says so."""
    lines: list[str] = []
    for question in questions:
        kept = {s.url for s in screened.get(question.id, [])}
        lines += [
            f"canary 落下: {question.slug} / {url}"
            for url in question.canary_papers
            if url not in kept
        ]
    return lines


def _joined(rendering: Rendering, sections: list[QuestionSection]) -> Rendering:
    """The Report keeps the day's prose as one text (the note and the QuestionLogs keep it
    per question); `rendering.rendering` is the last section's ladder outcome."""
    joined = "\n\n".join(f"### {s.title}\n\n{s.prose}" for s in sections if s.prose)
    return rendering.model_copy(update={"prose": joined or None})


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
