# launchd jobs (not loaded by the build)

| plist | when | runs |
|---|---|---|
| `com.shimo4228.jrp.run.plist` | daily 05:00 | `jrp run` — harvest ticks, then the next lines in rotation |
| `com.shimo4228.jrp.drift.plist` | Monday 05:30 | `jrp drift` — live replay of recorded Jev inputs |

Both call `scripts/launchd-jrp.sh`, which reads secrets from `~/.config/jrp/env` (outside
the repo). The default prose model (`openai-codex:gpt-6-luna`) also needs the pipeline's own
ChatGPT login: run `uv run jrp codex login` once in a terminal on this Mac before the first
scheduled run (it writes `~/.config/jrp/codex-auth.json`; without it `jrp run` stops at the
start and says so). To start the parallel run:

```bash
cp launchd/com.shimo4228.jrp.*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.shimo4228.jrp.run.plist
launchctl load ~/Library/LaunchAgents/com.shimo4228.jrp.drift.plist
```

The vault is in iCloud Drive, which macOS privacy (TCC) guards per executable: under launchd
`/bin/bash` may open it, the uv-managed python may not (its `open()` waits on an invisible
consent prompt, and its path changes with each Python patch release). So for `jrp run` the
wrapper copies the vault's `*_jrp_*.md` notes into `<JRP_STORE_DIR>/vault-stage/`, points
`JRP_VAULT_DIR` there, and afterwards copies back only the notes the run wrote. A tick made
during the run is harvested the next morning. Nothing in the vault is deleted.

The wrapper also reports what Python cannot (to the log, and to Slack when `JRP_SLACK_NOTIFY=1`,
through the same `~/.claude/scripts/notify-slack.sh`). A `jrp run` still going after
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
