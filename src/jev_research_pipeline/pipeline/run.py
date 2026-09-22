"""One line-run: queries → selection → fetch → triage → trust → units → claims → novelty
→ support → ordering → prose + rubric ladder → rubric_claim → report note (decision 1).

Idempotent (decision 8): fetches go through StageCache; every Jev judgment is looked up by
its @id before asking (the id is computable from state, bundle, model and subjects), so a
same-day re-run asks nothing already answered. Failures never stop the run: Jev failures
become "unjudged" items, fetch failures and query fallbacks become operations lines. When
the cost cap is exceeded the remaining judging stages are skipped and the report is
written as partial.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, override

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline.adapters import Adapter, arxiv, collect, github, hf_papers, web_search
from jev_research_pipeline.jev import (
    Bundle,
    JevClient,
    JevFailure,
    JevState,
    claim_detection,
    novelty,
    query_selection,
    relevance_triage,
    report_ordering,
    rubric_claim,
    source_support,
    source_trust,
)
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.jev.core import JEV_MODEL
from jev_research_pipeline.model import (
    AdapterKind,
    Claim,
    Decision,
    GraphNodeType,
    Judgment,
    Label,
    Operations,
    QueryCandidate,
    Report,
    SourceItem,
    Unit,
)
from jev_research_pipeline.quality import agreement, axis_meters, build_report, rubric_ladder
from jev_research_pipeline.qwen import (
    FLASH,
    MAX,
    GenerationMeter,
    Rendering,
    query_candidates,
    qwen_model,
)
from jev_research_pipeline.qwen.prose import prose_timeout_s
from jev_research_pipeline.reduction import DecisionLog, RuleConfig, rule_candidates
from jev_research_pipeline.report import ClaimEntry, render_report, write_note
from jev_research_pipeline.store import ClaimIndex, Partition, StageCache, input_sha256

from .costs import Budget
from .units import split_units

QUERIES_PER_ADAPTER: Final = 3


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
    """JevClient that answers from the store when the same judgment already exists."""

    def __init__(
        self, http_client: httpx2.AsyncClient, *, api_key: str, known: dict[str, GraphNodeType]
    ) -> None:
        super().__init__(http_client, api_key=api_key)
        self.known = known
        self.fresh: list[Judgment] = []

    @override
    async def judge(
        self, bundle: Bundle, subjects: tuple[str, ...], state: JevState, *, now: AwareDatetime
    ) -> Judgment | JevFailure:
        jid = Judgment.id_for(
            bundle.function, subjects, JEV_MODEL, input_sha256(state), bundle.sha256
        )
        hit = self.known.get(jid)
        if isinstance(hit, Judgment):
            return hit
        result = await super().judge(bundle, subjects, state, now=now)
        if isinstance(result, Judgment):
            self.fresh.append(result)
            self.known[result.id] = result
        return result


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
class _State:
    decisions: list[Decision] = field(default_factory=list[Decision])
    nodes: list[GraphNodeType] = field(default_factory=list[GraphNodeType])
    notes: list[str] = field(default_factory=list[str])
    unjudged: dict[str, str] = field(default_factory=dict[str, str])
    units: dict[str, Unit] = field(default_factory=dict[str, Unit])
    similar: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    partial: bool = False


class LineRun:
    def __init__(
        self,
        *,
        ctx: LineContext,
        partition: Partition,
        index_path: Path,
        vault: Path,
        http: httpx2.AsyncClient,
        keys: Keys,
        env: Mapping[str, str],
        now: AwareDatetime,
        harvest_notes: list[str],
        pacing: bool = True,
    ) -> None:
        self.ctx, self.partition, self.index_path, self.vault = ctx, partition, index_path, vault
        self.http, self.env, self.now = http, env, now
        self.known = partition.load()
        self.jev = StoredJev(http, api_key=keys.typesafe, known=self.known)
        self.flash = qwen_model(FLASH, http, api_key=keys.dashscope)
        self.max = qwen_model(MAX, http, api_key=keys.dashscope)
        self.meters = {FLASH: GenerationMeter(), MAX: GenerationMeter()}
        self.budget = Budget(env)
        self.st = _State(notes=list(harvest_notes))
        self.pacing = pacing

    # --- helpers ------------------------------------------------------------------------

    def _over_budget(self) -> bool:
        if self.budget.exceeded(jev_questions=self.jev.questions_asked, meters=self.meters):
            self.st.partial = True
        return self.st.partial

    def _decide(self, d: Decision, label: str) -> Decision:
        self.st.decisions.append(d)
        if d.outcome == "unjudged":
            self.st.unjudged[d.subjects[0]] = label
        return d

    # --- stages -------------------------------------------------------------------------

    async def _candidates(self, kind: AdapterKind) -> tuple[QueryCandidate, ...]:
        """Qwen query candidates, cached per (adapter, vocabulary, day): a same-day re-run
        reuses them instead of generating (and paying for) different ones."""
        cache = StageCache(self.partition)
        key = input_sha256(
            {
                "adapter": kind,
                "vocabulary": list(self.ctx.vocabulary),
                "day": self.now.date().isoformat(),
            }
        )
        done = cache.lookup("query_candidates", key)
        if done is not None:
            return tuple(
                n for i in done if isinstance(n := self.partition.load()[i], QueryCandidate)
            )
        qr = await query_candidates(
            self.flash, self.ctx, kind, n=QUERIES_PER_ADAPTER, meter=self.meters[FLASH]
        )
        if qr.fallback:
            self.st.notes.append(f"{kind}: query 候補は fallback (語彙から生成, {qr.failure})")
        self.partition.put(qr.candidates)
        cache.record("query_candidates", key, tuple(c.id for c in qr.candidates), self.now)
        return qr.candidates

    async def _queries(self) -> list[QueryCandidate]:
        kept: list[QueryCandidate] = []
        for kind in self.ctx.line.adapters:
            if self._over_budget():
                break
            needed = make_adapter(kind).required_env
            if needed is not None and not self.env.get(needed):
                self.st.notes.append(f"{kind}: key 未設定のため skip")
                continue
            candidates = await self._candidates(kind)
            pairs = [
                (c, await query_selection.judge(self.jev, self.ctx, c, now=self.now))
                for c in candidates
            ]
            decisions = query_selection.rank(pairs)
            if any(d.policy == query_selection.FLOOR_FALLBACK_POLICY for d in decisions):
                self.st.notes.append(
                    f"{kind}: query 選択は floor fallback (どの候補も floor 未満のため上位を採用)"
                )
            for c, d in zip(candidates, decisions, strict=True):
                if self._decide(d, f"query: {c.text}").outcome == "accept":
                    kept.append(c)
        return kept

    async def _fetch(self, queries: list[QueryCandidate]) -> list[SourceItem]:
        sources: dict[str, SourceItem] = {}
        adapters: dict[AdapterKind, Adapter] = {}
        for q in queries:
            adapter = adapters.setdefault(q.adapter, make_adapter(q.adapter, pacing=self.pacing))
            out = await collect(
                adapter,
                self.http,
                self.partition,
                self.ctx.line,
                q.text,
                now=self.now,
                env=self.env,
            )
            if out.failure is not None:
                self.st.notes.append(
                    f"{q.adapter}: fetch 失敗 ({out.failure.reason} {out.failure.detail})"
                )
            if out.skipped:
                self.st.notes.append(f"{q.adapter}: 検証落ちで {out.skipped} 件 skip")
            sources.update((s.id, s) for s in out.sources)
        return list(sources.values())

    async def _screen(self, sources: list[SourceItem]) -> list[SourceItem]:
        """relevance_triage then source_trust; only sources passing both are cut into units."""
        kept: list[SourceItem] = []
        for s in sources:
            if self._over_budget():
                break
            tri = self._decide(
                relevance_triage.decision(
                    await relevance_triage.judge(self.jev, self.ctx, s, now=self.now)
                ),
                s.title,
            )
            if tri.outcome != "accept":
                continue
            trust = self._decide(
                source_trust.decision(await source_trust.judge(self.jev, s, now=self.now)), s.title
            )
            if trust.outcome == "accept":
                kept.append(s)
        return kept

    async def _claims(self, sources: list[SourceItem]) -> list[tuple[Claim, SourceItem]]:
        out: list[tuple[Claim, SourceItem]] = []
        for s in sources:
            for u in split_units(s):
                if self._over_budget():
                    return out
                self.st.nodes.append(u)
                self.st.units[u.id] = u
                d = self._decide(
                    claim_detection.decision(
                        await claim_detection.judge(self.jev, self.ctx, u, s, now=self.now)
                    ),
                    u.text,
                )
                if d.outcome == "accept":
                    out.append((Claim.from_unit(u, line=self.ctx.line.id), s))
        return out

    async def _novel(
        self, claims: list[tuple[Claim, SourceItem]]
    ) -> list[tuple[Claim, SourceItem]]:
        # "Stored" = claims reported on an EARLIER day. Today's own report (a same-day re-run)
        # is neither a duplicate source nor a novelty reference — otherwise a re-run would
        # empty today's report.
        earlier = {
            c
            for n in self.known.values()
            if isinstance(n, Report) and n.line == self.ctx.line.id and n.run_date < self.now.date()
            for c in n.claims
        }
        stored = {i: n for i, n in self.known.items() if isinstance(n, Claim) and i in earlier}
        index = ClaimIndex.rebuild(self.index_path, self.partition)
        kept: list[tuple[Claim, SourceItem]] = []
        for claim, src in claims:
            if claim.id in stored or self._over_budget():
                continue  # reported on an earlier day, or no budget left to check it
            candidates = [i for i in novelty.candidate_pairs(index, claim) if i in stored]
            self.st.similar[claim.id] = [stored[i].text for i in candidates]
            pair_decisions = [
                self._decide(
                    novelty.decision(await novelty.judge(self.jev, claim, stored[i], now=self.now)),
                    claim.text,
                )
                for i in candidates
            ]
            verdict = novelty.verdict(pair_decisions)
            if verdict == "novel":
                kept.append((claim, src))
            elif verdict == "unjudged":
                self.st.unjudged[claim.id] = claim.text
        return kept

    async def _order(
        self, claims: list[tuple[Claim, SourceItem]]
    ) -> list[tuple[Claim, SourceItem]]:
        by_id = {c.id: (c, s) for c, s in claims}
        decisions: list[Decision] = []
        for c, s in claims:
            if self._over_budget():
                del by_id[c.id]
                continue
            support = await source_support.check(self.jev, c, s, now=self.now)
            if support.decision is not None:
                self._decide(support.decision, c.text)
            if support.verdict in ("contradicts", "says_nothing"):
                del by_id[c.id]
                continue
            decisions.append(
                self._decide(
                    report_ordering.decision(
                        await report_ordering.judge(self.jev, self.ctx, c, now=self.now)
                    ),
                    c.text,
                )
            )
        return [by_id[i] for i in report_ordering.order(decisions) if i in by_id]

    async def _render(self, report_id: str, ordered: list[tuple[Claim, SourceItem]]) -> Rendering:
        if not ordered or self._over_budget():
            return Rendering(rendering="template", prose=None, rubric=())
        done = self.known.get(report_id)
        if (
            isinstance(done, Report)
            and not done.partial
            and done.claims == tuple(c.id for c, _ in ordered)
        ):
            # Same claims as today's stored report: reuse its prose instead of re-generating.
            return Rendering(rendering=done.rendering, prose=done.prose, rubric=())
        rendering, drafts = await rubric_ladder(
            jev=self.jev,
            model=self.max,
            ctx=self.ctx,
            report_id=report_id,
            claims=[c.text for c, _ in ordered],
            meter=self.meters[MAX],
            now=self.now,
            timeout_s=prose_timeout_s(self.env),
        )
        self.st.decisions += list(rendering.rubric)
        self.st.nodes += drafts
        for i, attempt in enumerate(rendering.drafts, start=1):
            state = "生成" if attempt.prose else f"失敗 ({attempt.failure})"
            self.st.notes.append(f"prose 第{i}稿: {state} {attempt.seconds:.1f}s")
        return rendering

    async def _rubric_claims(
        self, report_id: str, rendering: Rendering, ordered: list[tuple[Claim, SourceItem]]
    ) -> None:
        """Dense labels (decision 5): every accepted claim scored in its report context."""
        for claim, src in ordered:
            if self._over_budget():
                return
            unit = self.st.units.get(claim.unit)
            span = (unit.start, unit.end) if unit is not None else None
            st = rubric_claim.state(
                self.ctx, claim, src, rendering.prose, self.st.similar.get(claim.id, []), span=span
            )
            result = await rubric_claim.judge(self.jev, report_id, claim, st, now=self.now)
            self._decide(rubric_claim.decision(result), claim.text)

    # --- run ----------------------------------------------------------------------------

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
            f"記入率 (前回): {fill:.2f}" if fill is not None else "記入率 (前回): なし",
            *(
                f"rubric {m.axis}: 平均 {m.mean_score:.2f} / gold 一致 "
                + (f"{m.gold_agreement:.2f}" if m.gold_agreement is not None else "未計測")
                if m.mean_score is not None
                else f"rubric {m.axis}: データなし"
                for m in meters
            ),
            *rule_candidates(log, RuleConfig(), today=self.now.date()),
        ]
        if self.st.partial:
            lines.append("partial: 費用上限に達したため以降の判定を省略")
        return ops, lines + self.st.notes

    async def execute(self) -> LineOutcome:
        report_id = Report.id_for(self.ctx.line.id, self.now.date())
        ordered: list[tuple[Claim, SourceItem]] = []
        if not self._over_budget():
            queries = await self._queries()
            sources = await self._fetch(queries)
            claims = await self._claims(await self._screen(sources))
            ordered = await self._order(await self._novel(claims))
        rendering = await self._render(report_id, ordered)
        await self._rubric_claims(report_id, rendering, ordered)
        ops, lines = self._operations(self.jev.fresh)
        report = build_report(
            line=self.ctx.line.id,
            run_date=self.now.date(),
            rendering=rendering,
            claims=tuple(c.id for c, _ in ordered),
            unjudged=tuple(i for i in self.st.unjudged if i not in {c.id for c, _ in ordered}),
            partial=self.st.partial,
            operations=ops,
        )
        self.partition.put(
            [*self.st.nodes, *self.jev.fresh, *self.st.decisions, *(c for c, _ in ordered), report]
        )
        text = render_report(
            report=report,
            ctx=self.ctx,
            claims=[ClaimEntry(claim=c, source_url=s.url) for c, s in ordered],
            unjudged=[self.st.unjudged[i] for i in report.unjudged],
            operations=lines,
        )
        return LineOutcome(
            report=report,
            note=write_note(self.vault, self.ctx.line.slug, self.now.date(), text),
            operations=lines,
        )


def fill_rate_previous(
    nodes: Mapping[str, GraphNodeType], line: str, now: AwareDatetime
) -> float | None:
    """Primary metric (decision 7): ticked / claims on the line's latest earlier report."""
    reports = [
        n
        for n in nodes.values()
        if isinstance(n, Report) and n.line == line and n.run_date < now.date()
    ]
    if not reports:
        return None
    last = max(reports, key=lambda r: r.run_date)
    if not last.claims:
        return None
    ticked = {n.claim for n in nodes.values() if isinstance(n, Label) and n.report == last.id}
    return len(ticked & set(last.claims)) / len(last.claims)
