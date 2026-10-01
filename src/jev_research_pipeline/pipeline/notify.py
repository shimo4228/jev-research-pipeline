"""One-message notifications of a run's result, to whichever channels the environment names
(any number of them, each best-effort — a failed notification never fails the run):

    JRP_SLACK_WEBHOOK_URL=<url>  POST {"text": ...} to a Slack Incoming Webhook
    JRP_NOTIFY_MACOS=1           macOS Notification Center (osascript)
    JRP_SLACK_NOTIFY=1           the author's harness script, ~/.claude/scripts/notify-slack.sh
                                 "<title>" "<body>"

`jrp notify <title> <body>` sends one the same way; the launchd wrapper uses it for what
python cannot report. Commands are argument lists (no shell), the webhook URL is never
printed, and the runner and the poster are injectable so tests never reach the network.
"""

import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

import httpx2
from opentelemetry.instrumentation.utils import suppress_instrumentation

NOTIFY_ENV: Final = "JRP_SLACK_NOTIFY"
WEBHOOK_ENV: Final = "JRP_SLACK_WEBHOOK_URL"
MACOS_ENV: Final = "JRP_NOTIFY_MACOS"
SCRIPT: Final = Path.home() / ".claude" / "scripts" / "notify-slack.sh"
TIMEOUT_S: Final = 30.0

# osascript reads the title and the body as arguments: nothing of either is AppleScript.
OSASCRIPT: Final = (
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "end run",
)

type Runner = Callable[[list[str]], object]
type Poster = Callable[[str, dict[str, str]], object]


def _run(cmd: list[str]) -> object:
    """Best-effort like every channel: a missing program (osascript off macOS) or a hung one
    is a line on stderr, never the end of a run that already wrote its notes."""
    try:
        return subprocess.run(cmd, check=False, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.stderr.write(f"notify: {cmd[0]} failed ({type(e).__name__})\n")
        return None


def _post(url: str, payload: dict[str, str]) -> object:
    # The webhook's path is its secret: no HTTP span (telemetry.py) may carry the URL.
    with suppress_instrumentation():
        return httpx2.post(url, json=payload, timeout=TIMEOUT_S)


def _slack_text(text: str) -> str:
    """Slack's own escaping: `<!channel>` or `<url|label>` in a failure message stay text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def notify(
    title: str,
    body: str,
    *,
    env: Mapping[str, str],
    runner: Runner = _run,
    poster: Poster = _post,
) -> bool:
    """True when at least one channel was configured (and tried)."""
    sent = False
    if url := env.get(WEBHOOK_ENV):
        sent = True
        try:
            poster(url, {"text": f"*{_slack_text(title)}*\n{_slack_text(body)}"})
        except Exception as e:
            sys.stderr.write(f"notify: Slack webhook failed ({type(e).__name__})\n")
    if env.get(MACOS_ENV) == "1":
        sent = True
        # `--`: a title that starts with "-" is not an osascript option
        runner(["osascript", *(a for line in OSASCRIPT for a in ("-e", line)), "--", title, body])
    if env.get(NOTIFY_ENV) == "1":
        sent = True
        runner(["bash", str(SCRIPT), title, body])
    return sent
