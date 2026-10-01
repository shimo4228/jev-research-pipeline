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


def test_sigterm_cancels_the_run_so_its_cleanup_runs(monkeypatch: pytest.MonkeyPatch):
    """The wrapper's watchdog sends SIGTERM: the run is cancelled and unwinds (a claude-code
    CLI is killed on the way out) instead of python dying mid-await."""
    import asyncio
    import os
    import signal

    from jev_research_pipeline import cli

    unwound: list[str] = []

    async def hangs(*args: object, **kwargs: object) -> list[object]:
        asyncio.get_running_loop().call_later(0.05, os.kill, os.getpid(), signal.SIGTERM)
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            unwound.append("cancelled")
            raise
        return []

    monkeypatch.setattr(cli, "run_pipeline", hangs)
    with pytest.raises(asyncio.CancelledError):
        cli.main(["run"])
    assert unwound == ["cancelled"]
    assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL  # the handler is not left behind


def test_notify_posts_to_a_slack_webhook_and_survives_its_failure():
    import httpx2

    from jev_research_pipeline.pipeline.notify import WEBHOOK_ENV

    posted: list[tuple[str, dict[str, str]]] = []

    def poster(url: str, payload: dict[str, str]) -> object:
        posted.append((url, payload))
        raise httpx2.ConnectError("down")

    env = {WEBHOOK_ENV: "https://hooks.slack.com/services/T/B/x"}
    assert notify("jrp run", "akc: 3 claims", env=env, poster=poster) is True
    assert posted == [(env[WEBHOOK_ENV], {"text": "*jrp run*\nakc: 3 claims"})]


def test_notify_reaches_macos_notification_center_with_text_as_arguments():
    from jev_research_pipeline.pipeline.notify import MACOS_ENV

    calls: list[list[str]] = []
    hostile = '" & do shell script "touch /tmp/x" & "'
    assert notify("jrp", hostile, env={MACOS_ENV: "1"}, runner=calls.append) is True
    (cmd,) = calls
    assert cmd[0] == "osascript" and cmd[-2:] == ["jrp", hostile]
    assert all(hostile not in a for a in cmd[:-1])  # never part of the script itself


def test_schedule_install_writes_a_job_for_this_jrp_and_keeps_existing_files(tmp_path: Path):
    import plistlib

    from jev_research_pipeline.scheduling import LABEL, install

    s = install(jrp=Path("/opt/jrp/bin/jrp"), hour=6, minute=30, home=tmp_path, log=tmp_path / "l")
    assert s.created == (True, True)
    job = plistlib.loads(s.plist.read_bytes())
    assert job["Label"] == LABEL
    assert job["ProgramArguments"] == ["/bin/bash", str(s.wrapper), "run"]
    assert job["EnvironmentVariables"] == {
        "JRP_BIN": "/opt/jrp/bin/jrp",
        "JRP_ENV_FILE": str(tmp_path / "env"),
    }
    assert job["StartCalendarInterval"] == {"Hour": 6, "Minute": 30}
    assert s.wrapper.stat().st_mode & 0o111  # executable
    s.plist.write_text("mine", encoding="utf-8")
    again = install(jrp=Path("/x"), home=tmp_path)
    assert again.created == (False, False) and s.plist.read_text(encoding="utf-8") == "mine"


def test_the_packaged_wrapper_is_the_repos_wrapper():
    repo = Path(__file__).parents[1]
    packaged = repo / "src" / "jev_research_pipeline" / "scheduling" / "launchd-jrp.sh"
    assert packaged.read_text(encoding="utf-8") == (repo / "scripts" / "launchd-jrp.sh").read_text(
        encoding="utf-8"
    )


def test_a_missing_notifier_program_does_not_fail_the_run(monkeypatch: pytest.MonkeyPatch):
    from jev_research_pipeline.pipeline import notify as n

    def missing(*_: object, **__: object) -> object:
        raise FileNotFoundError("osascript")

    monkeypatch.setattr(n.subprocess, "run", missing)
    assert n.notify("jrp", "ok", env={n.MACOS_ENV: "1"}) is True


def test_a_broken_webhook_url_neither_fails_the_run_nor_silences_the_other_channels():
    from jev_research_pipeline.pipeline.notify import MACOS_ENV, WEBHOOK_ENV

    def poster(url: str, payload: dict[str, str]) -> object:
        raise ValueError("invalid url (a CRLF env file leaves a \\r in it)")

    calls: list[list[str]] = []
    env = {WEBHOOK_ENV: "https://hooks.slack.com/x\r", MACOS_ENV: "1"}
    assert notify("jrp", "b", env=env, poster=poster, runner=calls.append) is True
    assert [c[0] for c in calls] == ["osascript"]


def test_slack_text_is_escaped():
    from jev_research_pipeline.pipeline.notify import WEBHOOK_ENV

    posted: list[dict[str, str]] = []
    notify(
        "jrp <!channel>",
        "a & b <https://x|y>",
        env={WEBHOOK_ENV: "https://h"},
        poster=lambda _u, p: posted.append(p),
    )
    assert posted == [{"text": "*jrp &lt;!channel&gt;*\na &amp; b &lt;https://x|y&gt;"}]
