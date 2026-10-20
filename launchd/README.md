# launchd jobs (not loaded by the build)

These two plists are the author's (this checkout, run through uv). For any other install,
`jrp schedule install` writes a job for that machine: [docs/scheduling.md](../docs/scheduling.md).

| plist | when | runs |
|---|---|---|
| `com.shimo4228.jrp.run.plist` | daily 05:00 | `jrp run` — harvest ticks, then the next lines in rotation; on Monday then `jrp wbr`, the weekly review |
| `com.shimo4228.jrp.drift.plist` | Monday 05:30 — **stopped** | `jrp drift` — live replay of recorded Jev inputs |

The Monday drift job is stopped until a fixed replay probe exists (author's decision,
2026-10-20). No live cassette was ever recorded, so the job could only stop at its gate or
compare nothing. Its plist stays in the repo for when the probe replaces it, and the commands
below copy only the run plist. If the drift job is loaded on this Mac, unload it and take its
plist out of `~/Library/LaunchAgents/` (a plist left there is loaded again at the next login;
the repo keeps the original):

```bash
launchctl bootout gui/$(id -u)/com.shimo4228.jrp.drift
mv ~/Library/LaunchAgents/com.shimo4228.jrp.drift.plist ~/.Trash/
```

`jrp drift` by hand still works with `JRP_DRIFT_LIVE=1`, and exits non-zero when it compared
no answer (no cassette dir, no `*.json` in it, or no replay answered).

Both plists call `scripts/launchd-jrp.sh`, which reads secrets from `~/.config/jrp/env` (outside
the repo). The default prose model (`openai-codex:gpt-6-luna`) also needs the pipeline's own
ChatGPT login: run `uv run jrp codex login` once in a terminal on this Mac before the first
scheduled run (it writes `~/.config/jrp/codex-auth.json`; without it `jrp run` stops at the
start and says so). To start the parallel run:

```bash
cp launchd/com.shimo4228.jrp.run.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.shimo4228.jrp.run.plist
```

The vault is in iCloud Drive, which macOS privacy (TCC) guards per executable: under launchd
`/bin/bash` may open it, the uv-managed python may not (its `open()` waits on an invisible
consent prompt, and its path changes with each Python patch release). So for `jrp run` the
wrapper copies the vault's `*_jrp_*.md` notes into `<JRP_STORE_DIR>/vault-stage/`, points
`JRP_VAULT_DIR` there, and afterwards copies back only the notes the run wrote. A tick made
during the run is harvested the next morning. Nothing in the vault is deleted.

It also copies Obsidian's two lists of recently opened files, `.obsidian/workspace.json` and
`.obsidian/workspace-mobile.json` (nothing else of `.obsidian`: not the app settings, not iCloud's
`workspace 2.json` conflict copies), into the stage's `.obsidian/`. The run keeps from them only
the names of jrp notes, each with the day it was first seen, in
`<JRP_STORE_DIR>/metrics/opened.jsonl` (`reduction/opened.py`). The copies hold every file name on
the lists, so they are in the stage only while `jrp run` runs: the wrapper removes them when the
run returns, is killed by the timeout or gets a TERM, and before it stages new ones it removes any
that a killed wrapper (SIGKILL) left. These copies never go back to the vault. A stage that
is the vault's directory, or whose `.obsidian` is the vault's, stops the wrapper before it
removes or copies anything (`jrp run FAILED`). The test is the inode (`-ef`), not the path, so a
symlink, a name that differs only in case (`…/Vault` on case-insensitive APFS) and the same folder
reached through the Data volume's firmlink are all caught. A list that iCloud has not downloaded to this Mac
(dataless) is not copied that morning, because the copy would wait for the download. A vault
without `.obsidian` is skipped quietly. A copy that fails, or a list left in iCloud, is one line in
the log, never a message or a stop.

The wrapper also reports what Python cannot (to the log, and to Slack when `JRP_SLACK_NOTIFY=1`,
through the same `~/.claude/scripts/notify-slack.sh`, with `&`, `<` and `>` escaped as Python
escapes its own Slack messages, so a `<!channel>` in a reason stays text). A `jrp run` still going after
`JRP_RUN_TIMEOUT_S` seconds (default 3600; a normal run takes 15 to 20 minutes) gets SIGTERM
(Python cancels the run, which also stops a `claude -p` it started), then its whole process group
is killed 10 s later; the notes it wrote before the kill are copied back, and the message is
`jrp run TIMED OUT` (exit 124). A note that cannot be copied to the vault is named in a
`jrp run FAILED` message and stays in the stage. If the wrapper itself stops before Python starts (uv missing,
`JRP_VAULT_DIR` unset, the staging copy failing), the message is `jrp run FAILED` with the reason.

Before each `jrp run` the wrapper runs `jrp doctor` (limited to 120 s) and writes its lines to
the log, so the morning log shows whether the launchd job could reach the writer's login — Claude
Code's lives in the macOS keychain, which a launchd job may not be allowed to read. A failing
doctor sends `jrp doctor FAILED` with its `FAIL` lines; the run still goes ahead.

On Monday (`date +%u` is 1) the same job then makes the weekly review. Once the morning's notes
are in the vault, and only when the run was not killed, the wrapper runs `jrp wbr` on the stage
(Python still never opens the iCloud vault) under its own limit, `JRP_WBR_TIMEOUT_S` (default
600 s), and copies its note, `<Monday>_jrp_wbr.md`, to the vault in a second copy that takes
nothing else. A review that exits non-zero or whose note cannot be copied sends `jrp wbr FAILED`,
one past its limit is killed with its process group and sends `jrp wbr TIMED OUT`, and a
`JRP_WBR_TIMEOUT_S` that is not a number sends `jrp wbr FAILED` and skips only the review. None
of them stops the morning or changes the job's exit status, which stays the run's. A Monday
whose run does not happen gets no review that week; `jrp wbr --week YYYY-Www` makes it by hand.
With `ANTHROPIC_API_KEY` in `~/.config/jrp/env`, the review's monitoring judge calls the Claude API
(`JRP_MONITOR_WEEKLY_USD` a week, default $5) and gives up after 300 s, inside that limit; its
stops (a 429, spent credits, a refused key, the cap) show in the note as "not measured", not as a
notification.

Every line the wrapper writes to the log starts with the local time (`2026-10-21T05:00:02+0900`),
on stdout or stderr as before, and `jrp run` sits between `start jrp run` and
`end jrp run status <exit status> · <seconds> s` (Monday's `jrp wbr` between `start jrp wbr` and
`end jrp wbr status <exit status> · <seconds> s`). In between, Python's own lines start and end
with `pipeline start` and `pipeline end · <seconds> s` at Python's own times: its output reaches
the log in buffered chunks, so a time the wrapper put in front of it would be the flush's.
