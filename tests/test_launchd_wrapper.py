"""scripts/launchd-jrp.sh stages the vault for `jrp run`: python must never open the
iCloud vault under launchd (TCC), so bash copies notes in and the run's notes back out.
It also reports what python cannot: a run that hangs (the watchdog) and a wrapper that
fails before python starts."""

import os
import subprocess
import time
from pathlib import Path

import pytest

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

# A stand-in for uv: asserts it was pointed at the stage, harvests (reads) a staged note,
# rewrites one note and writes a new one — what `jrp run` does to the vault dir.
FAKE_UV = f"""#!/usr/bin/env bash
set -euo pipefail
{DOCTOR}
notes="$JRP_VAULT_DIR/daily-research"
[[ "$JRP_VAULT_DIR" == "$EXPECT_STAGE" ]] || {{ echo "vault not staged: $JRP_VAULT_DIR"; exit 9; }}
grep -q "[x]" "$notes/2026-09-23_jrp_akc.md"
echo "rewritten" > "$notes/2026-09-24_jrp_akc.md"
echo "new" > "$notes/2026-09-24_jrp_aap.md"
if [[ -n "${{WRITE_ANS:-}}" ]]; then  # a note whose vault copy is read-only
  rm -f "$notes/2026-09-24_jrp_ans.md"
  echo "ans" > "$notes/2026-09-24_jrp_ans.md"
fi
echo "args: $*"
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
echo "partial" > "$JRP_VAULT_DIR/daily-research/2026-09-24_jrp_akc.md"
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


def test_an_installed_jrp_is_started_directly_and_notifies_through_python(tmp_path: Path):
    """JRP_BIN (written by `jrp schedule install`): the wrapper starts that jrp, not uv in a
    checkout, and a webhook / Notification Center message goes through `jrp notify`."""
    env, vault, _ = _setup(tmp_path)
    jrp = tmp_path / "jrp"
    # the fake uv, called as `jrp <args>`; `jrp notify` appends to $NOTIFIED
    jrp.write_text(
        FAKE_UV.replace('" jrp doctor "', '" doctor "').replace(
            "set -euo pipefail\n",
            'set -euo pipefail\n[[ "$1" == notify && "$2" == -- ]] && { printf "%s|%s\\n" "$3" "$4" >> "$NOTIFIED"; exit 0; }\n',
            1,
        )
    )
    jrp.chmod(0o755)
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
