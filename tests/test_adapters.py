"""Typed source adapters: SourceItem.new outputs, failures recorded not raised, stage cache."""

from datetime import date
from pathlib import Path

import httpx2
import pytest

from jev_research_pipeline.adapters import (
    Adapter,
    FetchOutcome,
    arxiv,
    collect,
    github,
    hf_papers,
    web_search,
)
from jev_research_pipeline.model import SourceItem, StageRecord
from jev_research_pipeline.store import GraphStore

from . import builders as b
from .conftest import ClientFactory
from .fakes import GITHUB_SEARCH, HF_SEARCH, OPENALEX_ARXIV_SEARCH, TAVILY_SEARCH, fake_json

NO_ENV: dict[str, str] = {}
QUERY = "agent memory"
"""Any test query must survive query_text.clean_query — a 1-char one is now refused."""


def _ok(outcome: FetchOutcome) -> tuple[SourceItem, ...]:
    assert outcome.failure is None, outcome.failure
    assert all(s.line == b.LINE_IRI and s.adapter == outcome.adapter for s in outcome.sources)
    return outcome.sources


# --- arXiv (keyword search through OpenAlex) -------------------------------------------


async def test_arxiv_search_parses_openalex_works(cassette: ClientFactory):
    client = cassette(fake_json(OPENALEX_ARXIV_SEARCH))
    out = await arxiv.adapter().fetch(client, b.line(), "narrow questions", now=b.T0, env=NO_ENV)
    first, second = _ok(out)
    # the firehose's form (no version), so the same paper from both nets is one node
    assert first.url == "https://arxiv.org/abs/2609.01234"
    assert first.title == "Narrow Questions Beat Broad Prompts"  # whitespace collapsed
    assert (
        first.text == "We decompose judgment into narrow questions. Fitted weights raise accuracy."
    )
    assert first.published_at == date(2026, 9, 20)
    assert second.title == "Agent Memory Layers"
    assert out.skipped == 1  # the work with no abstract
    assert out.credits == arxiv.SEARCH_CREDITS  # a replayed cassette keeps no headers


def test_arxiv_search_request_shape():
    req = arxiv.adapter().build_request("narrow questions", NO_ENV)
    assert req.url.host == "api.openalex.org"
    assert req.url.path == "/works"
    assert req.url.params["search"] == "narrow questions"
    assert req.url.params["filter"] == "primary_location.source.id:S4306400194"
    assert req.url.params["sort"] == "publication_date:desc"
    assert req.url.params["per_page"] == "20"
    assert "abstract_inverted_index" in req.url.params["select"]
    assert "authorization" not in req.headers
    keyed = arxiv.adapter().build_request("narrow questions", {"OPENALEX_API_KEY": "k"})
    assert keyed.headers["authorization"] == "Bearer k"
    assert "k" not in keyed.url.params.values()  # the key stays out of the URL


@pytest.mark.parametrize(
    ("doi", "url"),
    [
        ("https://doi.org/10.48550/arxiv.2609.27287", "https://arxiv.org/abs/2609.27287"),
        ("https://doi.org/10.48550/arXiv.2609.27287", "https://arxiv.org/abs/2609.27287"),
        ("https://doi.org/10.1234/journal.5", ""),
        (None, ""),
    ],
)
def test_arxiv_url_comes_from_the_datacite_doi(doi: str | None, url: str):
    assert arxiv.abs_url(doi) == url


def test_the_inverted_abstract_is_put_back_in_order():
    index = {"agents": [1, 4], "Tool": [0], "call": [2], "and": [3]}
    assert arxiv.abstract(index) == "Tool agents call and agents"
    assert arxiv.abstract(None) == ""


async def test_arxiv_search_reads_the_credit_header():
    async def upstream(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json=OPENALEX_ARXIV_SEARCH, headers={"x-ratelimit-credits-used": "12"}
        )

    out = await arxiv.adapter().fetch(
        httpx2.AsyncClient(transport=httpx2.MockTransport(upstream)),
        b.line(),
        QUERY,
        now=b.T0,
        env=NO_ENV,
    )
    assert out.credits == 12


async def test_arxiv_search_wrong_shape_is_a_parse_failure(cassette: ClientFactory):
    client = cassette(fake_json({"results": "not a list"}))
    out = await arxiv.adapter().fetch(client, b.line(), QUERY, now=b.T0, env=NO_ENV)
    assert out.sources == ()
    assert out.failure is not None and out.failure.reason == "parse"


async def test_a_source_that_is_not_openalex_spends_no_credit(cassette: ClientFactory):
    out = await hf_papers.adapter().fetch(
        cassette(fake_json(HF_SEARCH)), b.line(), QUERY, now=b.T0, env=NO_ENV
    )
    assert out.credits == 0


