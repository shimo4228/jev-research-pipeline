"""Step 10 tools: drift job, Slack one-liner, CLI wiring (no live calls, no real script)."""

import json
from collections.abc import Callable, Coroutine
from datetime import datetime
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


Handler = Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]]


def _drift_cli(
    monkeypatch: pytest.MonkeyPatch, live: Handler | None, *, gate: bool = True
) -> list[tuple[str, str]]:
    """`jrp drift` through main: the live gate set (or not), notify captured, and the client
    _drift opens answered by `live` (None = no request may be sent)."""
    from jev_research_pipeline import cli

    if gate:
        monkeypatch.setenv(LIVE_ENV, "1")
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    else:
        monkeypatch.delenv(LIVE_ENV, raising=False)
    sent: list[tuple[str, str]] = []

    def fake_notify(title: str, body: str, *, env: object) -> bool:
        sent.append((title, body))
        return True

    async def nothing(request: httpx2.Request) -> httpx2.Response:
        pytest.fail(f"replayed {request.url} although there was nothing to replay")

    real = httpx2.AsyncClient

    def client(**_: object) -> httpx2.AsyncClient:
        return real(transport=httpx2.MockTransport(live or nothing))

    monkeypatch.setattr(cli, "notify", fake_notify)
    monkeypatch.setattr(cli.httpx2, "AsyncClient", client)
    return sent


