# launchd jobs (not loaded by the build)

| plist | when | runs |
|---|---|---|
| `com.shimo4228.jrp.run.plist` | daily 05:00 | `jrp run` — harvest ticks, then the next lines in rotation |
| `com.shimo4228.jrp.drift.plist` | Monday 05:30 | `jrp drift` — live replay of recorded Jev inputs |

Both call `scripts/launchd-jrp.sh`, which reads secrets from `~/.config/jrp/env` (outside
the repo). To start the parallel run:

```bash
cp launchd/com.shimo4228.jrp.*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.shimo4228.jrp.run.plist
launchctl load ~/Library/LaunchAgents/com.shimo4228.jrp.drift.plist
```
