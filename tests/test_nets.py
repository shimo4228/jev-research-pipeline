"""Discovery nets: a code-fixed order, per-net budgets, an exploration share, and the
meters that say which net is earning its keep."""

import json
from pathlib import Path

import httpx2
import pytest

from jev_research_pipeline.adapters import arxiv, firehose, hf_papers, openalex, semantic_scholar
from jev_research_pipeline.adapters.base import credits_used
from jev_research_pipeline.model import Claim, SourceItem, Unit
from jev_research_pipeline.pipeline import meters, nets
from jev_research_pipeline.store import GraphStore

from . import builders as b
from .conftest import ClientFactory
from .fakes import (
    ARXIV_RSS,
    E2E_ABSTRACT,
    OPENALEX_ARXIV_SEARCH,
    OPENALEX_WORKS,
    S2_RECOMMENDATIONS,
)

KEYWORD = [(hf_papers.adapter(), "agent memory")] * 6


DEFAULTS = nets.NetConfig()


def _plan(config: nets.NetConfig = DEFAULTS) -> list[nets.NetRequest]:
    return nets.plan(
        config,
        hf_date="2026-09-22",
        keyword_queries=KEYWORD,
        positives=["ARXIV:2609.01234"],
        negatives=["ARXIV:2609.00009"],
        cited=["doi:10.48550/arXiv.2609.01234", "W2", "W3", "W4"],
        topics=["T10017"],
    )


def test_nets_run_in_the_code_fixed_order():
    assert [r.net for r in _plan()] == [
        "firehose",
        "firehose",
        "recommendation",
        "citation",
        "citation",
        "citation",
        # the default keyword budget (12) less the exploration share (20%) = 10
        *["keyword"] * min(len(KEYWORD), 10),
        "exploration",
    ]


def test_each_net_is_capped_by_its_budget():
    config = nets.NetConfig(budgets={**nets.DEFAULT_BUDGETS, "citation": 1, "keyword": 2})
    counts: dict[str, int] = {}
    for request in _plan(config):
        counts[request.net] = counts.get(request.net, 0) + 1
    assert counts["citation"] == 1
    assert counts["keyword"] == 2  # round(2 * 0.8) = 2


def test_the_exploration_share_comes_out_of_the_keyword_budget():
    wide = nets.NetConfig(budgets={**nets.DEFAULT_BUDGETS, "keyword": 10}, exploration_share=0.4)
    keyword = [r for r in _plan(wide) if r.net == "keyword"]
    assert len(keyword) == 6  # 10 * (1 - 0.4)


def test_a_net_with_no_budget_is_not_asked():
    silent = nets.NetConfig(budgets={**nets.DEFAULT_BUDGETS, "firehose": 0, "exploration": 0})
    assert {r.net for r in _plan(silent)} == {"recommendation", "citation", "keyword"}


def test_config_is_read_from_the_nets_table(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        "[nets]\nfirehose = 1\nkeyword = 4\nexploration_share = 0.5\n"
        'arxiv_categories = ["cs.AI"]\nopenalex_daily_credits = 50\n',
        encoding="utf-8",
    )
    loaded = nets.load_nets(config)
    assert loaded.budget("firehose") == 1
    assert loaded.categories == ("cs.AI",)
    assert loaded.exploration_share == 0.5
    assert loaded.openalex_daily_credits == 50
    assert loaded.budget("citation") == nets.DEFAULT_BUDGETS["citation"]  # untouched default


def test_missing_config_falls_back_to_the_defaults(tmp_path: Path):
    assert nets.load_nets(tmp_path / "nothing.toml").budgets == nets.DEFAULT_BUDGETS


def test_a_config_that_still_has_arxiv_keyword_max_loads(tmp_path: Path):
    # the cap arXiv's own rate limit asked for; arXiv search now goes through OpenAlex
    config = tmp_path / "config.toml"
    config.write_text("[nets]\narxiv_keyword_max = 1\nkeyword = 6\n", encoding="utf-8")
    loaded = nets.load_nets(config)
    assert loaded.budget("keyword") == 6
    assert not hasattr(loaded, "arxiv_keyword_max")


def test_the_openalex_cap_defaults_by_whether_there_is_a_key():
    assert nets.NetConfig().credit_cap({}) == nets.DEFAULT_CREDIT_CAP == 400
    assert nets.NetConfig().credit_cap({"OPENALEX_API_KEY": "k"}) == nets.KEYED_CREDIT_CAP == 4000
    # a configured cap wins either way
    assert nets.NetConfig(openalex_daily_credits=50).credit_cap({"OPENALEX_API_KEY": "k"}) == 50


