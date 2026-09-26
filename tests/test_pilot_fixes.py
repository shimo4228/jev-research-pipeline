"""The fixes the first scratch runs asked for (docs/pilot-log.md, 2026-09-23)."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2
import pytest

from jev_research_pipeline.adapters import Adapter, arxiv, canary, firehose, github, hf_papers
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
    request = paper[0].build_request(paper[1], {})
    assert request.url.host == "api.openalex.org"
    assert request.url.path == "/works/doi:10.48550/arXiv.2609.01234"
    assert "abstract_inverted_index" in request.url.params["select"]
    assert paper[0].credit_cost == 0  # a singleton lookup is free
    page = canary.plan("https://pydantic.dev/docs/ai/models/typesafe/")
    assert page is not None and page[0].kind == "web_search"
    assert canary.plan("http://example.org/") is None


async def test_an_arxiv_canary_openalex_has_not_indexed_is_a_line_not_a_crash():
    from . import builders as b

    async def not_yet(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, text="<title>404 Not Found</title>")

    got = await canary.fetch(
        httpx2.AsyncClient(transport=httpx2.MockTransport(not_yet)),
        b.line(),
        "https://arxiv.org/abs/2609.01234",
        now=b.T0,
        env={},
    )
    assert got == "OpenAlex 未収録 (索引待ち)"


async def test_an_arxiv_canary_comes_back_with_its_abstract():
    from . import builders as b
    from .fakes import inverted

    async def work(request: httpx2.Request) -> httpx2.Response:
        body = {
            "doi": "https://doi.org/10.48550/arxiv.2609.01234",
            "title": "Narrow Questions",
            "publication_date": "2026-09-20",
            "abstract_inverted_index": inverted("Typed questions beat prompts."),
        }
        return httpx2.Response(200, json=body)

    got = await canary.fetch(
        httpx2.AsyncClient(transport=httpx2.MockTransport(work)),
        b.line(),
        "https://arxiv.org/abs/2609.01234v2",
        now=b.T0,
        env={},
    )
    assert not isinstance(got, str)
    assert got.url == "https://arxiv.org/abs/2609.01234"
    assert got.text == "Typed questions beat prompts."


def test_an_arxiv_canary_waits_only_on_the_openalex_pool():
    from jev_research_pipeline.pipeline.run import (
        _canary_quiet,  # pyright: ignore[reportPrivateUsage]
    )

    assert _canary_quiet("arxiv", {nets.OPENALEX})
    assert not _canary_quiet("arxiv", {"firehose/arxiv"})  # the RSS is another host
    assert _canary_quiet("github", {"keyword/github"})


def test_the_firehose_is_ranked_by_the_english_query_lines_and_the_vocabulary():
    from jev_research_pipeline.pipeline.run import firehose_query

    from . import builders as b

    q = b.question()
    queries = {
        q.id: (
            ("arxiv", "agent memory"),
            ("github", "topic:llm-agents memory"),
            ("web", "エージェント 記憶"),
            ("hf_papers", "episodic recall"),
        )
    }
    got = firehose_query([q], queries, ["knowledge cycle"])  # pyright: ignore[reportArgumentType]
    assert got == "agent memory llm-agents memory episodic recall knowledge cycle"
    assert firehose_query([q], {}, []) == ""


def test_a_canary_page_is_its_title_and_its_text_without_tags():
    body = (
        "<html><head><title>TypeSafe &amp; Jev</title><style>p{}</style></head>"
        "<body><script>x=1</script><p>Fields map to <b>questions</b>.</p></body></html>"
    )
    (draft,) = canary.page_parse("https://example.org/p", body)
    assert draft["title"] == "TypeSafe & Jev"
    assert draft["text"] == "TypeSafe & Jev Fields map to questions ."


def test_a_folded_claim_names_the_citation_that_points_at_it_and_still_harvests():
    from jev_research_pipeline.report import ClaimEntry, harvest_text
    from jev_research_pipeline.report.markdown import claim_line

    from . import builders as b

    line = claim_line(
        ClaimEntry(claim=b.claim(), source_url="https://arxiv.org/abs/1", cite="agent-memory [2]")
    )
    assert line.startswith("- [ ] **agent-memory [2]** ")
    assert harvest_text(line.replace("- [ ]", "- [x]", 1)) == {b.claim().id: "correct"}


async def test_the_arxiv_listing_never_has_two_requests_in_flight():
    """arXiv ToU: one connection at a time — a slow answer holds the next request back."""
    import asyncio
    from dataclasses import replace

    from . import builders as b
    from .fakes import ARXIV_RSS, E2E_ABSTRACT

    open_now = 0
    peak = 0

    async def slow(request: httpx2.Request) -> httpx2.Response:
        nonlocal open_now, peak
        open_now += 1
        peak = max(peak, open_now)
        await asyncio.sleep(0.05)
        open_now -= 1
        return httpx2.Response(200, text=ARXIV_RSS.format(abstract=E2E_ABSTRACT))

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(slow))
    adapter = replace(firehose.arxiv_adapter(), min_interval_s=0.0)
    await asyncio.gather(
        *(adapter.fetch(client, b.line(), f"cs.AI+cs.CL{i}", now=b.T0, env={}) for i in range(3))
    )
    assert peak == 1


async def test_a_rate_limited_source_silences_only_itself(tmp_path: Path):
    from jev_research_pipeline.store import GraphStore

    from . import builders as b

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.openalex.org":
            return httpx2.Response(429, json={"message": "Rate limit exceeded"})
        return httpx2.Response(
            200, json={"total_count": 0, "incomplete_results": False, "items": []}
        )

    requests = [
        nets.NetRequest("keyword", arxiv.adapter(), "agent memory"),
        nets.NetRequest("keyword", arxiv.adapter(), "agent recall"),
        nets.NetRequest("keyword", github.adapter(), "agent memory"),
    ]
    requests = [nets.NetRequest(r.net, replace_interval(r.adapter), r.query) for r in requests]
    out = await nets.fetch_nets(
        requests,
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        GraphStore(tmp_path).line("akc"),
        b.line(),
        now=b.T0,
        env={},
        config=nets.NetConfig(),
    )
    assert "keyword/arxiv: rate limit のため本日は打ち切り" in out.notes
    # the second arXiv query is not sent at all (one failure line, not two)
    assert sum("fetch 失敗" in n for n in out.notes) == 1
    assert not any("keyword/github" in n for n in out.notes)  # GitHub still ran


def replace_interval(adapter: Adapter) -> Adapter:
    from dataclasses import replace

    return replace(adapter, min_interval_s=0.0)


def test_a_gist_ends_at_a_word_with_an_ellipsis():
    from jev_research_pipeline.pipeline import run

    gist = run._gist  # pyright: ignore[reportPrivateUsage]
    long = "DiscoverLLM learns what users want by letting a model interact with user " * 3
    cut = gist(long)
    assert cut.endswith("…") and len(cut) <= run.GIST_CHARS + 1
    assert not cut[:-1].endswith(" ")
    assert gist("short text") == "short text"


async def test_a_transient_jev_failure_is_sent_once_more(monkeypatch: pytest.MonkeyPatch):
    """Final run: a canary went "unjudged" over one failed request. One retry after the
    backoff, counted; a second failure stays unjudged."""
    from jev_research_pipeline.jev import JevClient, Judged, question_screening
    from jev_research_pipeline.jev import core as jev_core

    from . import builders as b
    from .fakes import fake_jev
    from .test_question_flow import CTX, _source  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(jev_core, "JEV_RETRY_BACKOFF_S", 0.0)
    ok = fake_jev()
    calls = 0

    async def flaky(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        if calls <= 3:  # the SDK's own three attempts all fail
            return httpx2.Response(503, json={"error": {"message": "busy"}})
        return await ok(request)

    jev = JevClient(httpx2.AsyncClient(transport=httpx2.MockTransport(flaky)), api_key="replay")
    source, question = _source(), b.question()
    state = question_screening.state(CTX, source, question, [])
    result = await jev.judge(question_screening.ASK, (source.id, question.id), state, now=b.T0)
    assert isinstance(result, Judged)
    assert jev.retries == 1
    assert jev.questions_asked == 2 * len(question_screening.ASK.output.model_fields)


def test_a_day_with_some_prose_is_not_a_template_day():
    """Scratch run 9: the last section fell to the template while an earlier one had prose,
    and Report refused rendering=template with prose set — the line failed."""
    from jev_research_pipeline.generation import Rendering
    from jev_research_pipeline.pipeline import run
    from jev_research_pipeline.report import QuestionSection

    joined = run._joined  # pyright: ignore[reportPrivateUsage]
    sections = [
        QuestionSection(question_id="q1", title="A", prose="本文 [1]。", evidence=()),
        QuestionSection(question_id="q2", title="B", prose=None, evidence=()),
    ]
    last = Rendering(rendering="template", prose=None, rubric=())
    out = joined(last, sections)
    assert out.rendering == "prose" and out.prose == "### A\n\n本文 [1]。"
    assert joined(last, [sections[1]]).rendering == "template"


def test_a_note_over_the_cap_drops_review_from_the_far_end_and_says_so():
    from jev_research_pipeline.pipeline import run
    from jev_research_pipeline.report import SourceEntry

    fitted = run._fitted  # pyright: ignore[reportPrivateUsage]
    review = [
        SourceEntry(source_id=f"s{i}", title="t", gist="g", url="https://example.org")
        for i in range(5)
    ]

    def rendered(ops: list[str]) -> str:
        # 4,000 bytes per remaining entry: fits once two entries are left
        return "x" * (4_000 * len(review)) + "\n".join(ops)

    text, ops = fitted(rendered, ["base"], review)
    assert len(text.encode()) <= run.NOTE_MAX_BYTES
    assert [e.source_id for e in review] == ["s0", "s1"]
    assert ops == ["base", "note 12 KB のため省略: Review 3 件"]
