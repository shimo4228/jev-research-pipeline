"""A degraded run is said out loud: the summary notification of a run that finished but
whose prose failed, whose writer was refused, whose Jev screen failed on a real share of
pairs, whose adapters failed, whose cost cap stopped a line, whose note has nothing to read
or whose prose cited nothing twice in a row says DEGRADED, one reason line per line, in one
Slack message (pipeline.health, pipeline.runner.run_summary). A keyless pool's rate limit is
expected and is not a reason (pipeline.nets)."""

import functools
from collections.abc import Callable, Coroutine
from datetime import date, timedelta
from pathlib import Path

import httpx2
import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.providers.openai_codex import CredentialsRefreshError

from jev_research_pipeline import note_text as t
from jev_research_pipeline.adapters import (
    arxiv,
    firehose,
    github,
    hf_papers,
    openalex,
    semantic_scholar,
)
from jev_research_pipeline.adapters.base import http_status_detail, http_status_kind
from jev_research_pipeline.generation import GenerationMeter, write_prose
from jev_research_pipeline.generation.claude_code import (
    ClaudeAuthError,
    ClaudeCodeError,
    parse_result,
)
from jev_research_pipeline.model import QuestionLog, Report
from jev_research_pipeline.pipeline import nets, run
from jev_research_pipeline.pipeline.health import UNJUDGED_SHARE, LineHealth
from jev_research_pipeline.pipeline.notify import NOTIFY_ENV, notify
from jev_research_pipeline.pipeline.run import LineOutcome
from jev_research_pipeline.pipeline.runner import run_summary

from . import builders as b
from .test_prose import CTX, QUESTION


def _raising(error: Exception) -> FunctionModel:
    async def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise error

    return FunctionModel(call)


@pytest.mark.parametrize(
    ("error", "auth"),
    [
        (CredentialsRefreshError("invalid_grant"), True),
        (ModelHTTPError(401, "gpt-6-luna", {"detail": "expired"}), True),
        (ModelHTTPError(403, "qwen3.7-max"), True),
        (ClaudeAuthError("claude error (status 401): Not logged in"), True),
        (ModelHTTPError(500, "gpt-6-luna"), False),
        (ModelHTTPError(429, "gpt-6-luna"), False),
        (ClaudeCodeError("claude timed out after 900 s"), False),
    ],
)
async def test_a_failed_draft_says_whether_the_writer_was_refused(error: Exception, auth: bool):
    result = await write_prose(
        _raising(error), CTX, QUESTION, ["c"], feedback=None, meter=GenerationMeter()
    )
    assert result.prose is None and result.failure is not None
    assert result.auth is auth


@pytest.mark.parametrize(
    "answer",
    [
        {"is_error": True, "api_error_status": 401, "result": "Invalid bearer token"},
        {"is_error": True, "result": "Not logged in · Please run /login"},
        {"is_error": True, "result": "Invalid API key · Please run /login"},
    ],
)
def test_a_signed_out_claude_cli_is_an_auth_error(answer: dict[str, object]):
    import json

    with pytest.raises(ClaudeAuthError):
        parse_result(json.dumps(answer).encode(), b"", 1)


def test_a_healthy_line_has_no_reason():
    assert LineHealth(drafts=2, failed_pairs=4, pairs=1400).reasons() == []


def test_each_degradation_is_one_reason():
    health = LineHealth(
        drafts=3,
        prose_failures=("ModelHTTPError: status_code: 500",),
        fetch_failures=("keyword/arxiv http_status", "keyword/arxiv http_status"),
        failed_pairs=70,
        pairs=1000,
        cost_capped=True,
    )
    reasons = health.reasons()
    assert reasons == [
        "prose failed 1/3 drafts (ModelHTTPError: status_code: 500)",
        "unjudged 70/1000 pairs (7%)",
        "fetch failed: keyword/arxiv http_status",
        "cost cap reached (partial note)",
    ]


def test_a_refused_writer_is_named_apart_from_a_failed_draft():
    health = LineHealth(
        drafts=2,
        prose_failures=("CredentialsRefreshError: invalid_grant",) * 2,
        writer_auth=True,
    )
    assert health.reasons()[0] == "writer auth failed — sign in again"