@pytest.mark.parametrize(
    ("url", "paper", "work"),
    [
        (
            "https://arxiv.org/abs/2609.01234v1",
            "ARXIV:2609.01234",
            "doi:10.48550/arXiv.2609.01234",
        ),
        ("https://doi.org/10.1234/x", "DOI:10.1234/x", "doi:10.1234/x"),
        ("https://openalex.org/W99", None, "W99"),
        ("https://example.org/post", None, None),
    ],
)
def test_ids_are_built_from_the_url(url: str, paper: str | None, work: str | None):
    assert nets.paper_id(url) == paper
    assert nets.openalex_work(url) == work


def test_seeded_negatives_are_stable():
    pool = [f"ARXIV:26{i:04d}" for i in range(20)]
    first = nets.seeded_negatives(pool, seed="line")
    assert first == nets.seeded_negatives(pool, seed="line")
    assert first != nets.seeded_negatives(pool, seed="other line")
    assert len(first) == nets.RANDOM_NEGATIVES


# --- the adapters the nets use -----------------------------------------------------------


def test_arxiv_firehose_keeps_new_announcements_and_strips_the_preamble():
    drafts = firehose.arxiv_parse(ARXIV_RSS.format(abstract=E2E_ABSTRACT))
    assert [d["title"] for d in drafts] == ["Narrow Questions Beat Broad Prompts"]
    assert not drafts[0]["text"].startswith("arXiv:")
    assert "Announce Type" not in drafts[0]["text"]


def test_hf_daily_builds_the_paper_url():
    body = json.dumps(
        [{"paper": {"id": "2609.00004", "title": "t", "summary": "s", "publishedAt": "2026-09-22"}}]
    )
    (draft,) = firehose.hf_parse(body)
    assert draft["url"] == "https://huggingface.co/papers/2609.00004"
    assert draft["published_at"] is not None


def test_recommendations_post_carries_both_sides():
    request = semantic_scholar.build_request(semantic_scholar.token(["ARXIV:1"], ["ARXIV:2"]), {})
    assert request.method == "POST"
    assert json.loads(request.content) == {
        "positivePaperIds": ["ARXIV:1"],
        "negativePaperIds": ["ARXIV:2"],
    }


def test_recommendations_fall_back_to_the_arxiv_url():
    body = json.dumps(
        {"recommendedPapers": [{"title": "t", "abstract": "a", "externalIds": {"ArXiv": "2609.1"}}]}
    )
    (draft,) = semantic_scholar.parse(body)
    assert draft["url"] == "https://arxiv.org/abs/2609.1"


def test_openalex_reads_credits_and_topics():
    response = httpx2.Response(200, json=OPENALEX_WORKS, headers={"x-ratelimit-credits-used": "1"})
    assert credits_used(response) == 1
    assert credits_used(httpx2.Response(200)) is None
    body = json.dumps(OPENALEX_WORKS)
    assert openalex.topics_of(body) == ["T10017"]
    (draft,) = openalex.parse(body)
    assert draft["url"].startswith("https://doi.org/")
    assert "OpenAlex topic: T10017 Agent memory" in draft["text"]
    assert openalex.topic_of(draft["text"]) == "T10017"


# --- fetching: failures are lines, not the end of the run --------------------------------


async def _fetch(
    cassette: ClientFactory, handler: object, requests: list[nets.NetRequest], tmp_path: Path
) -> nets.NetOutcome:
    client = cassette(handler)  # pyright: ignore[reportArgumentType]
    partition = GraphStore(tmp_path).line("akc")
    return await nets.fetch_nets(
        requests,
        client,
        partition,
        b.line(),
        now=b.T0,
        env={},
        config=nets.NetConfig(openalex_daily_credits=1),
    )


