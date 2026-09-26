"""Discovery nets: what the pipeline searches, in a code-fixed order (packet "Discovery").

    firehose → recommendation → citation → keyword → exploration

Keyword search alone is exploitation and converges — one Opus explorer put 88 of its 238
past topics (37%) on a single theme, and keyword-only recall is measured under 20% against citation
traversal's 80%+. So the keyword net is demoted to fourth and three code-owned nets run
before it, each with its own per-run request budget from config.toml. The model never
chooses where to search; it only screens what comes back.

- firehose: today's arXiv announcements in fixed categories + HF daily papers. No query;
  when the arXiv listing overflows the cap, what is kept is ranked by BM25 against the
  line's own English query text (authored `arxiv:` / `hf:` / `github:` lines + the line
  vocabulary), not cut in feed order (~541 items on 2026-09-26, cap 300, and the
  prefilter rejects ~97% of arXiv items).
- recommendation: Semantic Scholar, positives = the author's `[x]` ticks and the papers
  behind accepted claims, negatives = `[-]` ticks plus seeded random negatives (Scholar Inbox's recipe
  against collapse). Best-effort: the keyless pool answers 429 and the net goes quiet.
- citation: OpenAlex forward citations of papers this line already accepted.
- keyword: each question's authored queries (`arxiv:` / `github:` / `hf:` / `web:` lines).
  `arxiv:` goes to OpenAlex search restricted to the arXiv source (adapters.arxiv): arXiv's
  own API refuses Python clients since 2026-09-24.
- exploration: a fixed share of the run spent on a topic *next to* the line's own, so
  bridges_line has something outside the vocabulary to find.

Budgets are request counts, not result counts: a net that is cheap to ask is asked more
often. The OpenAlex credit cap is a daily budget (keyless: 1,000 credits, $0.10; with a
key 10,000 and $1; reset at midnight UTC), counted from the response headers — a citation
or exploration list costs 1 credit, an arXiv keyword search 10.
"""

import random
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, cast

import bm25s  # pyright: ignore[reportMissingTypeStubs]
import httpx2
from pydantic import AwareDatetime, JsonValue

from jev_research_pipeline.adapters import (
    Adapter,
    FetchFailure,
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
    "keyword": 12,
    "exploration": 1,
}
"""keyword 6 -> 12 (scratch run 4, 2026-09-23): 5 keyword requests for 3 questions x 3
adapters left two lines with no source on topic at all; the firehose is broad by design,
so the targeted net carries the question-specific sources."""
DEFAULT_EXPLORATION_SHARE: Final = 0.2
DEFAULT_CREDIT_CAP: Final = 400
"""OpenAlex credits we allow ourselves per day without a key; keyless buys 1,000."""
KEYED_CREDIT_CAP: Final = 4000
"""The same with OPENALEX_API_KEY set; a key buys 10,000 (measured 2026-09-26)."""
OPENALEX: Final = "openalex"
"""DayBudget.quiet key of the OpenAlex pool itself: citation, exploration and arXiv keyword
search all draw on it, so a 429 on one of them is a 429 for all."""
RANDOM_NEGATIVES: Final = 5
"""Seeded random negatives, so the recommender has something to move away from even
before the author has ticked a ❌ (Scholar Inbox: random negatives prevent collapse)."""


DEFAULT_FIREHOSE_MAX: Final = 300


@dataclass(frozen=True)
class NetConfig:
    budgets: Mapping[DiscoveryNet, int] = field(default_factory=lambda: dict(DEFAULT_BUDGETS))
    exploration_share: float = DEFAULT_EXPLORATION_SHARE
    categories: tuple[str, ...] = firehose.DEFAULT_CATEGORIES
    openalex_daily_credits: int | None = None
    """None = the default for the environment (credit_cap)."""
    firehose_max: int = DEFAULT_FIREHOSE_MAX
    """Firehose sources kept per line-run (the first pilot took 836); the arXiv listing is
    ranked by relevance before the cut (fetch_nets)."""

    def budget(self, net: DiscoveryNet) -> int:
        return int(self.budgets.get(net, DEFAULT_BUDGETS.get(net, 0)))

    def credit_cap(self, env: Mapping[str, str]) -> int:
        """The configured cap, or the default for whether OPENALEX_API_KEY is set."""
        if self.openalex_daily_credits is not None:
            return self.openalex_daily_credits
        return KEYED_CREDIT_CAP if env.get(openalex.API_KEY_ENV) else DEFAULT_CREDIT_CAP