def test_the_unjudged_share_is_degraded_from_five_percent():
    assert UNJUDGED_SHARE == 0.05
    assert LineHealth(failed_pairs=49, pairs=1000).reasons() == []
    assert LineHealth(failed_pairs=50, pairs=1000).reasons() == ["unjudged 50/1000 pairs (5%)"]


def _outcome(tmp_path: Path, slug: str, claims: int, health: LineHealth) -> LineOutcome:
    report = b.report().model_copy(update={"claims": tuple(f"c{i}" for i in range(claims))})
    return LineOutcome(
        report=report,
        note=tmp_path / f"{report.run_date}_jrp_{slug}.md",
        operations=[],
        health=health,
    )


def test_a_clean_run_is_titled_as_before(tmp_path: Path):
    title, body = run_summary([_outcome(tmp_path, "akc", 3, LineHealth())], skipped=[], failed=[])
    assert title == "jrp run"
    assert body == f"{date(2026, 9, 22)} 2026-09-22_jrp_akc: 3 claims"


def test_a_degraded_line_titles_the_run_and_gets_one_line(tmp_path: Path):
    outcomes = [
        _outcome(tmp_path, "akc", 3, LineHealth()),
        _outcome(tmp_path, "jev", 0, LineHealth(cost_capped=True, failed_pairs=9, pairs=100)),
    ]
    title, body = run_summary(outcomes, skipped=["ans: 問い未設定 (q)"], failed=[])
    assert title == "jrp run DEGRADED"
    lines = body.splitlines()
    assert lines[0].endswith("2026-09-22_jrp_jev: 0 claims")
    assert lines[1] == (
        "DEGRADED 2026-09-22_jrp_jev: unjudged 9/100 pairs (9%); cost cap reached (partial note)"
    )
    assert lines[2] == "ans: 問い未設定 (q)"
    assert len(lines) == 3  # the healthy line gets no reason line


def test_a_line_that_raised_is_degraded_too(tmp_path: Path):
    title, body = run_summary(
        [_outcome(tmp_path, "akc", 3, LineHealth())],
        skipped=[],
        failed=["jev: 失敗 (RuntimeError: boom)"],
    )
    assert title == "jrp run DEGRADED"
    assert body.splitlines()[-1] == "jev: 失敗 (RuntimeError: boom)"


def test_the_cli_sends_one_degraded_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from jev_research_pipeline import cli

    outcomes = [_outcome(tmp_path, "akc", 0, LineHealth(drafts=1, prose_failures=("x: y",)))]

    async def fake_run(*args: object, **kwargs: object) -> list[LineOutcome]:
        return outcomes

    sent: list[list[str]] = []
    monkeypatch.setattr(cli, "run_pipeline", fake_run)
    monkeypatch.setattr(cli, "notify", functools.partial(notify, runner=sent.append))
    monkeypatch.setenv(NOTIFY_ENV, "1")
    assert cli.main(["run"]) == 0
    (cmd,) = sent
    assert cmd[2] == "jrp run DEGRADED"
    assert "DEGRADED 2026-09-22_jrp_akc: prose failed 1/1 drafts (x: y)" in cmd[3]


async def test_an_adapter_skipped_for_an_unset_key_is_not_a_fetch_failure(tmp_path: Path):
    from jev_research_pipeline.adapters import web_search
    from jev_research_pipeline.store import GraphStore

    async def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"sent {request.url}")

    out = await nets.fetch_nets(
        [nets.NetRequest("keyword", web_search.adapter(), "agent memory")],
        httpx2.AsyncClient(transport=httpx2.MockTransport(unreachable)),
        GraphStore(tmp_path).line("akc"),
        b.line(),
        now=b.T0,
        env={},
        config=nets.NetConfig(),
    )
    assert out.failures == []


# --- a keyless pool's rate limit is expected; a source with no key has no such excuse ----


type Handler = Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]]


def _limited(status: int = 429, headers: dict[str, str] | None = None) -> Handler:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"message": "Too Many Requests"}, headers=headers)

    return handler


