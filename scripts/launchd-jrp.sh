#!/usr/bin/env bash
# launchd entry for `jrp <command>` (run | drift). Not loaded by the build — a human runs
# `launchctl load` (see launchd/README.md). Secrets live outside the repo in
# ~/.config/jrp/env (KEY=value lines: JRP_VAULT_DIR, JRP_STORE_DIR, TYPESAFE_API_KEY,
# DASHSCOPE_API_KEY, optional TAVILY_API_KEY / GITHUB_TOKEN / JRP_COST_CAP_USD /
# JRP_SLACK_NOTIFY / JRP_DRIFT_LIVE). The repo never holds them.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${HOME}/.config/jrp/env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi
cd "$REPO"
exec "${HOME}/.local/bin/uv" run --project "$REPO" --frozen jrp "$@"
