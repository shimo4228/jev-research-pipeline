"""The production prefilter as the intake eval's judge (plan intake-eval, claim 3).

The judge is question_prefilter over the line's open questions of today, asked the way a run
asks it (question_prefilter.state, one source per request), so an answer is a Judgment with
the run's own @id. A source's answer comes, first that applies, from:
1. the store: the Judgment a run already made for this state (the id pins the function, the
   model, the state's hash and the bundle — measurement-discipline 7: a label is frozen with
   its inputs, and a changed question or text is another id, never a stale hit);
2. the bench: `<bench>/judgments/<slug>.jsonld`, what an earlier eval asked;
3. Jev, once, through run.StoredJev, and kept in the bench. Before anything is sent, the
   requests are priced high (core.estimated_tokens x JEV_USD_PER_INPUT_TOKEN); over the
   invocation's cap nothing is sent and BudgetExceeded says what it would cost. Without
   TYPESAFE_API_KEY nothing is sent: those sources stay unjudged and N_ot reads as a lower
   bound.

The noise floor (jitter): a seeded sample of sources the store has an answer for, asked again
with no store in front (core.JevClient), the stored and the new on_topic side by side per
question in `<bench>/jitter.jsonl`. The rows are |Δp| of identical states — apart from any
change on the service's side since the stored answer, which the rows cannot separate.
"""

import asyncio
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import httpx2
from pydantic import AwareDatetime, BaseModel

from jev_research_pipeline.jev import (
    Ask,
    JevClient,
    JevFailure,
    JevState,
    Judged,
    judged_of,
    question_prefilter,
)
from jev_research_pipeline.jev.core import BATCH_SUBJECT, JEV_MODEL, estimated_tokens
from jev_research_pipeline.model import GraphNodeType, Judgment, SourceItem
from jev_research_pipeline.pipeline.concurrency import jev_concurrency
from jev_research_pipeline.pipeline.run import StoredJev
from jev_research_pipeline.store import Partition, input_sha256

from .intake import LineSetup, Verdict, verdict_of

JEV_USD_PER_INPUT_TOKEN: Final = 42e-9
"""TypeSafe's price, $42 per billion input tokens (README, as-of 2026-10-07). Review when
TypeSafe changes its price or Jev's version."""
REQUEST_TOKENS: Final = 250
QUESTION_TOKENS: Final = 150
"""Input tokens a prefilter request carries beyond its state (the instructions, each
question's field description, the framing). Measured 2026-10-20 on jev, 3 questions, 1,390
requests: 1,599 input tokens each against 1,114 from the state alone, so 485 beyond it; 250 +
3 x 150 = 700 keeps the estimate above the bill."""
DEFAULT_MAX_USD: Final = 0.50
"""What one `jrp eval intake` may spend on Jev unless --max-usd says otherwise."""
JITTER_SOURCES: Final = 40
"""Sources re-asked for the noise floor when the bench has none (x the line's questions)."""
API_KEY_ENV: Final = "TYPESAFE_API_KEY"


class BudgetExceeded(RuntimeError):
    def __init__(self, estimate: float, cap: float, requests: int) -> None:
        super().__init__(
            f"Jev に {requests} 件を聞くと見積もり ${estimate:.4f} で、上限 ${cap:.2f} を超える "
            "(--max-usd で上げる)"
        )
        self.estimate = estimate
        self.cap = cap


def judgments_partition(bench: Path, slug: str) -> Partition:
    return Partition(bench / "judgments" / f"{slug}.jsonld")


def jitter_path(bench: Path) -> Path:
    return bench / "jitter.jsonl"


def _probabilities(judged: Judged[BaseModel], n: int) -> list[float]:
    return [float(getattr(judged.output, question_prefilter.field(i))) for i in range(n)]


@dataclass
class Spend:
    """What the invocation asked of Jev, across lines."""

    cap: float
    estimate: float = 0.0
    requests: int = 0
    input_tokens: int = 0
    failed: int = 0

    @property
    def usd(self) -> float:
        """The price of the input tokens Jev reported."""
        return self.input_tokens * JEV_USD_PER_INPUT_TOKEN