async def _fetched(
    tmp_path: Path,
    request: nets.NetRequest,
    handler: Handler,
    env: dict[str, str],
    *,
    day: nets.DayBudget | None = None,
) -> nets.NetOutcome:
    from dataclasses import replace

    from jev_research_pipeline.store import GraphStore

    request = replace(request, adapter=replace(request.adapter, min_interval_s=0.0))
    return await nets.fetch_nets(
        [request],
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        GraphStore(tmp_path).line("akc"),
        b.line(),
        now=b.T0,
        env=env,
        config=nets.NetConfig(),
        day=day,
    )


def _s2() -> nets.NetRequest:
    return nets.NetRequest(
        "recommendation", semantic_scholar.adapter(), semantic_scholar.token(["A"], [])
    )


@pytest.mark.parametrize(
    ("env", "failures", "expected"),
    [
        ({}, [], ["recommendation/semantic_scholar http_status"]),
        (
            {semantic_scholar.API_KEY_ENV: "k"},
            ["recommendation/semantic_scholar http_status"],
            [],
        ),
    ],
)
async def test_a_keyless_rate_limit_is_expected_and_a_keyed_one_fails(
    tmp_path: Path, env: dict[str, str], failures: list[str], expected: list[str]
):
    out = await _fetched(tmp_path, _s2(), _limited(), env)
    assert out.failures == failures
    assert out.expected_limits == expected
    # keyed or keyless, the operations block says so and the source is done for the day
    assert out.rate_limited == ["recommendation/semantic_scholar"]
    assert "recommendation/semantic_scholar: rate limit のため本日は打ち切り" in out.notes
    health = LineHealth(fetch_failures=tuple(out.failures))
    assert health.reasons() == (
        ["fetch failed: recommendation/semantic_scholar http_status"] if failures else []
    )


@pytest.mark.parametrize(
    ("env", "failures", "expected"),
    [
        ({}, [], ["keyword/github http_status"]),
        ({github.TOKEN_ENV: "t"}, ["keyword/github http_status"], []),
    ],
)
async def test_a_spent_keyless_github_search_is_expected_too(
    tmp_path: Path, env: dict[str, str], failures: list[str], expected: list[str]
):
    # GitHub says a spent search budget with a 403 and x-ratelimit-remaining: 0
    spent = _limited(403, {"x-ratelimit-remaining": "0"})
    out = await _fetched(
        tmp_path, nets.NetRequest("keyword", github.adapter(), "agent memory"), spent, env
    )
    assert out.failures == failures
    assert out.expected_limits == expected


@pytest.mark.parametrize(
    ("env", "failures", "expected"),
    [
        ({}, [], ["firehose/hf_papers http_status"]),
        ({firehose.HF_TOKEN_ENV: "t"}, ["firehose/hf_papers http_status"], []),
    ],
)
async def test_a_keyless_hf_daily_rate_limit_is_expected_and_a_keyed_one_fails(
    tmp_path: Path, env: dict[str, str], failures: list[str], expected: list[str]
):
    # HF daily sends HF_TOKEN when it is set (firehose.hf_request), so unset it is the
    # shared keyless limit, like Semantic Scholar's
    request = nets.NetRequest("firehose", firehose.hf_adapter(), "2026-09-21")
    out = await _fetched(tmp_path, request, _limited(), env)
    assert out.failures == failures
    assert out.expected_limits == expected
    assert out.rate_limited == ["firehose/hf_papers"]


def test_the_key_hf_daily_names_is_the_key_it_sends():
    assert firehose.hf_adapter().key_env == firehose.HF_TOKEN_ENV
    sent = firehose.hf_request("2026-09-21", {firehose.HF_TOKEN_ENV: "t"})
    assert sent.headers["Authorization"] == "Bearer t"
    assert "Authorization" not in firehose.hf_request("2026-09-21", {}).headers


async def _says_rate_limit(request: httpx2.Request) -> httpx2.Response:
    """A 500 whose own message says rate_limit: its kind is error (http_status_detail)."""
    return httpx2.Response(500, json={"message": "upstream rate_limit store unreachable"})