# --- HF papers --------------------------------------------------------------------------


async def test_hf_papers_parses_search(cassette: ClientFactory):
    out = await hf_papers.adapter().fetch(
        cassette(fake_json(HF_SEARCH)), b.line(), "narrow questions", now=b.T0, env=NO_ENV
    )
    (paper,) = _ok(out)
    assert paper.url == "https://huggingface.co/papers/2609.01234"
    assert paper.text == "We decompose judgment into narrow questions."
    assert paper.published_at == date(2026, 9, 20)


# --- GitHub -----------------------------------------------------------------------------


async def test_github_parses_repos_and_skips_empty_descriptions(cassette: ClientFactory):
    out = await github.adapter().fetch(
        cassette(fake_json(GITHUB_SEARCH)), b.line(), "agent memory", now=b.T0, env=NO_ENV
    )
    (repo,) = _ok(out)
    assert repo.title == "someone/agent-memory"
    assert repo.text == "Episode log to knowledge store for LLM agents. Topics: llm, agents."
    assert repo.published_at == date(2026, 8, 1)


def test_github_token_is_optional_header():
    assert "authorization" not in github.adapter().build_request(QUERY, NO_ENV).headers
    req = github.adapter().build_request(QUERY, {"GITHUB_TOKEN": "t"})
    assert req.headers["authorization"] == "Bearer t"


# --- web search (Tavily) ----------------------------------------------------------------


async def test_web_search_without_key_is_skipped(cassette: ClientFactory):
    # No request is made (the cassette stays empty) and the skip is a recorded failure.
    out = await web_search.adapter().fetch(
        cassette(fake_json(TAVILY_SEARCH)), b.line(), "agent memory", now=b.T0, env=NO_ENV
    )
    assert out.sources == ()
    assert out.failure is not None and out.failure.reason == "missing_key"


async def test_web_search_parses_results(cassette: ClientFactory):
    out = await web_search.adapter().fetch(
        cassette(fake_json(TAVILY_SEARCH)),
        b.line(),
        "agent memory",
        now=b.T0,
        env={"TAVILY_API_KEY": "k"},
    )
    dated, undated = _ok(out)
    assert dated.published_at == date(2026, 9, 18)
    assert undated.published_at is None


def test_web_search_key_goes_in_header_not_body():
    req = web_search.adapter().build_request(QUERY, {"TAVILY_API_KEY": "secret-k"})
    assert req.headers["authorization"] == "Bearer secret-k"
    assert b"secret-k" not in req.content


# --- failures are records, not exceptions -----------------------------------------------


@pytest.mark.parametrize("status", [429, 500])
async def test_http_error_status_is_a_failure(cassette: ClientFactory, status: int):
    out = await hf_papers.adapter().fetch(
        cassette(fake_json({"error": "x"}, status=status)), b.line(), QUERY, now=b.T0, env=NO_ENV
    )
    assert out.failure is not None
    assert out.failure.reason == "http_status"
    assert out.failure.detail.startswith(str(status))


async def test_wrong_json_shape_is_a_parse_failure(cassette: ClientFactory):
    out = await hf_papers.adapter().fetch(
        cassette(fake_json({"not": "a list"})), b.line(), QUERY, now=b.T0, env=NO_ENV
    )
    assert out.failure is not None and out.failure.reason == "parse"


def test_adapter_kinds_cover_line_adapters():
    kinds = {
        a.kind
        for a in (arxiv.adapter(), hf_papers.adapter(), github.adapter(), web_search.adapter())
    }
    assert kinds == {"arxiv", "hf_papers", "github", "web_search"}


def test_pacing_intervals_follow_published_limits():
    # OpenAlex: 100 rps. GitHub search unauthenticated: 10/min. HF search: 50 / 5 min.
    assert arxiv.adapter().min_interval_s == 0.5
    assert github.adapter().min_interval_s == 6.0
    assert hf_papers.adapter().min_interval_s == 6.0


async def test_pacing_holds_across_adapter_instances():
    """The run builds a fresh adapter per keyword query, so a gap kept per instance let
    two arXiv requests go out back to back — the ToU interval is per source, not per object."""
    import time
    from dataclasses import replace

    sent: list[float] = []

    async def record(request: httpx2.Request) -> httpx2.Response:
        sent.append(time.monotonic())
        return httpx2.Response(200, json=OPENALEX_ARXIV_SEARCH)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    for _ in range(2):
        adapter = replace(arxiv.adapter(), min_interval_s=0.2)
        await adapter.fetch(http, b.line(), QUERY, now=b.T0, env=NO_ENV)
    assert sent[1] - sent[0] >= 0.2


# --- collect: stage cache around one fetch ----------------------------------------------


