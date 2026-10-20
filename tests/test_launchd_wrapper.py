"""scripts/launchd-jrp.sh stages the vault for `jrp run`: python must never open the
iCloud vault under launchd (TCC), so bash copies notes in and the run's notes back out.
It also reports what python cannot: a run that hangs (the watchdog) and a wrapper that
fails before python starts."""

import os
import re
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest

from jev_research_pipeline.cli import LOG_TIME_FORMAT

SCRIPT = Path(__file__).parents[1] / "scripts" / "launchd-jrp.sh"

# `jrp doctor` stand-in, the first lines of every fake uv: asserts it too sees the stage,
# prints a check line, exits $DOCTOR_STATUS (a FAIL line with it when non-zero).
DOCTOR = """
if [[ " $* " == *" jrp doctor "* ]]; then
  [[ "$JRP_VAULT_DIR" == "$EXPECT_STAGE" ]] || { echo "doctor saw the vault"; exit 8; }
  echo "ok   env: fake doctor"
  [[ "${DOCTOR_STATUS:-0}" == 0 ]] || echo "FAIL writer: claude-code:sonnet: not logged in"
  exit "${DOCTOR_STATUS:-0}"
fi
"""

# `jrp wbr` stand-in, after the doctor's: asserts it too sees the stage, prints "fake wbr"
# and writes the week's note there. $WBR: hang = sleeps in a child first, as HUNG_UV's run;
# fail = writes the note, then exits 3 (as a review whose weekly.jsonl append failed).
WBR_NOTE = "2026-09-28_jrp_wbr.md"
WBR = f"""
if [[ " $* " == *" jrp wbr "* ]]; then
  [[ "$JRP_VAULT_DIR" == "$EXPECT_STAGE" ]] || {{ echo "wbr saw the vault"; exit 8; }}
  echo "fake wbr"
  if [[ "${{WBR:-}}" == hang ]]; then
    sleep 30 &
    echo $! > "$WBR_PID"
    wait
  fi
  rm -f "$JRP_VAULT_DIR/daily-research/{WBR_NOTE}"
  echo "review" > "$JRP_VAULT_DIR/daily-research/{WBR_NOTE}"
  [[ "${{WBR:-}}" != fail ]] || exit 3
  exit 0
fi
"""

# A stand-in for uv: asserts it was pointed at the stage, harvests (reads) a staged note,
# rewrites one note and writes a new one — what `jrp run` does to the vault dir — and exits
# $RUN_STATUS.
FAKE_UV = f"""#!/usr/bin/env bash
set -euo pipefail
{DOCTOR}
{WBR}
notes="$JRP_VAULT_DIR/daily-research"
[[ "$JRP_VAULT_DIR" == "$EXPECT_STAGE" ]] || {{ echo "vault not staged: $JRP_VAULT_DIR"; exit 9; }}
if [[ -n "${{EXPECT_WORKSPACE:-}}" ]]; then  # Obsidian's list, read from the stage
  [[ "$(cat "$JRP_VAULT_DIR/.obsidian/workspace.json")" == "$EXPECT_WORKSPACE" ]] ||
    {{ echo "workspace not staged"; exit 7; }}
fi
if [[ -n "${{STAGE_SNAPSHOT:-}}" ]]; then  # what the stage's .obsidian holds during the run
  rm -rf "$STAGE_SNAPSHOT"
  mkdir -p "$STAGE_SNAPSHOT"
  if [[ -d "$JRP_VAULT_DIR/.obsidian" ]]; then cp -Rp "$JRP_VAULT_DIR/.obsidian/." "$STAGE_SNAPSHOT/"; fi
fi
grep -q "[x]" "$notes/2026-09-23_jrp_akc.md"
echo "rewritten" > "$notes/2026-09-24_jrp_akc.md"
echo "new" > "$notes/2026-09-24_jrp_aap.md"
if [[ -n "${{WRITE_ANS:-}}" ]]; then  # a note whose vault copy is read-only
  rm -f "$notes/2026-09-24_jrp_ans.md"
  echo "ans" > "$notes/2026-09-24_jrp_ans.md"
fi
if [[ -n "${{RUN_SLEEP:-}}" ]]; then sleep "$RUN_SLEEP"; fi  # a run that takes this long
echo "args: $*"
exit "${{RUN_STATUS:-0}}"
"""


def _setup(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    vault = tmp_path / "vault" / "daily-research"
    vault.mkdir(parents=True)
    (vault / "2026-09-23_jrp_akc.md").write_text("- [x] ticked\n")
    (vault / "2026-09-24_jrp_akc.md").write_text("old\n")
    (vault / "2026-09-23_edge_other.md").write_text("not a jrp note\n")
    old = time.time() - 3600
    os.utime(vault / "2026-09-23_jrp_akc.md", (old, old))
    uv = tmp_path / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
    store = tmp_path / "store"
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "JRP_ENV_FILE": str(tmp_path / "no-env"),
        "JRP_UV": str(uv),
        "JRP_VAULT_DIR": str(tmp_path / "vault"),
        "JRP_STORE_DIR": str(store),
        "EXPECT_STAGE": str(store / "vault-stage"),
        "JRP_WBR_DUE": "0",  # not Monday, whatever day the tests run (the review's tests: 1)
        "JRP_CAFFEINATE": "",  # no sleep assertion from a test (its own test below)
    }
    return env, vault, store / "vault-stage" / "daily-research"