async def test_a_keyless_failure_that_only_mentions_rate_limit_still_fails(tmp_path: Path):
    """Expected means the kind http_status_detail gave the status, not any "rate_limit" in
    the server's own message."""
    out = await _fetched(tmp_path, _s2(), _says_rate_limit, {})
    assert out.failures == ["recommendation/semantic_scholar http_status"]
    assert out.expected_limits == []
    health = LineHealth(fetch_failures=tuple(out.failures))
    assert health.reasons() == ["fetch failed: recommendation/semantic_scholar http_status"]


@pytest.mark.parametrize(
    ("handler", "limited"),
    [(_says_rate_limit, False), (_limited(), True)],
    ids=["500_saying_rate_limit", "429"],
)
async def test_only_a_rate_limit_status_stops_the_source_for_the_day(
    tmp_path: Path, handler: Handler, limited: bool
):
    """The quiet set, rate_limited and the RATE_LIMITED line follow the status kind, like the
    health (expected_limits): a keyless 500 whose message says rate_limit stops nothing."""
    source = "recommendation/semantic_scholar"
    day = nets.DayBudget()
    out = await _fetched(tmp_path, _s2(), handler, {}, day=day)
    stopped = t.RATE_LIMITED(out.lang, source=source)
    assert day.quiet == ({source} if limited else set())
    assert out.rate_limited == ([source] if limited else [])
    assert (stopped in out.notes) is limited
    assert out.expected_limits == ([f"{source} http_status"] if limited else [])


@pytest.mark.parametrize(
    ("status", "headers", "message", "kind"),
    [
        (429, {}, "Too Many Requests", "rate_limit"),
        (403, {"x-ratelimit-remaining": "0"}, "API rate limit exceeded", "rate_limit"),
        (403, {}, "rate_limit: you are not allowed", "forbidden"),
        (500, {}, "rate_limit", "error"),
        (406, {}, "", "not_acceptable"),
    ],
)
def test_the_status_kind_is_read_from_the_head_of_the_detail(
    status: int, headers: dict[str, str], message: str, kind: str
):
    response = httpx2.Response(status, json={"message": message}, headers=headers)
    assert http_status_kind(http_status_detail(response)) == kind


@pytest.mark.parametrize(
    "detail", ["", "rate_limit", "Too Many Requests: rate_limit", "429rate_limit: x", "ReadTimeout"]
)
def test_a_detail_without_a_status_head_has_no_kind(detail: str):
    assert http_status_kind(detail) is None


@pytest.mark.parametrize(
    "request_",
    [
        nets.NetRequest("keyword", hf_papers.adapter(), "agent memory"),
        nets.NetRequest("firehose", firehose.arxiv_adapter(), "cs.AI+cs.CL"),
    ],
    ids=["hf_papers", "arxiv_rss"],
)
async def test_a_rate_limit_on_a_source_with_no_key_is_a_failure(
    tmp_path: Path, request_: nets.NetRequest
):
    out = await _fetched(tmp_path, request_, _limited(), {})
    source = f"{request_.net}/{request_.adapter.kind}"
    assert out.failures == [f"{source} http_status"]
    assert out.expected_limits == []
    assert out.rate_limited == [source]  # quiet for the day, as before


async def test_a_keyless_source_that_errs_otherwise_still_fails(tmp_path: Path):
    request = nets.NetRequest("citation", openalex.citation_adapter(), openalex.cites_token("W1"))
    out = await _fetched(tmp_path, request, _limited(500), {})
    assert out.failures == ["citation/openalex http_status"]
    assert out.expected_limits == [] and out.rate_limited == []


def test_only_an_optional_key_makes_a_request_keyless():
    from jev_research_pipeline.adapters import web_search

    assert semantic_scholar.adapter().keyless({})
    assert not semantic_scholar.adapter().keyless({semantic_scholar.API_KEY_ENV: "k"})
    assert all(
        a.keyless({}) and a.key_env == openalex.API_KEY_ENV
        for a in (
            openalex.citation_adapter(),
            openalex.exploration_adapter(),
            arxiv.adapter(b.T0.date()),
            arxiv.paper_adapter(),
        )
    )
    assert github.adapter().key_env == github.TOKEN_ENV
    assert firehose.hf_adapter().keyless({})
    assert not firehose.hf_adapter().keyless({firehose.HF_TOKEN_ENV: "t"})
    # no key to set (HF papers search, the arXiv RSS), or a required one (Tavily: unset is
    # a skip)
    assert not any(
        a.keyless({})
        for a in (
            hf_papers.adapter(),
            firehose.arxiv_adapter(),
            web_search.adapter(),
        )
    )