@dataclass
class Judge:
    setup: LineSetup
    known: dict[str, GraphNodeType]
    """The store's nodes and the bench's judgments (asked ones are added)."""
    root: Path
    """The bench folder (judgments/, jitter.jsonl)."""
    spend: Spend
    http: httpx2.AsyncClient | None = None
    api_key: str | None = None
    asked: list[Judgment] = field(default_factory=list[Judgment])

    @property
    def bench(self) -> Partition:
        return judgments_partition(self.root, self.setup.slug)

    @property
    def ask(self) -> Ask[BaseModel]:
        return question_prefilter.ask(len(self.setup.questions))

    def state(self, source: SourceItem) -> JevState:
        return question_prefilter.state(self.setup.ctx, source, self.setup.questions)

    def stored(self, source: SourceItem) -> Judged[BaseModel] | None:
        """The answer the store or the bench holds for this state (run.StoredJev's lookup)."""
        ask = self.ask
        digest = input_sha256(self.state(source))
        for bundle in (ask.sha256, ask.batched(BATCH_SUBJECT).sha256):
            jid = Judgment.id_for(ask.function, (source.id,), JEV_MODEL, digest, bundle)
            hit = self.known.get(jid)
            if isinstance(hit, Judgment):
                judged = judged_of(ask, hit, subject=BATCH_SUBJECT)
                if judged is not None:
                    return judged
        return None

    def estimate(self, sources: Sequence[SourceItem]) -> float:
        """High: the state (core.estimated_tokens) plus what a request carries besides it."""
        overhead = REQUEST_TOKENS + QUESTION_TOKENS * len(self.setup.questions)
        tokens = sum(estimated_tokens(self.state(s)) + overhead for s in sources)
        return tokens * JEV_USD_PER_INPUT_TOKEN

    async def verdicts(
        self, sources: Sequence[SourceItem], *, now: AwareDatetime
    ) -> dict[str, Verdict]:
        """A Verdict per source that has or gets an answer (module docstring)."""
        n = len(self.setup.questions)
        out: dict[str, Verdict] = {}
        missing: list[SourceItem] = []
        for s in dict.fromkeys(sources):
            judged = self.stored(s)
            if judged is None:
                missing.append(s)
            else:
                out[s.id] = verdict_of(_probabilities(judged, n))
        if not missing or self.http is None or self.api_key is None:
            return out
        estimate = self.estimate(missing)
        if self.spend.estimate + estimate > self.spend.cap:
            raise BudgetExceeded(self.spend.estimate + estimate, self.spend.cap, len(missing))
        self.spend.estimate += estimate
        jev = StoredJev(self.http, api_key=self.api_key, known=self.known)
        gate = asyncio.Semaphore(jev_concurrency({}))
        ask = self.ask

        async def one(s: SourceItem) -> Judged[BaseModel] | JevFailure:
            async with gate:
                return await jev.judge(ask, (s.id,), self.state(s), now=now)

        results = await asyncio.gather(*(one(s) for s in missing))
        self.spend.requests += len(missing)
        self.spend.input_tokens += jev.input_tokens
        for s, result in zip(missing, results, strict=True):
            if isinstance(result, JevFailure):
                self.spend.failed += 1
                continue
            out[s.id] = verdict_of(_probabilities(result, n), fresh=True)
        self.asked += jev.fresh
        if jev.fresh:
            self.bench.put(jev.fresh)
        return out


@dataclass(frozen=True)
class JitterRow:
    line: str
    source: str
    question: int
    p_stored: float
    p_again: float
    asked_at: str

    @property
    def delta(self) -> float:
        return abs(self.p_again - self.p_stored)

    @property
    def flipped(self) -> bool:
        cut = question_prefilter.THRESHOLDS[0].value
        return (self.p_stored >= cut) != (self.p_again >= cut)


def read_jitter(bench: Path) -> list[JitterRow]:
    path = jitter_path(bench)
    if not path.is_file():
        return []
    rows: list[JitterRow] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            rows.append(JitterRow(**json.loads(raw)))
    return rows


async def measure_jitter(
    judge: Judge, sources: Sequence[SourceItem], *, n: int, seed: str, now: AwareDatetime
) -> list[JitterRow]:
    """Re-ask `n` of `sources` that have a stored answer, seeded; append the rows."""
    if judge.http is None or judge.api_key is None:
        return []
    stored = [(s, j) for s in sources if (j := judge.stored(s)) is not None]
    stored.sort(key=lambda pair: pair[0].id)
    sample = random.Random(seed).sample(stored, min(n, len(stored)))
    if not sample:
        return []
    estimate = judge.estimate([s for s, _ in sample])
    if judge.spend.estimate + estimate > judge.spend.cap:
        raise BudgetExceeded(judge.spend.estimate + estimate, judge.spend.cap, len(sample))
    judge.spend.estimate += estimate
    client = JevClient(judge.http, api_key=judge.api_key)
    gate = asyncio.Semaphore(jev_concurrency({}))
    ask = judge.ask
    q = len(judge.setup.questions)

    async def one(s: SourceItem) -> Judged[BaseModel] | JevFailure:
        async with gate:
            return await client.judge(ask, (s.id,), judge.state(s), now=now)

    again = await asyncio.gather(*(one(s) for s, _ in sample))
    judge.spend.requests += len(sample)
    judge.spend.input_tokens += client.input_tokens
    rows: list[JitterRow] = []
    for (s, before), after in zip(sample, again, strict=True):
        if isinstance(after, JevFailure):
            judge.spend.failed += 1
            continue
        for i, (p0, p1) in enumerate(
            zip(_probabilities(before, q), _probabilities(after, q), strict=True)
        ):
            rows.append(JitterRow(judge.setup.slug, s.id, i, p0, p1, now.isoformat()))
    path = jitter_path(judge.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row.__dict__, ensure_ascii=False, sort_keys=True) + "\n")
    return rows
