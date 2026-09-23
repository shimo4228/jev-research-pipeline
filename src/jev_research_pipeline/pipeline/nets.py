"""Discovery nets: what the pipeline searches, in a code-fixed order (packet "Discovery").

    firehose → recommendation → citation → keyword → exploration

Keyword search alone is exploitation and converges — one Opus explorer hit 37% single
theme in 30 days, and keyword-only recall is measured under 20% against citation
traversal's 80%+. So the keyword net is demoted to fourth and three code-owned nets run
before it, each with its own per-run request budget from config.toml. The model never
chooses where to search; it only screens what comes back.

- firehose: today's arXiv announcements in fixed categories + HF daily papers. No query.
- recommendation: Semantic Scholar, positives = the author's ⭕ and the papers behind
  accepted claims, negatives = ❌ plus seeded random negatives (Scholar Inbox's recipe
  against collapse). Best-effort: the keyless pool answers 429 and the net goes quiet.
- citation: OpenAlex forward citations of papers this line already accepted.
- keyword: the Qwen queries scored per question (the original net).
- exploration: a fixed share of the run spent on a topic *next to* the line's own, so
  bridges_line has something outside the vocabulary to find.

Budgets are request counts, not result counts: a net that is cheap to ask is asked more
often. The OpenAlex credit cap is a daily budget (keyless: 1,000 credits, $0.10, reset at
midnight UTC), counted from the response headers.
"""

import random
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

import httpx2
from pydantic import AwareDatetime, JsonValue

from jev_research_pipeline.adapters import (
    Adapter,
    FetchOutcome,
    collect,
    firehose,
    openalex,
    semantic_scholar,
)
from jev_research_pipeline.model import DiscoveryNet, Line, SourceItem
from jev_research_pipeline.store import Partition

NET_ORDER: Final[tuple[DiscoveryNet, ...]] = (
    "firehose",
    "recommendation",
    "citation",
    "keyword",
    "exploration",
)
DEFAULT_BUDGETS: Final[dict[DiscoveryNet, int]] = {
    "firehose": 2,
    "recommendation": 1,
    "citation": 3,
    "keyword": 6,
    "exploration": 1,
}
DEFAULT_EXPLORATION_SHARE: Final = 0.2
DEFAULT_CREDIT_CAP: Final = 400
"""Requests we allow ourselves against OpenAlex per day; keyless buys 1,000 credits."""
RANDOM_NEGATIVES: Final = 5
"""Seeded random negatives, so the recommender has something to move away from even
before the author has ticked a ❌ (Scholar Inbox: random negatives prevent collapse)."""


DEFAULT_FIREHOSE_MAX: Final = 300


@dataclass(frozen=True)
class NetConfig:
    budgets: Mapping[DiscoveryNet, int] = field(default_factory=lambda: dict(DEFAULT_BUDGETS))
    exploration_share: float = DEFAULT_EXPLORATION_SHARE
    categories: tuple[str, ...] = firehose.DEFAULT_CATEGORIES
    openalex_daily_credits: int = DEFAULT_CREDIT_CAP
    firehose_max: int = DEFAULT_FIREHOSE_MAX
    """Firehose sources kept per line-run, in feed order (the first pilot took 836)."""

    def budget(self, net: DiscoveryNet) -> int:
        return int(self.budgets.get(net, DEFAULT_BUDGETS.get(net, 0)))


def load_nets(config: Path) -> NetConfig:
    """`[nets]` of the daily-research config.toml; every key optional."""
    try:
        raw = tomllib.loads(config.read_text(encoding="utf-8")).get("nets", {})
    except (OSError, tomllib.TOMLDecodeError):
        return NetConfig()
    data = cast("dict[str, JsonValue]", raw if isinstance(raw, dict) else {})
    budgets = dict(DEFAULT_BUDGETS)
    for net in NET_ORDER:
        if isinstance(value := data.get(net), int):
            budgets[net] = max(0, value)
    share = data.get("exploration_share", DEFAULT_EXPLORATION_SHARE)
    raw_categories = data.get("arxiv_categories")
    categories = (
        tuple(str(c) for c in raw_categories)
        if isinstance(raw_categories, list)
        else firehose.DEFAULT_CATEGORIES
    )
    credits = data.get("openalex_daily_credits", DEFAULT_CREDIT_CAP)
    firehose_max = data.get("firehose_max", DEFAULT_FIREHOSE_MAX)
    return NetConfig(
        firehose_max=max(0, firehose_max)
        if isinstance(firehose_max, int)
        else DEFAULT_FIREHOSE_MAX,
        budgets=budgets,
        exploration_share=float(share)
        if isinstance(share, int | float)
        else DEFAULT_EXPLORATION_SHARE,
        categories=categories,
        openalex_daily_credits=int(credits) if isinstance(credits, int) else DEFAULT_CREDIT_CAP,
    )