# --- a quiet note: nothing to read, or nothing cited twice in a row -----------------------


def test_review_without_a_citation_sounds_on_the_second_run_only():
    # the ans line: Review every run, the prose cites nothing
    first = LineHealth(has_questions=True, claims=0, review=6, cited=0, previous_cited=4)
    assert first.reasons() == []
    assert LineHealth(has_questions=True, review=6, cited=0, previous_cited=None).reasons() == []
    second = LineHealth(has_questions=True, claims=0, review=6, cited=0, previous_cited=0)
    assert second.reasons() == ["no citation 2 runs in a row"]


def test_claims_on_the_template_are_not_citations():
    # a template day lists its claims, but its prose cites none of them
    health = LineHealth(has_questions=True, claims=5, review=0, cited=0, previous_cited=0)
    assert health.reasons() == ["no citation 2 runs in a row"]


def test_a_note_with_no_claim_and_no_review_sounds_at_once():
    health = LineHealth(has_questions=True, claims=0, review=0, cited=0, previous_cited=None)
    assert health.reasons() == ["empty note (no claim, no review)"]
    assert LineHealth(has_questions=True, claims=1, review=0, cited=1).reasons() == []
    assert LineHealth(has_questions=True, claims=0, review=1).reasons() == []


def test_a_line_with_no_question_is_never_quiet():
    assert LineHealth(claims=0, review=0, cited=0, previous_cited=0).reasons() == []


def test_the_quiet_reasons_come_after_the_judging_and_before_the_fetch():
    health = LineHealth(
        failed_pairs=10,
        pairs=100,
        fetch_failures=("citation/openalex http_status",),
        has_questions=True,
        previous_cited=0,
    )
    assert health.reasons() == [
        "unjudged 10/100 pairs (10%)",
        "empty note (no claim, no review)",
        "no citation 2 runs in a row",
        "fetch failed: citation/openalex http_status",
    ]


def _log(question: str, report: str, run_date: date, text: str) -> QuestionLog:
    return QuestionLog.new(
        question=question,
        report=report,
        run_date=run_date,
        movement="new_evidence_same_answer",
        text=text,
        logged_at=b.T0,
    )


def test_citations_are_counted_once_per_question_and_summed():
    report = b.report().id
    q1, q2 = b.question().id, b.question(version=2).id
    logs = [
        _log(q1, report, b.T0.date(), "A [1] and B [2], again A [1]. Not a cite: [x]."),
        _log(q2, report, b.T0.date(), "Its own first claim [1]."),  # another question's [1]
        _log(q1, report, b.T0.date(), ""),  # a template section
    ]
    assert run.cited(logs) == 3
    assert run.cited([]) == 0


def test_the_previous_count_is_the_latest_earlier_report():
    q = b.question().id
    day = b.T0.date()

    def report_on(d: date) -> Report:
        return b.report().model_copy(update={"id": Report.id_for(b.LINE_IRI, d), "run_date": d})

    older, last, today = (report_on(day - timedelta(days=n)) for n in (5, 2, 0))
    nodes = {
        n.id: n
        for n in (
            older,
            last,
            today,
            _log(q, older.id, older.run_date, "[1] [2] [3]"),
            _log(q, last.id, last.run_date, "only [2]"),
            _log(q, today.id, today.run_date, "today's [1] [2] are not the previous run"),
        )
    }
    assert run.cited_previous(nodes, b.LINE_IRI, b.T0) == 1
    # a Report with no QuestionLog (no section that day) cites 0; none at all is None
    del nodes[_log(q, last.id, last.run_date, "").id]
    assert run.cited_previous(nodes, b.LINE_IRI, b.T0) == 0
    assert run.cited_previous({today.id: today}, b.LINE_IRI, b.T0) is None
    assert run.cited_previous(nodes, "https://example.org/other-line", b.T0) is None
