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
from .fakes import ARXIV_ATOM, GITHUB_SEARCH, HF_SEARCH, TAVILY_SEARCH, fake_json

NO_ENV: dict[str, str] = {}


def _ok(outcome: FetchOutcome) -> tuple[SourceItem, ...]:
    assert outcome.failure is None, outcome.failure
    assert all(s.line == b.LINE_IRI and s.adapter == outcome.adapter for s in outcome.sources)
    return outcome.sources


# --- arXiv ------------------------------------------------------------------------------


async def test_arxiv_parses_atom(cassette: ClientFactory):
    client = cassette(fake_json(ARXIV_ATOM, content_type="application/atom+xml"))
    out = await arxiv.adapter().fetch(client, b.line(), "narrow questions", now=b.T0, env=NO_ENV)
    first, second = _ok(out)
    assert first.url == "https://arxiv.org/abs/2609.01234v1"
    assert first.title == "Narrow Questions Beat Broad Prompts"  # whitespace collapsed
    assert (
        first.text == "We decompose judgment into narrow questions. Fitted weights raise accuracy."
    )
    assert first.published_at == date(2026, 9, 20)
    assert second.title == "Agent Memory Layers"


def test_arxiv_request_shape():
    req = arxiv.adapter().build_request("narrow questions", NO_ENV)
    assert req.url.host == "export.arxiv.org"
    assert req.url.params["search_query"] == "all:narrow AND all:questions"
    assert req.url.params["sortBy"] == "submittedDate"


async def test_arxiv_malformed_xml_is_a_parse_failure(cassette: ClientFactory):
    client = cassette(fake_json("<feed><entry>", content_type="application/atom+xml"))
    out = await arxiv.adapter().fetch(client, b.line(), "q", now=b.T0, env=NO_ENV)
    assert out.sources == ()
    assert out.failure is not None and out.failure.reason == "parse"


async def test_arxiv_rejects_xml_entity_expansion(cassette: ClientFactory):
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><feed>&a;</feed>'
    client = cassette(fake_json(bomb, content_type="application/atom+xml"))
    out = await arxiv.adapter().fetch(client, b.line(), "q", now=b.T0, env=NO_ENV)
    assert out.failure is not None and out.failure.reason == "parse"


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
    assert "authorization" not in github.adapter().build_request("q", NO_ENV).headers
    req = github.adapter().build_request("q", {"GITHUB_TOKEN": "t"})
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
    req = web_search.adapter().build_request("q", {"TAVILY_API_KEY": "secret-k"})
    assert req.headers["authorization"] == "Bearer secret-k"
    assert b"secret-k" not in req.content


# --- failures are records, not exceptions -----------------------------------------------


@pytest.mark.parametrize("status", [429, 500])
async def test_http_error_status_is_a_failure(cassette: ClientFactory, status: int):
    out = await hf_papers.adapter().fetch(
        cassette(fake_json({"error": "x"}, status=status)), b.line(), "q", now=b.T0, env=NO_ENV
    )
    assert out.failure is not None
    assert (out.failure.reason, out.failure.detail) == ("http_status", str(status))


async def test_wrong_json_shape_is_a_parse_failure(cassette: ClientFactory):
    out = await hf_papers.adapter().fetch(
        cassette(fake_json({"not": "a list"})), b.line(), "q", now=b.T0, env=NO_ENV
    )
    assert out.failure is not None and out.failure.reason == "parse"


def test_adapter_kinds_cover_line_adapters():
    kinds = {
        a.kind
        for a in (arxiv.adapter(), hf_papers.adapter(), github.adapter(), web_search.adapter())
    }
    assert kinds == {"arxiv", "hf_papers", "github", "web_search"}


def test_pacing_intervals_follow_published_limits():
    # arXiv ToU: 1 request / 3 s. GitHub search unauthenticated: 10/min. HF search: 50 / 5 min.
    assert arxiv.adapter().min_interval_s == 3.0
    assert github.adapter().min_interval_s == 6.0
    assert hf_papers.adapter().min_interval_s == 6.0


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
    assert [r.stage for r in records] == ["fetch_hf_papers"]

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
        "q",
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
        "q",
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
        cassette(fake_json(payload)), b.line(), "q", now=b.T0, env={"TAVILY_API_KEY": "k"}
    )
    assert [s.title for s in _ok(out)] == ["ok"]
    assert out.skipped == 2