async def test_a_rate_limited_net_goes_quiet_for_the_day(cassette: ClientFactory, tmp_path: Path):
    async def limited(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.semanticscholar.org":
            return httpx2.Response(429, json={"message": "Too Many Requests"})
        return httpx2.Response(200, json=S2_RECOMMENDATIONS)

    adapter = semantic_scholar.adapter()
    requests = [nets.NetRequest("recommendation", adapter, semantic_scholar.token(["A"], []))] * 2
    outcome = await _fetch(cassette, limited, requests, tmp_path)
    assert outcome.sources == []
    assert any("rate limit" in line for line in outcome.notes)


async def test_the_openalex_credit_cap_stops_the_citation_net(
    cassette: ClientFactory, tmp_path: Path
):
    async def works(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=OPENALEX_WORKS, headers={"x-ratelimit-credits-used": "1"})

    adapter = openalex.citation_adapter()
    requests = [
        nets.NetRequest("citation", adapter, openalex.cites_token("W1")),
        nets.NetRequest("citation", adapter, openalex.cites_token("W2")),
    ]
    outcome = await _fetch(cassette, works, requests, tmp_path)
    assert outcome.openalex_credits == 1  # the cap in _fetch is one credit
    assert any("credit 上限" in line for line in outcome.notes)
    assert outcome.per_net["citation"] == 1


CITED_DOI = "doi:10.48550/arXiv.2609.26217"
"""A paper the jev line had accepted, as `openalex_work` addresses it (2026-09-25 run)."""


async def _openalex_api(request: httpx2.Request) -> httpx2.Response:
    """OpenAlex as measured live on 2026-09-25: the singleton `works/doi:<doi>` resolves a
    DOI to its work (a DOI OpenAlex does not hold is a 404 page), and `cites:` takes only a
    work id — anything else is a 400."""
    if request.url.path == f"/works/{CITED_DOI}":
        return httpx2.Response(200, json={"id": "https://openalex.org/W7214088086"})
    if request.url.path == "/works/doi:10.48550/arXiv.2609.00429":
        return httpx2.Response(429, json={"message": "Rate limit exceeded"})
    if request.url.path.startswith("/works/"):
        return httpx2.Response(404, text="<title>404 Not Found</title>")
    value = request.url.params["filter"].removeprefix(openalex.CITES)
    if not value.startswith("W"):
        message = f"'{value}' is not a valid OpenAlex ID."
        return httpx2.Response(
            400, json={"error": "Invalid query parameters error.", "message": message}
        )
    return httpx2.Response(200, json=OPENALEX_WORKS, headers={"x-ratelimit-credits-used": "1"})


@pytest.mark.parametrize("work", ["doi:10.1000/a?b#c", "doi:10.1000/a\x01b"])
def test_the_lookup_keeps_the_whole_doi_in_the_path(work: str):
    # `?` and `#` are legal in a DOI and would cut it short; a control character from a
    # malformed stored URL made httpx2 raise InvalidURL, which is not a RequestError.
    request = openalex.lookup_request(work, {})
    assert request.url.path == f"/works/{work}"
    assert dict(request.url.params) == {"select": "id"}


def _citation(work: str) -> list[nets.NetRequest]:
    return [nets.NetRequest("citation", openalex.citation_adapter(), openalex.cites_token(work))]


async def test_a_cited_doi_is_resolved_to_a_work_id_before_the_cites_filter(
    cassette: ClientFactory, cassette_path: Path, tmp_path: Path
):
    # 2026-09-25 05:00: `cites:doi:10.48550/arXiv.…` answered 400 on the akc, edge and jev
    # lines, so the citation net never returned anything.
    outcome = await _fetch(cassette, _openalex_api, _citation(CITED_DOI), tmp_path)
    assert outcome.notes == []
    assert outcome.per_net["citation"] == 1
    sent = json.loads(cassette_path.read_text(encoding="utf-8"))
    assert any("filter=cites%3AW7214088086" in key for key in sent)


async def test_a_cited_paper_openalex_does_not_hold_is_skipped_with_a_line(
    cassette: ClientFactory, cassette_path: Path, tmp_path: Path
):
    work = "doi:10.48550/arXiv.2609.99999"
    outcome = await _fetch(cassette, _openalex_api, _citation(work), tmp_path)
    assert outcome.sources == []
    assert outcome.notes == [f"citation/openalex: {work} は OpenAlex 未収録のため省略"]
    sent = json.loads(cassette_path.read_text(encoding="utf-8"))
    assert not any("filter=" in key for key in sent)  # no cites request for it


async def test_a_rate_limited_lookup_quiets_the_citation_net(
    cassette: ClientFactory, tmp_path: Path
):
    requests = _citation("doi:10.48550/arXiv.2609.00429") + _citation(CITED_DOI)
    outcome = await _fetch(cassette, _openalex_api, requests, tmp_path)
    assert outcome.sources == []  # the second paper is not asked for once OpenAlex said 429
    assert "citation/openalex: rate limit のため本日は打ち切り" in outcome.notes


async def _openalex_everything(request: httpx2.Request) -> httpx2.Response:
    """OpenAlex answering both a `search=` (arXiv keyword) and a filtered list (citation)."""
    if "search" in request.url.params:
        return httpx2.Response(200, json=OPENALEX_ARXIV_SEARCH)
    return httpx2.Response(200, json=OPENALEX_WORKS)


def _arxiv_search(query: str = "agent memory") -> nets.NetRequest:
    return nets.NetRequest("keyword", arxiv.adapter(), query)


async def test_an_arxiv_search_spends_ten_credits_of_the_openalex_day(
    cassette: ClientFactory, tmp_path: Path
):
    # measured 2026-09-26: a `search=` costs 10 credits, a filtered list 1 (the replayed
    # cassette has no headers, so the adapters' declared costs are what is counted)
    requests = [_arxiv_search(), *_citation("W1")]
    outcome = await nets.fetch_nets(
        requests,
        cassette(_openalex_everything),
        GraphStore(tmp_path).line("akc"),
        b.line(),
        now=b.T0,
        env={},
        config=nets.NetConfig(),
    )
    assert outcome.openalex_credits == 11
    assert outcome.per_net == {"keyword": 2, "citation": 1}


async def test_the_openalex_credit_cap_holds_back_arxiv_search_too(
    cassette: ClientFactory, tmp_path: Path
):
    day = nets.DayBudget()
    outcome = await nets.fetch_nets(
        [_arxiv_search("agent memory"), _arxiv_search("agent recall"), *_citation("W1")],
        cassette(_openalex_everything),
        GraphStore(tmp_path).line("akc"),
        b.line(),
        now=b.T0,
        env={},
        config=nets.NetConfig(openalex_daily_credits=10),
        day=day,
    )
    assert day.spent == 10  # the first search; the second and the citation list wait
    assert outcome.notes == [
        "keyword/arxiv: 検証落ちで 1 件 skip",  # the work with no abstract
        "openalex: 1 日の credit 上限に達したため以降を省略",  # once, not per request
    ]
    assert "citation" not in outcome.per_net


async def test_a_rate_limited_arxiv_search_quiets_the_whole_openalex_pool(
    cassette: ClientFactory, cassette_path: Path, tmp_path: Path
):
    # citation, exploration and arXiv keyword search are one OpenAlex budget
    async def limited(request: httpx2.Request) -> httpx2.Response:
        if "search" in request.url.params:
            return httpx2.Response(429, json={"message": "Rate limit exceeded"})
        return httpx2.Response(200, json=OPENALEX_WORKS)

    outcome = await _fetch(cassette, limited, [_arxiv_search(), *_citation("W1")], tmp_path)
    assert "keyword/arxiv: rate limit のため本日は打ち切り" in outcome.notes
    assert outcome.per_net == {}
    sent = json.loads(cassette_path.read_text(encoding="utf-8"))
    assert not any("filter=cites" in key for key in sent)


# --- the firehose cap: by relevance to the line, not by feed order ------------------------


def _listed(title: str, text: str, n: int) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        net="firehose",
        url=f"https://arxiv.org/abs/2609.{n:05d}",
        title=title,
        text=text,
        fetched_at=b.T0,
    )


