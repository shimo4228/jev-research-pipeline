#!/usr/bin/env bash
# launchd entry for `jrp <command>` (run | drift). A human loads the jobs (launchd/README.md).
# Secrets live outside the repo in ~/.config/jrp/env (KEY=value lines: JRP_VAULT_DIR,
# JRP_STORE_DIR, TYPESAFE_API_KEY, optional JRP_PROSE_MODEL / DASHSCOPE_API_KEY (for a
# dashscope: model) / TAVILY_API_KEY / GITHUB_TOKEN / JRP_COST_CAP_USD / JRP_SLACK_NOTIFY /
# JRP_DRIFT_LIVE) and, for the default prose model, the login `jrp codex login` wrote to
# ~/.config/jrp/codex-auth.json. The repo never holds them.
#
# The vault lives in iCloud Drive, which macOS privacy (TCC) guards per executable. Under
# launchd, /bin/bash may open it but the uv-managed python may not: its open() waits on an
# invisible consent prompt forever (2026-09-24 05:00, the first scheduled run hung for 80
# min), and its path changes with every Python patch release, so a grant would not last.
# So bash stages the notes: before `jrp run` it copies the vault's jrp notes (the author's
# ticks are in them) to a local stage, python reads and writes only the stage, and after
# the run bash copies back the notes the run wrote. Nothing in the vault is deleted, and a
# note the run did not touch is not copied back (an edit made during the run survives).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${JRP_ENV_FILE:-${HOME}/.config/jrp/env}"
UV="${JRP_UV:-${HOME}/.local/bin/uv}"  # both overridable for tests/test_launchd_wrapper.py
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi
cd "$REPO"

if [[ "${1:-}" != "run" ]]; then
  exec "$UV" run --project "$REPO" --frozen jrp "$@"
fi

NOTES="daily-research"
VAULT="${JRP_VAULT_DIR:?JRP_VAULT_DIR is not set}"
STAGE="${JRP_VAULT_STAGE:-${JRP_STORE_DIR:?JRP_STORE_DIR is not set}/vault-stage}"
mkdir -p "$STAGE/$NOTES" "$VAULT/$NOTES"

# vault -> stage: every jrp note, so the harvest sees the author's ticks
rsync -a --include='*_jrp_*.md' --exclude='*' "$VAULT/$NOTES/" "$STAGE/$NOTES/"

MARK="$(mktemp "${TMPDIR:-/tmp}/jrp-run-mark.XXXXXX")"
trap 'rm -f "$MARK"' EXIT
set +e
JRP_VAULT_DIR="$STAGE" "$UV" run --project "$REPO" --frozen jrp "$@"
status=$?
set -e

# stage -> vault: only the notes this run wrote (newer than the mark)
find "$STAGE/$NOTES" -name '*_jrp_*.md' -newer "$MARK" -print0 |
  while IFS= read -r -d '' note; do
    cp -p "$note" "$VAULT/$NOTES/"
    echo "vault ← $(basename "$note")"
  done
exit "$status"