@dataclass(frozen=True)
class NetRequest:
    """One fetch: which net asks, with which code-built query."""

    net: DiscoveryNet
    adapter: Adapter
    query: str


def arxiv_id_of(url: str) -> str | None:
    """The arXiv id in an abs/pdf URL, version stripped."""
    marker = "/abs/" if "/abs/" in url else ("/pdf/" if "/pdf/" in url else None)
    if marker is None:
        return None
    tail = url.split(marker, 1)[1].split("?", 1)[0].removesuffix(".pdf")
    return tail.split("v")[0] if tail else None


def paper_id(url: str) -> str | None:
    """A Semantic Scholar paper id for a source URL, or None when there is none to build.
    `ARXIV:<id>` is the documented path-parameter form; DOIs go through `DOI:`."""
    if (arxiv := arxiv_id_of(url)) is not None:
        return f"ARXIV:{arxiv}"
    if "doi.org/" in url:
        return "DOI:" + url.split("doi.org/", 1)[1]
    return None


def openalex_work(url: str) -> str | None:
    """The filter value for `cites:` — OpenAlex has no arXiv id filter, so an arXiv paper
    is addressed through its DataCite DOI (10.48550, ~2022 onward)."""
    if "openalex.org/" in url:
        return url.rsplit("/", 1)[-1]
    if "doi.org/" in url:
        return "doi:" + url.split("doi.org/", 1)[1]
    if (arxiv := arxiv_id_of(url)) is not None:
        return f"doi:10.48550/arXiv.{arxiv}"
    return None


def plan(
    config: NetConfig,
    *,
    hf_date: str,
    keyword_queries: Sequence[tuple[Adapter, str]],
    positives: Sequence[str],
    negatives: Sequence[str],
    cited: Sequence[str],
    topics: Sequence[str],
) -> list[NetRequest]:
    """Every request of one run, in net order and within each net's budget."""
    out: list[NetRequest] = []
    firehose_budget = config.budget("firehose")
    # HF daily first: its 50 are already curated, and the arXiv listing alone fills the
    # firehose cap (first pilot: 836), which left no room for HF on the first run.
    if firehose_budget > 1:
        out.append(NetRequest("firehose", firehose.hf_adapter(), hf_date))
    if firehose_budget:
        out.append(
            NetRequest(
                "firehose", firehose.arxiv_adapter(), firehose.categories_token(config.categories)
            )
        )
    if positives and config.budget("recommendation"):
        out.append(
            NetRequest(
                "recommendation",
                semantic_scholar.adapter(),
                semantic_scholar.token(list(positives), list(negatives)),
            )
        )
    for work in list(cited)[: config.budget("citation")]:
        out.append(NetRequest("citation", openalex.citation_adapter(), openalex.cites_token(work)))
    keyword_budget = _keyword_budget(config)
    for adapter, query in _round_robin(keyword_queries)[:keyword_budget]:
        out.append(NetRequest("keyword", adapter, query))
    for topic in list(topics)[: _exploration_budget(config)]:
        out.append(
            NetRequest("exploration", openalex.exploration_adapter(), openalex.topic_token(topic))
        )
    return out


def _round_robin(queries: Sequence[tuple[Adapter, str]]) -> list[tuple[Adapter, str]]:
    """One query per adapter kind in turn, each kind's own order kept: cut first-come, the
    keyword budget went to arXiv and HF and no GitHub query was ever sent (first scratch
    run, 2026-09-23 — the jev line's canaries are repositories)."""
    by_kind: dict[str, list[tuple[Adapter, str]]] = {}
    for pair in queries:
        by_kind.setdefault(pair[0].kind, []).append(pair)
    out: list[tuple[Adapter, str]] = []
    while any(by_kind.values()):
        for kind in list(by_kind):
            if by_kind[kind]:
                out.append(by_kind[kind].pop(0))
    return out


def _keyword_budget(config: NetConfig) -> int:
    """The keyword net gives up the exploration share of its own budget: exploration is
    paid for out of exploitation, or it never happens."""
    budget = config.budget("keyword")
    return max(1, round(budget * (1.0 - config.exploration_share))) if budget else 0


def _exploration_budget(config: NetConfig) -> int:
    """What exploitation gave up, capped by the exploration net's own budget — so raising
    the share moves requests from one net to the other instead of only shrinking keyword."""
    given_up = config.budget("keyword") - _keyword_budget(config)
    return min(config.budget("exploration"), given_up) if config.budget("exploration") else 0


def seeded_negatives(
    candidates: Sequence[str], *, seed: str, n: int = RANDOM_NEGATIVES
) -> list[str]:
    """Random negatives, drawn from a seed so a re-run asks the same thing."""
    pool = list(dict.fromkeys(candidates))
    rng = random.Random(seed)
    rng.shuffle(pool)
    return pool[:n]