LISTING = [
    _listed("Protein folding at scale", "Diffusion models fold proteins.", 1),
    _listed("Galaxy surveys", "We count galaxies in deep fields.", 2),
    _listed("Verifying agent tool calls", "Agents check their tool calls before acting.", 3),
    _listed("Crop yield forecasting", "Satellite images predict harvests.", 4),
    _listed("Agent memory benchmarks", "A benchmark for long-term memory in agents.", 5),
]


def test_the_listing_is_ranked_by_bm25_and_ties_keep_feed_order():
    ranked = nets.ranked(LISTING, "agent verification tool calls memory")
    assert ranked is not None
    assert [s.title for s in ranked[:2]] == [
        "Verifying agent tool calls",
        "Agent memory benchmarks",
    ]
    # the three that match nothing tie at zero and stay in feed order
    assert [s.title for s in ranked[2:]] == [
        "Protein folding at scale",
        "Galaxy surveys",
        "Crop yield forecasting",
    ]
    assert nets.ranked(LISTING, "the of and") is None  # stopwords only: nothing to rank by
    assert nets.ranked(LISTING, "") is None


def test_an_overflowing_listing_keeps_the_most_relevant():
    outcome = nets.NetOutcome()
    kept = nets._capped(  # pyright: ignore[reportPrivateUsage]
        list(LISTING), 2, outcome, query="agent tool calls memory"
    )
    assert [s.title for s in kept] == ["Verifying agent tool calls", "Agent memory benchmarks"]
    assert outcome.notes == ["firehose: 関連度順に上位 2 件 (3 件を省略)"]


