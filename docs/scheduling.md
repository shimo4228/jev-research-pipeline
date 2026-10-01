# Scheduling the daily run

jrp is meant to run once a day, early, so the note is waiting when you sit down. Nothing is
scheduled for you: jrp writes the job, you load it.

## macOS (launchd)

```bash
uv tool install <path to this repo or the package>   # so `jrp` has a stable path
jrp schedule install --hour 5 --minute 0
```

`jrp schedule install` writes, each only if missing, `~/.config/jrp/launchd/launchd-jrp.sh`
(the wrapper) and `~/.config/jrp/launchd/local.jrp.run.plist` (runs the wrapper daily at the
given time, with `JRP_BIN` naming this `jrp` and `JRP_ENV_FILE` naming `~/.config/jrp/env`),
then prints the two commands that load it:

```bash
cp ~/.config/jrp/launchd/local.jrp.run.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.jrp.run.plist
```

The wrapper sources the env file, copies the vault's jrp notes to a local stage (macOS privacy
guards a vault in iCloud Drive per executable), runs `jrp doctor` and then `jrp run` under a
watchdog (`JRP_RUN_TIMEOUT_S`, default 3600 s), copies back the notes the run wrote, and reports
what python cannot (a hung run, a wrapper that stops before jrp starts) through the channels
below. Its log is `~/Library/Logs/jrp-run.log`. Details: [launchd/README.md](../launchd/README.md).

## Linux (cron or systemd)

The launchd wrapper's staging exists for macOS privacy; on Linux run `jrp run` directly. cron:

```cron
# m h dom mon dow
0 5 * * * set -a; . "$HOME/.config/jrp/env"; set +a; "$HOME/.local/bin/jrp" run >>"$HOME/.local/state/jrp-run.log" 2>&1
```

systemd (user units):

```ini
# ~/.config/systemd/user/jrp.service
[Service]
Type=oneshot
EnvironmentFile=%h/.config/jrp/env
ExecStart=%h/.local/bin/jrp run
TimeoutStartSec=3600

# ~/.config/systemd/user/jrp.timer
[Timer]
OnCalendar=*-*-* 05:00
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now jrp.timer
```

`EnvironmentFile` reads `KEY=value` lines; quote-free values are the safe form there.

## Notifications

Each `jrp run` sends one message (the claims per line, or `DEGRADED` / `FAILED` with the
reason) to every channel the env names; none is required.

| variable | channel |
|---|---|
| `JRP_SLACK_WEBHOOK_URL` | a Slack Incoming Webhook (the URL is a secret: keep it in the env file; jrp never prints it or puts it in a trace) |
| `JRP_NOTIFY_MACOS=1` | macOS Notification Center |
| `JRP_SLACK_NOTIFY=1` | the author's own script, `~/.claude/scripts/notify-slack.sh <title> <body>` |

`jrp notify <title> <body>` sends one by hand, which is a quick way to check a webhook.

## Reading the notes outside Obsidian

The notes are plain Markdown written for Obsidian. In another viewer (GitHub, VS Code, any
CommonMark renderer) they read the same, with two differences: the folded claim list
`> [!note]- Claims` shows as an ordinary quote block whose first line is `[!note]- Claims`, and
a tick written as `- [-]` (incorrect) shows as the text `[-]` instead of a checkbox. Ticks are
read back from the text itself, so they work from any editor.