def load_nets(config: Path) -> NetConfig:
    """`[nets]` of the daily-research config.toml; every key optional. A key this version
    no longer reads (`arxiv_keyword_max`, the cap arXiv's own rate limit asked for) is
    ignored, so an older config still loads."""
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
    credits = data.get("openalex_daily_credits")
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
        openalex_daily_credits=max(0, credits) if isinstance(credits, int) else None,
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
    """How OpenAlex knows a cited paper: its work id, or a `doi:` that fetch_nets resolves
    to one before the `cites:` filter goes out (the filter takes only a work id). OpenAlex
    has no arXiv id filter, so an arXiv paper goes through its DataCite DOI (10.48550,
    ~2022 onward)."""
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
    quiet: set[str] = field(default_factory=set[str])
    """A net ("citation"), one source within a net ("keyword/github") or the OpenAlex pool
    (OPENALEX) that is done today."""
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
    """Operations lines of one successful fetch: dropped results."""
    if out.skipped:
        return [f"{_source_key(request)}: 検証落ちで {out.skipped} 件 skip"]
    return []


def _held_back(
    request: NetRequest,
    budget: DayBudget,
    outcome: NetOutcome,
    *,
    cap: int,
) -> bool:
    """Whether today's quotas keep this request from going out (quiet source, net or
    OpenAlex pool, the OpenAlex credit cap). The cap is reported once a day."""
    if request.net in budget.quiet or _source_key(request) in budget.quiet:
        return True
    if not request.adapter.credit_cost:
        return False
    if OPENALEX in budget.quiet:
        return True
    if budget.spent >= cap:
        if "openalex_cap" not in budget.reported:
            budget.reported.add("openalex_cap")
            outcome.notes.append("openalex: 1 日の credit 上限に達したため以降を省略")
        return True
    return False


def _source_key(request: NetRequest) -> str:
    return f"{request.net}/{request.adapter.kind}"


def _record_failure(
    request: NetRequest, failure: FetchFailure, budget: DayBudget, outcome: NetOutcome
) -> None:
    """A failed request is a line in the operations section, never the end of the run."""
    outcome.notes.append(f"{_source_key(request)}: fetch 失敗 ({failure.reason} {failure.detail})")
    if "rate_limit" in failure.detail:
        # A shared pool answering 429 is a policy signal, not a transient error: that
        # source is done for the day in this net, for every line. The net's other sources
        # are other pools (scratch run 5: one arXiv 429 had silenced GitHub and HF keyword
        # search for every line) — except OpenAlex, which is one pool behind three nets.
        budget.quiet.add(_source_key(request))
        if request.adapter.credit_cost:
            budget.quiet.add(OPENALEX)
        outcome.notes.append(f"{_source_key(request)}: rate limit のため本日は打ち切り")


async def _sendable(
    request: NetRequest,
    client: httpx2.AsyncClient,
    *,
    env: Mapping[str, str],
    budget: DayBudget,
    outcome: NetOutcome,
) -> NetRequest | None:
    """The request as it can go on the wire, or None when it cannot (the reason is an
    operations line). Only a citation request on a DOI changes: `cites:` takes nothing but
    an OpenAlex work id, so the DOI is looked up first (openalex.resolve_work)."""
    work = request.query.removeprefix(openalex.CITES)
    if request.net != "citation" or not work.startswith(openalex.DOI):
        return request
    found = await openalex.resolve_work(client, work, env=env)
    if isinstance(found, FetchFailure):
        _record_failure(request, found, budget, outcome)
        return None
    if found is None:
        outcome.notes.append(f"{_source_key(request)}: {work} は OpenAlex 未収録のため省略")
        return None
    return replace(request, query=openalex.cites_token(found))


