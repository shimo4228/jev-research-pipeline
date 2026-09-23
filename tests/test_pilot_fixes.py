"""The fixes the first scratch runs asked for (docs/pilot-log.md, 2026-09-23)."""

import urllib.error
from datetime import datetime
from email.message import Message
from io import BytesIO
from zoneinfo import ZoneInfo

import httpx2
import pytest

from jev_research_pipeline.adapters import arxiv, canary, firehose, github, hf_papers
from jev_research_pipeline.adapters.routing import HostRoutedTransport, UrllibTransport
from jev_research_pipeline.pipeline import nets


def test_hf_daily_asks_for_yesterday_in_utc():
    """09:46 JST on 09-23 is 00:46 UTC on 09-23; HF accepts at most 09-22."""
    now = datetime(2026, 9, 23, 9, 46, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert firehose.hf_date(now) == "2026-09-22"


def test_keyword_budget_goes_round_robin_across_adapters():
    queries = [
        (arxiv.adapter(), "a1"),
        (arxiv.adapter(), "a2"),
        (hf_papers.adapter(), "h1"),
        (arxiv.adapter(), "a3"),
        (github.adapter(), "g1"),
    ]
    plan = nets.plan(
        nets.NetConfig(budgets={**nets.DEFAULT_BUDGETS, "keyword": 4}, exploration_share=0.0),
        hf_date="2026-09-22",
        keyword_queries=queries,
        positives=[],
        negatives=[],
        cited=[],
        topics=[],
    )
    assert [r.query for r in plan if r.net == "keyword"] == ["a1", "h1", "g1", "a2"]


def test_hf_daily_comes_before_the_arxiv_listing():
    plan = nets.plan(
        nets.NetConfig(),
        hf_date="2026-09-22",
        keyword_queries=[],
        positives=[],
        negatives=[],
        cited=[],
        topics=[],
    )
    firehose_kinds = [r.adapter.kind for r in plan if r.net == "firehose"]
    assert firehose_kinds == ["hf_papers", "arxiv"]


def test_canary_urls_pick_their_fetch():
    repo = canary.plan("https://github.com/scienthoon/jev-ood-calibration")
    assert repo is not None and repo[1] == "scienthoon/jev-ood-calibration"
    assert str(repo[0].build_request(repo[1], {}).url) == (
        "https://api.github.com/repos/scienthoon/jev-ood-calibration/readme"
    )
    paper = canary.plan("https://arxiv.org/abs/2609.01234v2")
    assert paper is not None and paper[1] == "2609.01234"
    assert paper[0].build_request(paper[1], {}).url.params["id_list"] == "2609.01234"
    page = canary.plan("https://pydantic.dev/docs/ai/models/typesafe/")
    assert page is not None and page[0].kind == "web_search"
    assert canary.plan("http://example.org/") is None


def test_a_canary_page_is_its_title_and_its_text_without_tags():
    body = (
        "<html><head><title>TypeSafe &amp; Jev</title><style>p{}</style></head>"
        "<body><script>x=1</script><p>Fields map to <b>questions</b>.</p></body></html>"
    )
    (draft,) = canary.page_parse("https://example.org/p", body)
    assert draft["title"] == "TypeSafe & Jev"
    assert draft["text"] == "TypeSafe & Jev Fields map to questions ."


class _FakeResponse:
    status = 200
    headers = Message()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return b"<feed/>"


async def test_urllib_transport_carries_status_and_body(monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []

    def urlopen(req: object, timeout: float) -> _FakeResponse:
        seen.append(getattr(req, "full_url", ""))
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = httpx2.AsyncClient(transport=UrllibTransport(timeout=5))
    r = await client.get("https://export.arxiv.org/api/query?search_query=all%3Ax")
    assert r.status_code == 200 and r.text == "<feed/>"
    assert seen == ["https://export.arxiv.org/api/query?search_query=all%3Ax"]


async def test_urllib_transport_turns_http_errors_into_responses(monkeypatch: pytest.MonkeyPatch):
    def urlopen(req: object, timeout: float) -> _FakeResponse:
        raise urllib.error.HTTPError("u", 406, "Not Acceptable", Message(), BytesIO(b""))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = httpx2.AsyncClient(transport=UrllibTransport(timeout=5))
    r = await client.get("https://export.arxiv.org/api/query")
    assert r.status_code == 406


async def test_only_the_listed_host_goes_around_httpx2(monkeypatch: pytest.MonkeyPatch):
    def urlopen(req: object, timeout: float) -> _FakeResponse:
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    async def other(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(204)

    transport = HostRoutedTransport(timeout=5, fallback=httpx2.MockTransport(other))
    client = httpx2.AsyncClient(transport=transport)
    assert (await client.get("https://export.arxiv.org/api/query")).status_code == 200
    assert (await client.get("https://rss.arxiv.org/rss/cs.AI")).status_code == 204


def test_a_folded_claim_names_the_citation_that_points_at_it_and_still_harvests():
    from jev_research_pipeline.report import ClaimEntry, harvest_text
    from jev_research_pipeline.report.markdown import claim_line

    from . import builders as b

    line = claim_line(
        ClaimEntry(claim=b.claim(), source_url="https://arxiv.org/abs/1", cite="agent-memory [2]")
    )
    assert line.startswith("- [ ] **agent-memory [2]** ")
    assert harvest_text(line.replace("- [ ]", "- [x]", 1)) == {b.claim().id: "correct"}