def test_without_query_text_the_cap_keeps_feed_order():
    outcome = nets.NetOutcome()
    kept = nets._capped(list(LISTING), 2, outcome)  # pyright: ignore[reportPrivateUsage]
    assert kept == LISTING[:2]
    assert outcome.notes == ["firehose: 上限 2 件のため 3 件を省略"]


async def test_hf_daily_is_cut_in_its_own_order_even_with_query_text(
    cassette: ClientFactory, tmp_path: Path
):
    # HF daily is already curated and goes first; only the arXiv listing is ranked
    async def daily(request: httpx2.Request) -> httpx2.Response:
        papers = [
            {"paper": {"id": "2609.00004", "title": "Galaxy surveys", "summary": E2E_ABSTRACT}},
            {"paper": {"id": "2609.00005", "title": "Narrow typed questions", "summary": "x y"}},
        ]
        return httpx2.Response(200, json=papers)

    outcome = await nets.fetch_nets(
        [nets.NetRequest("firehose", firehose.hf_adapter(), "2026-09-22")],
        cassette(daily),
        GraphStore(tmp_path).line("akc"),
        b.line(),
        now=b.T0,
        env={},
        config=nets.NetConfig(firehose_max=1),
        firehose_query="narrow typed questions",
    )
    assert [s.title for s in outcome.sources] == ["Galaxy surveys"]
    assert outcome.notes == ["firehose: 上限 1 件のため 1 件を省略"]


# --- meters -------------------------------------------------------------------------------


def _claim(net: str, text: str) -> tuple[Claim, Unit, SourceItem]:
    src = SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        net=net,  # pyright: ignore[reportArgumentType]
        url=f"https://arxiv.org/abs/{abs(hash(text)) % 10000}",
        title="t",
        text=f"{text} — OpenAlex topic: T{abs(hash(net)) % 100}",
        fetched_at=b.T0,
    )
    unit = Unit.cut(src, start=0, end=len(text), granularity="sentence")
    return Claim.from_unit(unit, line=b.LINE_IRI), unit, src


def test_accepted_share_per_net():
    made = [_claim("firehose", "a"), _claim("firehose", "b"), _claim("keyword", "c")]
    claims = [c for c, _, _ in made]
    units = {u.id: u for _, u, _ in made}
    sources = {s.id: s for _, _, s in made}
    shares = meters.share_per_net(claims, units, sources)
    assert shares == {"firehose": pytest.approx(2 / 3), "keyword": pytest.approx(1 / 3)}


def test_topic_clusters_count_distinct_topics():
    sources = [s for _, _, s in (_claim("firehose", "a"), _claim("keyword", "b"))]
    assert meters.topic_clusters(sources) == 2


def test_convergence_needs_enough_runs_and_rises_with_saturation():
    assert meters.convergence([3, 6]) is None
    slow = meters.convergence([5, 10, 15, 20])
    fast = meters.convergence([20, 24, 25, 25])
    assert slow is not None and fast is not None
    assert fast > slow  # a curve that flattened is further along


def test_consecutive_irrelevant_is_not_reported_as_convergence():
    # Repke 2026: a run of irrelevant results is not a stopping signal, so no meter line
    # may say it is. The only convergence line is the fitted one.
    lines = meters.lines(
        {"keyword": 0},
        {},
        clusters=1,
        previous_clusters=3,
        fit=None,
        openalex_credits=0,
    )
    assert any("収束推定 f: データ不足" in line for line in lines)
    assert not any("連続" in line for line in lines)
    assert any("減少" in line for line in lines)  # a falling cluster count is the alarm


def test_time_to_discovery_is_the_median_over_ticked_sources():
    from datetime import timedelta

    from jev_research_pipeline.model import Label

    made = [_claim("firehose", "a"), _claim("keyword", "b")]
    sources = {s.id: s for _, _, s in made}
    units = {u.id: u for _, u, _ in made}
    claims = {c.id: c for c, _, _ in made}
    labels = [
        Label.new(
            subject=made[0][2].id,
            report=b.report().id,
            verdict="correct",
            provenance="source",
            harvested_at=b.T0 + timedelta(days=2),
        ),
        Label.new(
            subject=made[1][0].id,  # a claim tick resolves to its source
            report=b.report().id,
            verdict="correct",
            provenance="claim",
            harvested_at=b.T0 + timedelta(days=4),
        ),
        Label.new(
            subject=made[1][2].id,
            report=b.report().id,
            verdict="incorrect",  # a ❌ is not a discovery
            provenance="source",
            harvested_at=b.T0 + timedelta(days=30),
        ),
    ]
    assert meters.time_to_discovery(labels, sources, claims, units) == pytest.approx(3.0)
    assert meters.time_to_discovery([], sources, claims, units) is None
