# launchd jobs (not loaded by the build)

| plist | when | runs |
|---|---|---|
| `com.shimo4228.jrp.run.plist` | daily 05:00 | `jrp run` — harvest ticks, then the next lines in rotation |
| `com.shimo4228.jrp.drift.plist` | Monday 05:30 | `jrp drift` — live replay of recorded Jev inputs |

Both call `scripts/launchd-jrp.sh`, which reads secrets from `~/.config/jrp/env` (outside
the repo). The default prose model (`openai-codex:gpt-5.6-sol`) also needs the pipeline's own
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
