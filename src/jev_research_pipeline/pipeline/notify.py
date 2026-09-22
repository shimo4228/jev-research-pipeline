"""Slack one-liner through the harness script (~/.claude/scripts/notify-slack.sh
"<title>" "<body>"). Sent only when JRP_SLACK_NOTIFY=1; the runner is injectable so
tests never call the real script. Arguments are passed as a list — no shell parsing."""

import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

NOTIFY_ENV: Final = "JRP_SLACK_NOTIFY"
SCRIPT: Final = Path.home() / ".claude" / "scripts" / "notify-slack.sh"

type Runner = Callable[[list[str]], object]


def _run(cmd: list[str]) -> object:
    return subprocess.run(cmd, check=False, timeout=30)


def notify(title: str, body: str, *, env: Mapping[str, str], runner: Runner = _run) -> bool:
    if env.get(NOTIFY_ENV) != "1":
        return False
    runner(["bash", str(SCRIPT), title, body])
    return True