@dataclass
class DayBudget:
    """What is spent against the shared, daily quotas — across every line of the rotation.

    One rotation runs several lines in one process against the same keyless pools, so a
    per-line counter would let three lines spend three times the daily cap and would ask
    the pool that just answered 429 twice more. `spent` is the OpenAlex credits used
    today; `quiet` are the nets that hit a rate limit and are done for the day.
    """

    date: str = ""
    spent: int = 0
    quiet: set[DiscoveryNet] = field(default_factory=set[DiscoveryNet])
    reported: set[str] = field(default_factory=set[str])
    """Notes already written once, so a cap is not reported per net per line."""

    def for_day(self, run_date: str) -> "DayBudget":
        """Reset at the day boundary; the quotas are daily."""
        if self.date != run_date:
            self.date, self.spent, self.quiet, self.reported = run_date, 0, set(), set()
        return self


@dataclass
class NetOutcome:
    sources: list[SourceItem] = field(default_factory=list[SourceItem])
    notes: list[str] = field(default_factory=list[str])
    per_net: dict[DiscoveryNet, int] = field(default_factory=dict[DiscoveryNet, int])
    topics: list[str] = field(default_factory=list[str])
    openalex_credits: int = 0


def _fetch_notes(request: NetRequest, out: FetchOutcome) -> list[str]:
    """Operations lines of one successful fetch: resends and dropped results."""
    where = f"{request.net}/{request.adapter.kind}"
    notes: list[str] = []
    if out.retried:
        notes.append(f"{where}: {out.retried} 回待って再送 (406 の波)")
    if out.skipped:
        notes.append(f"{where}: 検証落ちで {out.skipped} 件 skip")
    return notes


def _capped(fresh: list[SourceItem], cap: int, outcome: NetOutcome) -> list[SourceItem]:
    """The firehose's share of a line-run, in feed order (NetConfig.firehose_max)."""
    room = max(cap - outcome.per_net.get("firehose", 0), 0)
    if len(fresh) > room:
        outcome.notes.append(f"firehose: 上限 {cap} 件のため {len(fresh) - room} 件を省略")
    return fresh[:room]


async def fetch_nets(
    requests: Sequence[NetRequest],
    client: httpx2.AsyncClient,
    partition: Partition,
    line: Line,
    *,
    now: AwareDatetime,
    env: Mapping[str, str],
    config: NetConfig,
    day: DayBudget | None = None,
    on_sources: Callable[[list[SourceItem]], None] | None = None,
) -> NetOutcome:
    """Run the plan in order. A net that fails is a line in the operations section, never
    the end of the run: the next net still gets its turn. `day` carries the quotas that
    are shared across the rotation's lines; without one they are this call's alone.
    `on_sources` sees each request's new sources as soon as they are in, in plan order,
    so the caller can start judging them while the later (paced) requests still wait."""
    outcome = NetOutcome()
    budget = (day or DayBudget()).for_day(now.date().isoformat())
    seen: set[str] = set()
    for request in requests:
        if request.net in budget.quiet:
            continue
        if request.adapter.kind == "openalex" and budget.spent >= config.openalex_daily_credits:
            if "openalex_cap" not in budget.reported:
                budget.reported.add("openalex_cap")
                outcome.notes.append("openalex: 1 日の credit 上限に達したため以降を省略")
            budget.quiet.add(request.net)
            continue
        out = await collect(
            request.adapter, client, partition, line, request.query, now=now, env=env
        )
        if out.failure is not None:
            outcome.notes.append(
                f"{request.net}/{request.adapter.kind}: fetch 失敗 "
                f"({out.failure.reason} {out.failure.detail})"
            )
            if "rate_limit" in out.failure.detail:
                # A shared pool answering 429 is a policy signal, not a transient error:
                # the net is done for the day, for every line, not just this one.
                budget.quiet.add(request.net)
                outcome.notes.append(f"{request.net}: rate limit のため本日は打ち切り")
            continue
        outcome.notes += _fetch_notes(request, out)
        if request.adapter.kind == "openalex" and not out.cached:
            # A filtered list costs one credit (measured 2026-09-23 from
            # x-ratelimit-credits-used); the header itself is not visible here because
            # collect() returns parsed sources, not the response.
            budget.spent += 1
        fresh = [s for s in out.sources if s.id not in seen]
        if request.net == "firehose":
            fresh = _capped(fresh, config.firehose_max, outcome)
        seen.update(s.id for s in fresh)
        outcome.sources += fresh
        if on_sources is not None and fresh:
            on_sources(fresh)
        outcome.per_net[request.net] = outcome.per_net.get(request.net, 0) + len(fresh)
    outcome.openalex_credits = budget.spent
    return outcome