@pytest.mark.parametrize("make", [False, True], ids=["missing", "empty"])
def test_drift_without_cassettes_says_so_and_fails(
    make: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """The default dir (tests/cassettes/live) was never recorded: no call, and no "0 answers
    compared" that reads like no drift."""
    from jev_research_pipeline.cli import main

    cassettes = tmp_path / "live"
    if make:
        cassettes.mkdir()
        (cassettes / "notes.txt").write_text("not a cassette", encoding="utf-8")
    sent = _drift_cli(monkeypatch, None)
    assert main(["drift", "--cassettes", str(cassettes)]) == 1
    state = "has no *.json cassette" if make else "does not exist"
    why = f"nothing to compare: {cassettes} {state}"
    captured = capsys.readouterr()
    assert captured.err == f"jrp drift: {why}\n"
    assert captured.out == ""  # no empty table
    assert sent == [("jrp drift FAILED", why)]


async def _refused(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(401, json={"error": "bad key"})


@pytest.mark.parametrize(
    ("live", "failed"),
    [(_refused, 1), (None, 0)],
    ids=["every-replay-failed", "no-recorded-jev-request"],
)
def test_drift_that_compared_no_answer_fails_whatever_failed_says(
    live: Handler | None,
    failed: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """failed 0 (a cassette with no recorded Jev request: live None) is still nothing
    compared."""
    from jev_research_pipeline.cli import main

    if live:
        path = _cassette(tmp_path)
    else:
        path = tmp_path / "live" / "c.json"
        only_arxiv = Cassette(path)
        only_arxiv.put(
            "GET https://export.arxiv.org/api/query",
            Entry(status=200, content_type="text/xml", body="<feed/>"),
        )
        only_arxiv.save()
    sent = _drift_cli(monkeypatch, live)
    assert main(["drift", "--cassettes", str(path.parent)]) == 1
    why = f"no answer compared: 1 cassettes, {failed} replays failed"
    assert capsys.readouterr().err == f"jrp drift: {why}\n"
    assert sent == [("jrp drift FAILED", why)]


async def _moved(request: httpx2.Request) -> httpx2.Response:
    body = {
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
    }
    return httpx2.Response(200, json=body)


def test_drift_that_compared_answers_succeeds_with_the_worst_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from jev_research_pipeline.cli import main

    sent = _drift_cli(monkeypatch, _moved)
    assert main(["drift", "--cassettes", str(_cassette(tmp_path).parent)]) == 0
    assert "| c.json | relevant | 0.300 |" in capsys.readouterr().out
    assert sent == [("jrp drift", "2 answers compared, max Δp 0.300, 0 replays failed")]


def test_drift_with_the_gate_closed_stays_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """The gate comes first: a Monday job still loaded exits 2 with no message, as before."""
    from jev_research_pipeline.cli import main

    sent = _drift_cli(monkeypatch, None, gate=False)
    assert main(["drift", "--cassettes", str(tmp_path / "live")]) == 2
    assert f"set {LIVE_ENV}=1" in capsys.readouterr().err
    assert sent == []


def _timed_texts(out: str) -> list[str]:
    """The text after the time of each stdout line that starts with one (cli._log_line)."""
    from jev_research_pipeline.cli import LOG_TIME_FORMAT

    texts: list[str] = []
    for line in out.splitlines():
        stamp, _, text = line.partition(" ")
        try:
            when = datetime.strptime(stamp, LOG_TIME_FORMAT)
        except ValueError:
            continue
        assert when.tzinfo is not None  # the local offset is in the line
        texts.append(text)
    return texts


def test_cli_run_is_framed_by_timed_lines_and_the_message_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Under cron or systemd no wrapper writes the log's times: python writes its own."""
    from jev_research_pipeline import cli

    async def ran(*args: object, **kwargs: object) -> list[object]:
        return []

    sent: list[tuple[str, str]] = []

    def fake_notify(title: str, body: str, *, env: object) -> bool:
        sent.append((title, body))
        return True

    monkeypatch.setattr(cli, "run_pipeline", ran)
    monkeypatch.setattr(cli, "notify", fake_notify)
    assert cli.main(["run"]) == 0
    out = capsys.readouterr().out
    assert _timed_texts(out) == ["pipeline start", "pipeline end · 0 s"]
    assert out.splitlines()[2:] == ["jrp run", "no line ran"]  # run_summary, as before
    assert sent == [("jrp run", "no line ran")]  # Slack gets no time


def test_cli_run_failure_is_notified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
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
    assert _timed_texts(capsys.readouterr().out) == ["pipeline start", "pipeline end · 0 s"]


def test_sigterm_cancels_the_run_so_its_cleanup_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
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
    assert _timed_texts(capsys.readouterr().out)[-1] == "pipeline end · 0 s"  # a killed run too


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


@pytest.mark.parametrize(
    "found",
    [
        "/home/u/.cache/uv/archive-v0/QCHy0zYg/bin/jrp",  # uvx: a cache entry uv may delete
        "/home/u/src/jev-research-pipeline/.venv/bin/jrp",  # a checkout's venv
        None,
    ],
)
def test_schedule_install_refuses_a_jrp_that_will_not_stay(
    found: str | None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from jev_research_pipeline import cli

    def which(_: str) -> str | None:
        return found

    def install(**_: object) -> object:
        pytest.fail("wrote a job for a jrp that will not stay")

    monkeypatch.setattr(cli.shutil, "which", which)
    monkeypatch.setattr(cli, "install", install)
    assert cli.main(["schedule", "install", "--hour", "5"]) == 1
    assert "uv tool install" in capsys.readouterr().err


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


def test_the_harness_script_gets_the_slack_escaped_text_too():
    """notify-slack.sh posts its arguments to Slack as they are (jq --arg): an exception
    text with <!channel> or <url|label> in it must stay text there too."""
    from jev_research_pipeline.pipeline.notify import MACOS_ENV, WEBHOOK_ENV

    calls: list[list[str]] = []
    posted: list[dict[str, str]] = []
    env = {NOTIFY_ENV: "1", WEBHOOK_ENV: "https://h", MACOS_ENV: "1"}
    notify(
        "jrp run FAILED <!channel>",
        "RuntimeError: a & b <https://x|y> <@U123>",
        env=env,
        runner=calls.append,
        poster=lambda _u, p: posted.append(p),
    )
    script, osascript = [c for c in calls if c[0] == "bash"], [c for c in calls if c[0] != "bash"]
    ((_, _, title, body),) = script
    assert title == "jrp run FAILED &lt;!channel&gt;"
    assert body == "RuntimeError: a &amp; b &lt;https://x|y&gt; &lt;@U123&gt;"
    # the same text the webhook gets, and Notification Center (not Slack) gets it as written
    assert posted == [{"text": f"*{title}*\n{body}"}]
    assert osascript[0][-2:] == [
        "jrp run FAILED <!channel>",
        "RuntimeError: a & b <https://x|y> <@U123>",
    ]
