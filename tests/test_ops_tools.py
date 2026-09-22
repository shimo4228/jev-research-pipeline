"""Step 10 tools: drift job, Slack one-liner, CLI wiring (no live calls, no real script)."""

import json
from pathlib import Path

import httpx2
import pytest

from jev_research_pipeline.cassette import Cassette, Entry
from jev_research_pipeline.pipeline.drift import LIVE_ENV, drift, drift_table, drift_with_failures
from jev_research_pipeline.pipeline.notify import NOTIFY_ENV, notify


def _cassette(tmp_path: Path) -> Path:
    path = tmp_path / "live" / "c.json"
    c = Cassette(path)
    recorded = {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": {
            "relevant": {"type": "noul", "noul": 0.8},
            "trust": {
                "type": "score",
                "score": 1.0,
                "confidence": 0.6,
                "legend": {"0": "a", "1": "b"},
                "probabilities": {"0": 0.4, "1": 0.6},
            },
        },
    }
    c.put(
        "POST https://api.typesafe.ai/v1/systemone body:0",
        Entry(
            status=200,
            content_type="application/json",
            body=json.dumps(recorded),
            request_body=json.dumps({"state": "s", "model": "jev-1.13.0", "questions": {}}),
        ),
    )
    c.put(
        "GET https://export.arxiv.org/api/query",
        Entry(status=200, content_type="text/xml", body="<feed/>"),
    )
    c.save()
    return path


async def test_drift_reports_probability_deltas(tmp_path: Path):
    seen: list[httpx2.Request] = []

    async def live(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": {
                    "relevant": {"type": "noul", "noul": 0.5},
                    "trust": {
                        "type": "score",
                        "score": 1.0,
                        "confidence": 0.6,
                        "legend": {"0": "a", "1": "b"},
                        "probabilities": {"0": 0.4, "1": 0.6},
                    },
                },
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(live)) as client:
        rows = await drift([_cassette(tmp_path)], client, api_key="k")
    assert len(seen) == 1  # only the Jev entry is replayed, with its recorded body
    assert json.loads(seen[0].content)["model"] == "jev-1.13.0"
    by_q = {r.question: r for r in rows}
    assert by_q["relevant"].delta == pytest.approx(0.3)
    assert by_q["trust"].delta == pytest.approx(0.0)
    assert "relevant" in drift_table(rows)


def test_drift_live_switch_name():
    assert LIVE_ENV == "JRP_DRIFT_LIVE"


def test_notify_is_off_unless_env_says_so():
    calls: list[list[str]] = []
    assert notify("t", "b", env={}, runner=calls.append) is False
    assert calls == []


def test_notify_calls_the_harness_script_with_title_and_body():
    calls: list[list[str]] = []
    assert notify("jrp", "3 reports", env={NOTIFY_ENV: "1"}, runner=calls.append) is True
    (cmd,) = calls
    assert cmd[0] == "bash" and cmd[1].endswith(".claude/scripts/notify-slack.sh")
    assert cmd[2:] == ["jrp", "3 reports"]


def test_cli_parses_subcommands():
    from jev_research_pipeline.cli import parser

    p = parser()
    assert p.parse_args(["run"]).command == "run"
    assert p.parse_args(["drift", "--cassettes", "x"]).command == "drift"
    assert p.parse_args(["fit"]).command == "fit"
    assert p.parse_args(["export-cases"]).command == "export-cases"


async def test_drift_counts_failed_replays(tmp_path: Path):
    async def down(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": "bad key"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(down)) as client:
        rows, failed = await drift_with_failures([_cassette(tmp_path)], client, api_key="k")
    assert (rows, failed) == ([], 1)


def test_cli_run_failure_is_notified(monkeypatch: pytest.MonkeyPatch):
    from jev_research_pipeline import cli

    sent: list[tuple[str, str]] = []

    async def boom(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("vault missing")

    monkeypatch.setattr(cli, "run_pipeline", boom)

    def fake_notify(title: str, body: str, *, env: object) -> bool:
        sent.append((title, body))
        return True

    monkeypatch.setattr(cli, "notify", fake_notify)
    with pytest.raises(RuntimeError):
        cli.main(["run"])
    assert sent and sent[0][0] == "jrp run FAILED" and "vault missing" in sent[0][1]
