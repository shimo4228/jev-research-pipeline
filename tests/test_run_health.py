"""A degraded run is said out loud: the summary notification of a run that finished but
whose prose failed, whose writer was refused, whose Jev screen failed on a real share of
pairs, whose adapters failed or whose cost cap stopped a line says DEGRADED, one reason
line per line, in one Slack message (pipeline.health, pipeline.runner.run_summary)."""

import functools
from datetime import date
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.providers.openai_codex import CredentialsRefreshError

from jev_research_pipeline.generation import GenerationMeter, write_prose
from jev_research_pipeline.generation.claude_code import (
    ClaudeAuthError,
    ClaudeCodeError,
    parse_result,
)
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
    import httpx2

    from jev_research_pipeline.adapters import web_search
    from jev_research_pipeline.pipeline import nets
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