def _tokens(texts: Sequence[str]) -> list[list[str]]:
    """Lower-cased words of two or more characters, English stopwords out (bm25s's own
    tokenizer, no stemmer: deterministic and dependency-free)."""
    tokenized = bm25s.tokenize(  # pyright: ignore[reportUnknownMemberType]
        list(texts), stopwords="en", return_ids=False, show_progress=False
    )
    return cast("list[list[str]]", tokenized)


def ranked(items: Sequence[SourceItem], query: str) -> list[SourceItem] | None:
    """`items` by BM25 of title + text against `query`, best first; ties keep their order
    (a stable sort). None when the query has no searchable word — the caller keeps the
    feed order."""
    (words,) = _tokens([query])
    if not words or not items:
        return None
    index = bm25s.BM25()
    index.index(  # pyright: ignore[reportUnknownMemberType]
        _tokens([f"{s.title} {s.text}" for s in items]), show_progress=False
    )
    scores = cast(
        "list[float]",
        index.get_scores(words).tolist(),  # pyright: ignore[reportUnknownMemberType]
    )
    order = sorted(range(len(items)), key=lambda i: -scores[i])
    return [items[i] for i in order]


def _capped(
    fresh: list[SourceItem], cap: int, outcome: NetOutcome, *, query: str = ""
) -> list[SourceItem]:
    """The firehose's share of a line-run (NetConfig.firehose_max). What overflows is cut
    by relevance to `query` when there is one (ranked), in feed order when not."""
    room = max(cap - outcome.per_net.get("firehose", 0), 0)
    if len(fresh) <= room:
        return fresh
    dropped = len(fresh) - room
    by_relevance = ranked(fresh, query) if room else None
    if by_relevance is not None:
        outcome.notes.append(f"firehose: 関連度順に上位 {room} 件 ({dropped} 件を省略)")
        return by_relevance[:room]
    outcome.notes.append(f"firehose: 上限 {cap} 件のため {dropped} 件を省略")
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
    firehose_query: str = "",
) -> NetOutcome:
    """Run the plan in order. A net that fails is a line in the operations section, never
    the end of the run: the next net still gets its turn. `day` carries the quotas that
    are shared across the rotation's lines; without one they are this call's alone.
    `on_sources` sees each request's new sources as soon as they are in, in plan order,
    so the caller can start judging them while the later (paced) requests still wait.
    `firehose_query` is the line's English query text the arXiv listing is ranked by when
    it overflows the firehose cap (HF daily keeps its place ahead: it is curated)."""
    outcome = NetOutcome()
    budget = (day or DayBudget()).for_day(now.date().isoformat())
    cap = config.credit_cap(env)
    seen: set[str] = set()
    for planned in requests:
        if _held_back(planned, budget, outcome, cap=cap):
            continue
        request = await _sendable(planned, client, env=env, budget=budget, outcome=outcome)
        if request is None:
            continue
        out = await collect(
            request.adapter, client, partition, line, request.query, now=now, env=env
        )
        if out.failure is not None:
            _record_failure(request, out.failure, budget, outcome)
            continue
        outcome.notes += _fetch_notes(request, out)
        budget.spent += out.credits  # 0 when cached: collect() sent nothing
        fresh = [s for s in out.sources if s.id not in seen]
        if request.net == "firehose":
            query = firehose_query if request.adapter.kind == "arxiv" else ""
            fresh = _capped(fresh, config.firehose_max, outcome, query=query)
        seen.update(s.id for s in fresh)
        outcome.sources += fresh
        if on_sources is not None and fresh:
            on_sources(fresh)
        outcome.per_net[request.net] = outcome.per_net.get(request.net, 0) + len(fresh)
    outcome.openalex_credits = budget.spent
    return outcome