async def test_collect_stores_sources_and_skips_when_done(cassette: ClientFactory, tmp_path: Path):
    part = GraphStore(tmp_path).line("akc")
    adapter: Adapter = hf_papers.adapter()
    first = await collect(
        adapter,
        cassette(fake_json(HF_SEARCH)),
        part,
        b.line(),
        "narrow questions",
        now=b.T0,
        env=NO_ENV,
    )
    assert not first.cached
    ids = {s.id for s in first.sources}
    assert ids <= set(part.load())
    records = [n for n in part.load().values() if isinstance(n, StageRecord)]
    assert [r.stage for r in records] == ["fetch_keyword_hf_papers"]

    # Same (adapter, query, run date): no request at all — the empty replay cassette would miss.
    again = await collect(
        adapter,
        cassette(fake_json(HF_SEARCH)),
        part,
        b.line(),
        "narrow questions",
        now=b.T0,
        env=NO_ENV,
    )
    assert again.cached
    assert {s.id for s in again.sources} == ids


async def test_collect_does_not_cache_failures(cassette: ClientFactory, tmp_path: Path):
    part = GraphStore(tmp_path).line("akc")
    out = await collect(
        web_search.adapter(),
        cassette(fake_json(TAVILY_SEARCH)),
        part,
        b.line(),
        QUERY,
        now=b.T0,
        env=NO_ENV,
    )
    assert out.failure is not None
    assert part.load() == {}


async def test_body_decoding_error_is_a_failure(cassette: ClientFactory):
    # A corrupt Content-Encoding body raises httpx2.DecodingError (a RequestError that is
    # not a TransportError); it must still be a record, not an exception.
    async def corrupt(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"not gzip", headers={"content-encoding": "gzip"})

    out = await hf_papers.adapter().fetch(
        httpx2.AsyncClient(transport=httpx2.MockTransport(corrupt)),
        b.line(),
        QUERY,
        now=b.T0,
        env=NO_ENV,
    )
    assert out.failure is not None and out.failure.reason == "transport"


async def test_one_bad_result_is_skipped_not_fatal(cassette: ClientFactory):
    payload = {
        "results": [
            {"title": "ok", "url": "https://example.org/ok", "content": "Good text."},
            {"title": "empty", "url": "https://example.org/e", "content": ""},
            {"title": "bad url", "url": "javascript:alert(1)", "content": "x"},
        ]
    }
    out = await web_search.adapter().fetch(
        cassette(fake_json(payload)), b.line(), QUERY, now=b.T0, env={"TAVILY_API_KEY": "k"}
    )
    assert [s.title for s in _ok(out)] == ["ok"]
    assert out.skipped == 2


# --- first live run: GitHub 403 ------------------------------------------------------


def test_github_sends_a_descriptive_user_agent():
    headers = github.adapter().build_request(QUERY, NO_ENV).headers
    assert headers["user-agent"].startswith("jev-research-pipeline/")


@pytest.mark.parametrize(
    ("status", "body", "headers", "expected"),
    [
        (
            403,
            {"message": "API rate limit exceeded for 1.2.3.4."},
            {"x-ratelimit-remaining": "0"},
            "rate_limit",
        ),
        (
            403,
            {"message": "You have exceeded a secondary rate limit."},
            {"retry-after": "60"},
            "rate_limit",
        ),
        (403, {"message": "Bad credentials"}, {"x-ratelimit-remaining": "9"}, "forbidden"),
        (406, {"message": "not acceptable"}, {}, "not_acceptable"),
    ],
    ids=["primary", "secondary", "auth", "406"],
)
async def test_http_error_detail_explains_itself(
    cassette: ClientFactory,
    status: int,
    body: dict[str, str],
    headers: dict[str, str],
    expected: str,
):
    async def upstream(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body, headers=headers)

    out = await github.adapter().fetch(
        httpx2.AsyncClient(transport=httpx2.MockTransport(upstream)),
        b.line(),
        QUERY,
        now=b.T0,
        env=NO_ENV,
    )
    assert out.failure is not None
    assert out.failure.reason == "http_status"
    assert out.failure.detail.startswith(f"{status} {expected}")
    assert body["message"][:20] in out.failure.detail


@pytest.mark.parametrize("junk", [",", "]", "   ", "--", "<|end|>"])
async def test_adapter_refuses_a_query_with_no_searchable_text(cassette: ClientFactory, junk: str):
    # Deterministic guard behind the model-side validation (2026-09-23 live: arXiv 406).
    out = await arxiv.adapter().fetch(
        cassette(fake_json(OPENALEX_ARXIV_SEARCH)),
        b.line(),
        junk,
        now=b.T0,
        env=NO_ENV,
    )
    assert out.sources == ()
    assert out.failure is not None and out.failure.reason == "invalid_query"