def test_run_stages_the_vault_and_copies_back_only_what_it_wrote(tmp_path: Path):
    env, vault, stage = _setup(tmp_path)
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    assert "--frozen jrp run" in out.stdout
    assert out.stdout.index("ok   env: fake doctor") < out.stdout.index("--frozen jrp run")
    assert (vault / "2026-09-24_jrp_akc.md").read_text() == "rewritten\n"
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"
    assert (vault / "2026-09-23_jrp_akc.md").read_text() == "- [x] ticked\n"  # untouched
    assert (vault / "2026-09-23_edge_other.md").exists()  # nothing deleted in the vault
    assert not (stage / "2026-09-23_edge_other.md").exists()  # only jrp notes are staged
    assert "vault ← 2026-09-24_jrp_aap.md" in out.stdout
    assert "2026-09-23_jrp_akc.md" not in out.stdout  # read, not written: not copied back


def test_other_commands_do_not_stage(tmp_path: Path):
    env, _, stage = _setup(tmp_path)
    out = subprocess.run(
        ["bash", str(SCRIPT), "drift"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 9  # the fake saw the real vault dir: drift is passed through
    assert not stage.exists()


# A hung run (2026-09-24: 80 min on an invisible TCC prompt): writes one note, then hangs in
# a child process, the way uv's python sits under uv.
HUNG_UV = f"""#!/usr/bin/env bash
{DOCTOR}
{WBR}
echo "partial" > "$JRP_VAULT_DIR/daily-research/2026-09-24_jrp_akc.md"
ls "$JRP_VAULT_DIR/.obsidian" > "$HUNG_PID.staged" 2>/dev/null
sleep 30 &
echo $! > "$HUNG_PID"
wait
"""

# notify-slack.sh stand-in: one line per call, the title and the body, into $NOTIFIED.
FAKE_NOTIFY = """#!/usr/bin/env bash
printf '%s|%s\\n' "$1" "$2" >> "$NOTIFIED"
"""


def _with_notify(tmp_path: Path, env: dict[str, str]) -> Path:
    script = tmp_path / ".claude" / "scripts" / "notify-slack.sh"  # HOME is tmp_path
    script.parent.mkdir(parents=True)
    script.write_text(FAKE_NOTIFY)
    notified = tmp_path / "notified"
    env |= {"JRP_SLACK_NOTIFY": "1", "NOTIFIED": str(notified)}
    return notified


def _messages(notified: Path) -> list[tuple[str, str]]:
    lines = notified.read_text().splitlines() if notified.exists() else []
    return [(title, body) for title, _, body in (ln.partition("|") for ln in lines)]


def test_a_hung_run_is_killed_notified_and_its_notes_still_copied_back(tmp_path: Path):
    env, vault, _ = _setup(tmp_path)
    (tmp_path / "uv").write_text(HUNG_UV)
    notified = _with_notify(tmp_path, env)
    env |= {"JRP_RUN_TIMEOUT_S": "1", "HUNG_PID": str(tmp_path / "hung.pid")}
    started = time.monotonic()
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert time.monotonic() - started < 20  # not the 30 s the child would have slept
    assert out.returncode == 124
    assert (vault / "2026-09-24_jrp_akc.md").read_text() == "partial\n"
    ((title, body),) = _messages(notified)
    assert title == "jrp run TIMED OUT"
    assert "1 s" in body and "1 note" in body
    child = int((tmp_path / "hung.pid").read_text())
    with pytest.raises(ProcessLookupError):  # the whole process group, not only uv
        os.kill(child, 0)


def test_a_run_within_the_timeout_is_not_notified_by_the_wrapper(tmp_path: Path):
    env, _, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    subprocess.run(["bash", str(SCRIPT), "run"], env=env, capture_output=True, check=True)
    assert _messages(notified) == []  # python sends the run's own message


@pytest.mark.parametrize("slack", [True, False])
def test_a_wrapper_that_fails_before_python_starts_is_notified(tmp_path: Path, slack: bool):
    env, _, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    if not slack:
        del env["JRP_SLACK_NOTIFY"]
    env["JRP_UV"] = str(tmp_path / "no-such-uv")
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode != 0
    assert "uv not found" in out.stderr  # the log says why either way
    if slack:
        ((title, body),) = _messages(notified)
        assert title == "jrp run FAILED" and "uv not found" in body
    else:
        assert _messages(notified) == []


def test_the_harness_slack_script_gets_the_title_and_body_slack_escaped(tmp_path: Path):
    """notify-slack.sh posts its arguments as they are, so the wrapper escapes & < > first,
    as pipeline/notify.py's _slack_text does (& before the others): <!channel> or <url|label>
    in a path or a reason stays text in Slack. The log keeps the text as written."""
    env, _, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    env["JRP_UV"] = str(tmp_path / "<!channel> & <x|y> 未取得")  # no "/": one path part
    out = subprocess.run(
        ["bash", str(SCRIPT), "<@U123>&"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode != 0
    ((title, body),) = _messages(notified)
    assert title == "jrp &lt;@U123&gt;&amp; FAILED"
    assert body == (
        "launchd-jrp.sh stopped before jrp started: uv not found at "
        f"{tmp_path}/&lt;!channel&gt; &amp; &lt;x|y&gt; 未取得 (JRP_UV)"
    )
    assert "jrp <@U123>& FAILED: launchd-jrp.sh stopped" in out.stderr
    assert f"{tmp_path}/<!channel> & <x|y> 未取得 (JRP_UV)" in out.stderr


def test_jrp_notify_gets_the_text_as_written(tmp_path: Path):
    """The webhook and Notification Center go through `jrp notify` (pipeline/notify.py),
    which escapes for Slack itself: only the harness script gets the wrapper's escaping."""
    env, _, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    jrp = tmp_path / "jrp"
    jrp.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$1" == notify && "$2" == -- ]] && printf "%s|%s\\n" "$3" "$4" >> "$NOTIFIED_PY"\n'
    )
    jrp.chmod(0o755)
    raw = "<!channel> & <https://x|y>"
    env |= {
        "JRP_BIN": str(jrp),
        "JRP_SLACK_WEBHOOK_URL": "https://hooks.example/x",
        "NOTIFIED_PY": str(tmp_path / "notified-py"),
        "JRP_RUN_TIMEOUT_S": raw,
    }
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode != 0
    ((title, body),) = _messages(tmp_path / "notified-py")
    assert title == "jrp run FAILED" and body.endswith(f"seconds: {raw}")
    ((_, slack_body),) = _messages(notified)
    assert slack_body.endswith("seconds: &lt;!channel&gt; &amp; &lt;https://x|y&gt;")


def test_a_timeout_that_is_not_a_number_stops_before_python(tmp_path: Path):
    env, _, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    env["JRP_RUN_TIMEOUT_S"] = "1h"
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode != 0
    ((title, body),) = _messages(notified)
    assert title == "jrp run FAILED" and "JRP_RUN_TIMEOUT_S" in body


def test_a_failing_doctor_is_notified_and_the_run_still_goes_ahead(tmp_path: Path):
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    env["DOCTOR_STATUS"] = "1"
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    assert "FAIL writer: claude-code:sonnet: not logged in" in out.stdout  # in the log
    ((title, body),) = _messages(notified)
    assert title == "jrp doctor FAILED"
    assert "FAIL writer: claude-code:sonnet: not logged in" in body and "run goes ahead" in body
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"  # the run did run


def test_a_note_that_cannot_reach_the_vault_is_notified_and_the_others_still_go(tmp_path: Path):
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    blocked = vault / "2026-09-24_jrp_ans.md"
    blocked.write_text("old\n")
    blocked.chmod(0o444)  # the vault copy of one note refuses the write
    env["WRITE_ANS"] = "1"
    try:
        out = subprocess.run(
            ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
        )
    finally:
        blocked.chmod(0o644)
    assert out.returncode == 1
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"  # the other note went
    ((title, body),) = _messages(notified)
    assert title == "jrp run FAILED" and "2026-09-24_jrp_ans.md" in body
    assert "2026-09-24_jrp_aap.md" not in body


def test_a_term_to_the_wrapper_reaches_the_run_it_started(tmp_path: Path):
    """launchctl or a shutdown TERMs the wrapper; the run sits in its own process group,
    so without passing the signal on it would go on (spending the prose plan) orphaned."""
    env, _, _ = _setup(tmp_path)
    (tmp_path / "uv").write_text(HUNG_UV)
    env |= {"JRP_RUN_TIMEOUT_S": "600", "HUNG_PID": str(tmp_path / "hung.pid")}
    wrapper = subprocess.Popen(
        ["bash", str(SCRIPT), "run"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    pid_file = tmp_path / "hung.pid"
    deadline = time.monotonic() + 10
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    child = int(pid_file.read_text())
    wrapper.terminate()
    assert wrapper.wait(timeout=10) == 143
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    pytest.fail("the run outlived the wrapper")


def _installed(tmp_path: Path) -> Path:
    """An installed jrp (JRP_BIN): the fake uv, called as `jrp <args>`; `jrp notify` appends
    to $NOTIFIED."""
    jrp = tmp_path / "jrp"
    jrp.write_text(
        FAKE_UV.replace('" jrp doctor "', '" doctor "')
        .replace('" jrp wbr "', '" wbr "')
        .replace(
            "set -euo pipefail\n",
            'set -euo pipefail\n[[ "$1" == notify && "$2" == -- ]] && { printf "%s|%s\\n" "$3" "$4" >> "$NOTIFIED"; exit 0; }\n',
            1,
        )
    )
    jrp.chmod(0o755)
    return jrp


def test_an_installed_jrp_is_started_directly_and_notifies_through_python(tmp_path: Path):
    """JRP_BIN (written by `jrp schedule install`): the wrapper starts that jrp, not uv in a
    checkout, and a webhook / Notification Center message goes through `jrp notify`."""
    env, vault, _ = _setup(tmp_path)
    jrp = _installed(tmp_path)
    notified = tmp_path / "notified"
    env |= {
        "JRP_BIN": str(jrp),
        "JRP_UV": str(tmp_path / "no-uv"),
        "JRP_SLACK_WEBHOOK_URL": "https://hooks.example/x",
        "NOTIFIED": str(notified),
        "DOCTOR_STATUS": "1",
    }
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    assert "args: run" in out.stdout  # `jrp run`, not `uv run --project … jrp run`
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"
    assert [t for t, _ in _messages(notified)] == ["jrp doctor FAILED"]


# --- the log's times --------------------------------------------------------------------

_STAMP = re.compile(r"^(\S+) (.*)$")


def _timed(text: str) -> list[tuple[datetime, str]]:
    """(time, text) of each line that starts with a LOG_TIME_FORMAT time."""
    out: list[tuple[datetime, str]] = []
    for line in text.splitlines():
        if m := _STAMP.match(line):
            try:
                out.append((datetime.strptime(m[1], LOG_TIME_FORMAT), m[2]))
            except ValueError:
                continue
    return out


def test_the_wrapper_and_python_write_one_time_format():
    assert f"date '+{LOG_TIME_FORMAT}'" in SCRIPT.read_text(encoding="utf-8")


def test_every_wrapper_line_starts_with_the_time_and_the_run_is_framed(tmp_path: Path):
    env, _, _ = _setup(tmp_path)
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    timed = _timed(out.stdout)
    texts = [text for _, text in timed]
    assert texts[0] == "ok   env: fake doctor"  # the doctor's lines, as the wrapper logs them
    assert texts[1] == "start jrp run"
    assert re.fullmatch(r"end jrp run status 0 · \d+ s", texts[2])
    assert sorted(texts[3:]) == ["vault ← 2026-09-24_jrp_aap.md", "vault ← 2026-09-24_jrp_akc.md"]
    assert all(when.tzinfo is not None for when, _ in timed)
    lines = out.stdout.splitlines()
    run_line = next(i for i, ln in enumerate(lines) if "--frozen jrp run" in ln)
    start = next(i for i, ln in enumerate(lines) if ln.endswith(" start jrp run"))
    end = next(i for i, ln in enumerate(lines) if " end jrp run status " in ln)
    assert start < run_line < end  # python's output (untimed here: the fake's) in between
    assert len(timed) == len(lines) - 1  # every line but the fake python's own


def test_a_wrapper_failure_on_stderr_starts_with_the_time_and_slack_gets_it_bare(
    tmp_path: Path,
):
    env, _, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    env["JRP_UV"] = str(tmp_path / "no-such-uv")
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.stdout == ""  # stderr only: the two streams stay apart
    texts = [text for _, text in _timed(out.stderr)]
    assert len(texts) == len(out.stderr.splitlines()) == 2
    assert texts[0].startswith("uv not found at ")
    assert texts[1].startswith("jrp run FAILED: launchd-jrp.sh stopped before jrp started: ")
    ((title, body),) = _messages(notified)
    assert title == "jrp run FAILED" and body.startswith("launchd-jrp.sh stopped")


def test_a_killed_run_logs_its_end_before_the_timeout_notice(tmp_path: Path):
    env, _, _ = _setup(tmp_path)
    (tmp_path / "uv").write_text(HUNG_UV)
    env |= {"JRP_RUN_TIMEOUT_S": "1", "HUNG_PID": str(tmp_path / "hung.pid")}
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 124
    (end,) = [t for _, t in _timed(out.stdout) if t.startswith("end jrp run")]
    assert re.fullmatch(r"end jrp run status (?!0 )\d+ · \d+ s", end)
    assert [t for _, t in _timed(out.stderr)][-1].startswith("jrp run TIMED OUT: killed after 1 s")


# --- Obsidian's recently opened files ------------------------------------------------------


def _obsidian(tmp_path: Path) -> Path:
    """The vault's .obsidian: the two lists, an iCloud conflict copy and an app setting."""
    obsidian = tmp_path / "vault" / ".obsidian"
    obsidian.mkdir(parents=True)
    for name, text in [
        ("workspace.json", '{"lastOpenFiles": ["desktop"]}'),
        ("workspace-mobile.json", '{"lastOpenFiles": ["mobile"]}'),
        ("workspace 2.json", '{"lastOpenFiles": ["conflict"]}'),
        ("app.json", "{}"),
    ]:
        (obsidian / name).write_text(text)
    old = time.time() - 7200
    os.utime(obsidian / "workspace.json", (old, old))
    return obsidian


def _snapshot(path: Path) -> dict[str, tuple[bytes, float]]:
    return {p.name: (p.read_bytes(), p.stat().st_mtime) for p in path.iterdir()}


def test_the_two_workspace_lists_and_nothing_else_reach_the_stage(tmp_path: Path):
    env, _, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    obsidian = _obsidian(tmp_path)
    before = _snapshot(obsidian)
    env["EXPECT_WORKSPACE"] = '{"lastOpenFiles": ["desktop"]}'  # the fake reads the stage
    env["STAGE_SNAPSHOT"] = str(tmp_path / "snapshot")
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    during = _snapshot(tmp_path / "snapshot")  # the stage's .obsidian while the run ran
    assert sorted(during) == ["workspace-mobile.json", "workspace.json"]
    for name in ("workspace.json", "workspace-mobile.json"):
        assert during[name] == before[name]  # cp -p: the bytes and the mtime
    assert _snapshot(obsidian) == before
    assert _messages(notified) == [] and out.stderr == ""


def test_the_copies_leave_the_stage_once_the_run_returns(tmp_path: Path):
    """The lists name every recently opened file, jrp's or not; python keeps only jrp note
    names, so the copies holding the rest stay in the stage only while the run reads them."""
    env, _, _ = _setup(tmp_path)
    obsidian = _obsidian(tmp_path)
    staged = tmp_path / "store" / "vault-stage" / ".obsidian"
    subprocess.run(["bash", str(SCRIPT), "run"], env=env, capture_output=True, check=True)
    assert list(staged.iterdir()) == []
    assert sorted(p.name for p in obsidian.iterdir()) == [
        "app.json",
        "workspace 2.json",
        "workspace-mobile.json",
        "workspace.json",
    ]


def test_a_killed_run_leaves_no_copy_in_the_stage(tmp_path: Path):
    env, _, _ = _setup(tmp_path)
    (tmp_path / "uv").write_text(HUNG_UV)
    _obsidian(tmp_path)
    env |= {"JRP_RUN_TIMEOUT_S": "1", "HUNG_PID": str(tmp_path / "hung.pid")}
    out = subprocess.run(["bash", str(SCRIPT), "run"], env=env, capture_output=True, check=False)
    assert out.returncode == 124
    staged = tmp_path / "store" / "vault-stage" / ".obsidian"
    assert (tmp_path / "hung.pid.staged").read_text().split() == [
        "workspace-mobile.json",
        "workspace.json",
    ]
    assert list(staged.iterdir()) == []


def test_a_termed_wrapper_leaves_no_copy_in_the_stage(tmp_path: Path):
    env, _, _ = _setup(tmp_path)
    (tmp_path / "uv").write_text(HUNG_UV)
    _obsidian(tmp_path)
    env |= {"JRP_RUN_TIMEOUT_S": "600", "HUNG_PID": str(tmp_path / "hung.pid")}
    wrapper = subprocess.Popen(
        ["bash", str(SCRIPT), "run"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    pid_file = tmp_path / "hung.pid"
    deadline = time.monotonic() + 10
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    staged = tmp_path / "store" / "vault-stage" / ".obsidian"
    assert sorted(p.name for p in staged.iterdir()) == ["workspace-mobile.json", "workspace.json"]
    wrapper.terminate()
    assert wrapper.wait(timeout=10) == 143
    assert list(staged.iterdir()) == []


def test_a_copy_a_killed_wrapper_left_is_not_read_again(tmp_path: Path):
    """A KILL runs no trap: the copies it left go before the next run stages the vault's."""
    env, _, _ = _setup(tmp_path)
    obsidian = _obsidian(tmp_path)
    staged = tmp_path / "store" / "vault-stage" / ".obsidian"
    snapshot = tmp_path / "snapshot"
    env["STAGE_SNAPSHOT"] = str(snapshot)
    subprocess.run(["bash", str(SCRIPT), "run"], env=env, capture_output=True, check=True)
    assert sorted(p.name for p in snapshot.iterdir()) == ["workspace-mobile.json", "workspace.json"]

    (obsidian / "workspace-mobile.json").unlink()
    (staged / "workspace-mobile.json").write_text('{"lastOpenFiles": ["left by a KILL"]}')
    subprocess.run(["bash", str(SCRIPT), "run"], env=env, capture_output=True, check=True)
    assert [p.name for p in snapshot.iterdir()] == ["workspace.json"]

    for p in obsidian.iterdir():
        p.unlink()
    obsidian.rmdir()  # a vault without .obsidian: the left copies go too
    (staged / "workspace.json").write_text('{"lastOpenFiles": ["left by a KILL"]}')
    subprocess.run(["bash", str(SCRIPT), "run"], env=env, capture_output=True, check=True)
    assert list(snapshot.iterdir()) == []
    assert list(staged.iterdir()) == []


FIRMLINKED = Path("/System/Volumes/Data")
"""Where macOS's firmlinks (/usr/share/firmlinks: /Users, /private/var, …) lead: the same
directory under two paths that are not symlinks, so `pwd -P` keeps them apart."""


@pytest.mark.parametrize(
    "stage", ["vault", "link", "obsidian_link", "case_alias", "case_alias_obsidian", "firmlink"]
)
def test_a_stage_that_is_the_vault_stops_before_obsidian_is_touched(tmp_path: Path, stage: str):
    """The vault's workspace lists are never removed: the stage's copies are, so a stage
    that is the vault's directory (-ef: the same device and inode) is refused before
    anything is removed or copied — whatever path names it: a symlink, a name that differs
    only in case on case-insensitive APFS, or a firmlink."""
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    obsidian = _obsidian(tmp_path)
    before = _snapshot(obsidian)
    if stage.startswith("case_alias") and not (tmp_path / "VAULT").exists():
        pytest.skip("a case-sensitive filesystem: VAULT is not vault")
    if stage == "firmlink" and not (FIRMLINKED / str(tmp_path).lstrip("/")).is_dir():
        pytest.skip(f"no firmlink to {tmp_path} under {FIRMLINKED}")
    if stage == "vault":
        env["JRP_VAULT_STAGE"] = str(vault.parent)
    elif stage == "link":
        (tmp_path / "link").symlink_to(vault.parent)
        env["JRP_VAULT_STAGE"] = str(tmp_path / "link")
    elif stage == "case_alias":  # …/VAULT is …/vault on case-insensitive APFS
        env["JRP_VAULT_STAGE"] = str(tmp_path / "VAULT")
    elif stage == "case_alias_obsidian":  # a stage of its own, .obsidian a link to …/VAULT's
        (tmp_path / "stage").mkdir()
        (tmp_path / "stage" / ".obsidian").symlink_to(tmp_path / "VAULT" / ".OBSIDIAN")
        env["JRP_VAULT_STAGE"] = str(tmp_path / "stage")
    elif stage == "firmlink":  # /System/Volumes/Data/private/var/… is /private/var/…
        env["JRP_VAULT_STAGE"] = str(FIRMLINKED / str(vault.parent).lstrip("/"))
    else:  # a stage of its own whose .obsidian is the vault's
        (tmp_path / "stage").mkdir()
        (tmp_path / "stage" / ".obsidian").symlink_to(obsidian)
        env["JRP_VAULT_STAGE"] = str(tmp_path / "stage")
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 1
    assert _snapshot(obsidian) == before
    assert "args:" not in out.stdout  # jrp never started
    assert (vault / "2026-09-24_jrp_akc.md").read_text() == "old\n"
    ((title, body),) = _messages(notified)
    assert title == "jrp run FAILED" and "is the vault" in body


# stat stand-in: the file named in $DATALESS reports iCloud's dataless flag, the rest asks
# the real stat (macOS: `stat -f %Sf` prints the file's flags, "-" for none).
FAKE_STAT = """#!/usr/bin/env bash
for a in "$@"; do last=$a; done
if [[ "$1" == "-f" && "$2" == "%Sf" && "$last" == */"$DATALESS" ]]; then
  echo "$FLAGS"
  exit 0
fi
exec /usr/bin/stat "$@"
"""


@pytest.mark.parametrize("flags", ["dataless", "compressed,dataless"])
def test_a_list_still_in_icloud_is_not_staged_and_is_one_log_line(tmp_path: Path, flags: str):
    """Reading a dataless file makes iCloud download it first: the morning run does not
    wait on that, it goes without the list."""
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    obsidian = _obsidian(tmp_path)
    before = _snapshot(obsidian)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "stat").write_text(FAKE_STAT)
    (bin_dir / "stat").chmod(0o755)
    env |= {
        "PATH": f"{bin_dir}:{env['PATH']}",
        "DATALESS": "workspace-mobile.json",
        "FLAGS": flags,
        "STAGE_SNAPSHOT": str(tmp_path / "snapshot"),
    }
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    assert [p.name for p in (tmp_path / "snapshot").iterdir()] == ["workspace.json"]
    (text,) = [t for _, t in _timed(out.stderr)]
    assert len(out.stderr.splitlines()) == 1
    assert text.startswith(".obsidian/workspace-mobile.json not staged: ") and "iCloud" in text
    assert _messages(notified) == []
    assert _snapshot(obsidian) == before
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"  # the run did run


def test_a_vault_without_obsidian_is_not_a_failure(tmp_path: Path):
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0 and out.stderr == ""
    assert _messages(notified) == []
    assert not (tmp_path / "store" / "vault-stage" / ".obsidian").exists()
    assert not (vault.parent / ".obsidian").exists()


def test_a_list_that_cannot_be_staged_is_one_log_line_and_the_run_goes_on(tmp_path: Path):
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    _obsidian(tmp_path)
    staged = tmp_path / "store" / "vault-stage" / ".obsidian"
    staged.mkdir(parents=True)
    staged.chmod(0o555)  # the stage refuses the copies
    try:
        out = subprocess.run(
            ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
        )
    finally:
        staged.chmod(0o755)
    assert out.returncode == 0
    assert _messages(notified) == []
    texts = [t for _, t in _timed(out.stderr)]
    assert len(texts) == len(out.stderr.splitlines()) == 2  # one line per list, nothing else
    assert texts[0].startswith(".obsidian/workspace.json not staged: ")
    assert texts[1].startswith(".obsidian/workspace-mobile.json not staged: ")
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"  # the run did run


# --- Monday's weekly review ---------------------------------------------------------------

# date stand-in: `date +%u` prints $WEEKDAY (1 = Monday), the rest asks the real date.
FAKE_DATE = """#!/usr/bin/env bash
if [[ "$*" == "+%u" ]]; then echo "$WEEKDAY"; exit 0; fi
exec /bin/date "$@"
"""


def _monday(env: dict[str, str]) -> None:
    env["JRP_WBR_DUE"] = "1"


@pytest.mark.parametrize("form", ["uv", "installed"])
def test_on_monday_the_review_follows_the_morning_notes_into_the_vault(tmp_path: Path, form: str):
    """The morning's notes reach the vault first; then `jrp wbr` runs on the stage (the fake
    fails unless it sees the stage) and a second copy takes its note, and only its note: last
    week's review, staged with the notes, is not copied back."""
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    if form == "installed":
        env["JRP_BIN"] = str(_installed(tmp_path))
    last_week = vault / "2026-09-21_jrp_wbr.md"
    last_week.write_text("last week\n")
    old = time.time() - 7 * 86400
    os.utime(last_week, (old, old))
    _monday(env)
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    assert (vault / WBR_NOTE).read_text() == "review\n"
    assert last_week.read_text() == "last week\n"
    texts = [t for _, t in _timed(out.stdout)]
    start = texts.index("start jrp wbr")
    assert re.fullmatch(r"end jrp run status 0 · \d+ s", texts[2])
    assert sorted(texts[3:start]) == [
        "vault ← 2026-09-24_jrp_aap.md",
        "vault ← 2026-09-24_jrp_akc.md",
    ]
    assert re.fullmatch(r"end jrp wbr status 0 · \d+ s", texts[start + 1])
    assert texts[start + 2 :] == [f"vault ← {WBR_NOTE}"]
    lines = out.stdout.splitlines()
    morning = max(i for i, ln in enumerate(lines) if "vault ← 2026-09-24_" in ln)
    assert morning < lines.index("fake wbr")  # delivered before the review started
    assert _messages(notified) == [] and out.stderr == ""


@pytest.mark.parametrize(
    ("due", "weekday", "called"),
    [("0", "1", False), ("1", "3", True), (None, "3", False), (None, "1", True)],
)
def test_the_review_is_due_on_monday_unless_jrp_wbr_due_says_otherwise(
    tmp_path: Path, due: str | None, weekday: str, called: bool
):
    env, vault, _ = _setup(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "date").write_text(FAKE_DATE)
    (bin_dir / "date").chmod(0o755)
    env |= {"PATH": f"{bin_dir}:{env['PATH']}", "WEEKDAY": weekday}
    if due is None:
        del env["JRP_WBR_DUE"]
    else:
        env["JRP_WBR_DUE"] = due
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    assert ("fake wbr" in out.stdout) is called
    assert ("start jrp wbr" in out.stdout) is called
    assert (vault / WBR_NOTE).exists() is called
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"


def test_a_hung_review_is_killed_by_its_own_timeout_after_the_morning_reached_the_vault(
    tmp_path: Path,
):
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    _monday(env)
    env |= {"WBR": "hang", "WBR_PID": str(tmp_path / "wbr.pid"), "JRP_WBR_TIMEOUT_S": "1"}
    started = time.monotonic()
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert time.monotonic() - started < 20  # not the 30 s the child would have slept
    assert out.returncode == 0  # the run's status: the morning's notes are in the vault
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"
    assert not (vault / WBR_NOTE).exists()
    ((title, body),) = _messages(notified)
    assert title == "jrp wbr TIMED OUT"
    assert "1 s awake (JRP_WBR_TIMEOUT_S)" in body and "0 note" in body
    (end,) = [t for _, t in _timed(out.stdout) if t.startswith("end jrp wbr")]
    assert re.fullmatch(r"end jrp wbr status (?!0 )\d+ · \d+ s", end)
    child = int((tmp_path / "wbr.pid").read_text())
    with pytest.raises(ProcessLookupError):  # the whole process group, not only uv
        os.kill(child, 0)


@pytest.mark.parametrize("run_status", [0, 5])
def test_a_failing_review_is_notified_and_the_job_exits_with_the_runs_status(
    tmp_path: Path, run_status: int
):
    """A run that exited non-zero still gets its review (python reported the run itself),
    and a note the review wrote before failing still reaches the vault."""
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    _monday(env)
    env |= {"WBR": "fail", "RUN_STATUS": str(run_status)}
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == run_status
    assert (vault / WBR_NOTE).read_text() == "review\n"
    ((title, body),) = _messages(notified)
    assert title == "jrp wbr FAILED" and body.startswith("exit 3, see the log")


def test_a_review_note_that_cannot_reach_the_vault_is_notified(tmp_path: Path):
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    blocked = vault / WBR_NOTE
    blocked.write_text("old\n")
    blocked.chmod(0o444)  # the vault copy of the review refuses the write
    _monday(env)
    try:
        out = subprocess.run(
            ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
        )
    finally:
        blocked.chmod(0o644)
    assert out.returncode == 0
    assert blocked.read_text() == "old\n"
    ((title, body),) = _messages(notified)
    assert title == "jrp wbr FAILED" and body.endswith(f"/daily-research): {WBR_NOTE}")


def test_a_killed_run_gets_no_weekly_review(tmp_path: Path):
    env, vault, _ = _setup(tmp_path)
    (tmp_path / "uv").write_text(HUNG_UV)
    notified = _with_notify(tmp_path, env)
    _monday(env)
    env |= {"JRP_RUN_TIMEOUT_S": "1", "HUNG_PID": str(tmp_path / "hung.pid")}
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 124
    assert "fake wbr" not in out.stdout and "start jrp wbr" not in out.stdout
    assert not (vault / WBR_NOTE).exists()
    assert [title for title, _ in _messages(notified)] == ["jrp run TIMED OUT"]


def test_a_review_timeout_that_is_not_a_number_skips_the_review_only(tmp_path: Path):
    """The run's JRP_RUN_TIMEOUT_S stops the morning before python starts; the review's
    stops only the review, after the morning's notes reached the vault."""
    env, vault, _ = _setup(tmp_path)
    notified = _with_notify(tmp_path, env)
    _monday(env)
    env["JRP_WBR_TIMEOUT_S"] = "10m"
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"
    assert "fake wbr" not in out.stdout and not (vault / WBR_NOTE).exists()
    ((title, body),) = _messages(notified)
    assert title == "jrp wbr FAILED"
    assert body.startswith("JRP_WBR_TIMEOUT_S is not a number of seconds: 10m;")


def test_the_run_keeps_the_mac_awake_until_the_wrapper_exits(tmp_path: Path):
    """launchd starts the 05:00 job in a dark wake of seconds; without an assertion the run
    moved only in the next dark wakes and was killed (2026-10-21). caffeinate holds -i and -s
    for the wrapper's own pid (-w), so the assertion ends with the job."""
    env, _, _ = _setup(tmp_path)
    seen = tmp_path / "caffeinate.args"
    fake = tmp_path / "caffeinate"
    fake.write_text(
        f'#!/bin/bash\nprintf "%s\\n" "$*" > "{seen}.tmp" && mv "{seen}.tmp" "{seen}"\n'
    )
    fake.chmod(0o755)
    env["JRP_CAFFEINATE"] = str(fake)
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    texts = [text for _, text in _timed(out.stdout)]
    assert texts[0] == "caffeinate: the Mac stays awake until the job ends"
    for _ in range(50):  # the fake runs in the background; give it a moment to write
        if seen.exists():
            break
        time.sleep(0.1)
    args = seen.read_text().split()
    assert args[:3] == ["-i", "-s", "-w"] and args[3].isdigit()


def test_no_caffeinate_holds_nothing_and_says_nothing(tmp_path: Path):
    env, _, _ = _setup(tmp_path)
    env["JRP_CAFFEINATE"] = str(tmp_path / "no-such-caffeinate")  # not macOS
    out = subprocess.run(
        ["bash", str(SCRIPT), "run"], env=env, capture_output=True, text=True, check=True
    )
    assert not any("caffeinate" in text for _, text in _timed(out.stdout))


def test_the_watchdog_counts_awake_seconds_not_the_wall_clock():
    """A Mac asleep through the morning runs no tick of the watchdog's loop: the limit is
    reached by ticks, never by SECONDS (bash's wall clock, which counts the sleep)."""
    text = SCRIPT.read_text(encoding="utf-8")
    body = text[text.index("limited() {") : text.index("send_back() {")]
    assert "awake=$((awake + 1))" in body and "((awake >= limit))" in body
    assert "SECONDS" not in body


def test_a_run_paused_like_a_sleeping_mac_is_not_killed_for_the_pause(tmp_path: Path):
    """SIGSTOP stands in for a sleeping Mac: no tick runs while the wrapper is stopped. A
    wall-clock deadline (bash SECONDS) killed the run the moment the wrapper resumed."""
    env, vault, _ = _setup(tmp_path)
    env |= {"JRP_RUN_TIMEOUT_S": "4", "RUN_SLEEP": "6"}
    proc = subprocess.Popen(
        ["bash", str(SCRIPT), "run"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:  # pause the wrapper once the run is going, not while it stages
        if line.endswith(" start jrp run\n"):
            break
    time.sleep(0.5)
    proc.send_signal(signal.SIGSTOP)
    time.sleep(5.0)  # past the 4 s limit on the wall clock
    proc.send_signal(signal.SIGCONT)
    _, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    assert "TIMED OUT" not in err
    assert (vault / "2026-09-24_jrp_aap.md").read_text() == "new\n"
