#!/usr/bin/env bash
# launchd entry for `jrp <command>` (run | drift). A human loads the jobs (launchd/README.md).
# Secrets live outside the repo in ~/.config/jrp/env (KEY=value lines: JRP_VAULT_DIR,
# JRP_STORE_DIR, TYPESAFE_API_KEY, optional JRP_PROSE_MODEL / DASHSCOPE_API_KEY (for a
# dashscope: model) / TAVILY_API_KEY / GITHUB_TOKEN / JRP_COST_CAP_USD / JRP_SLACK_NOTIFY /
# JRP_RUN_TIMEOUT_S / JRP_DRIFT_LIVE) and, for the default prose model, the login
# `jrp codex login` wrote to ~/.config/jrp/codex-auth.json. The repo never holds them.
#
# The vault lives in iCloud Drive, which macOS privacy (TCC) guards per executable. Under
# launchd, /bin/bash may open it but the uv-managed python may not: its open() waits on an
# invisible consent prompt forever (2026-09-24 05:00, the first scheduled run hung for 80
# min), and its path changes with every Python patch release, so a grant would not last.
# So bash stages the notes: before `jrp run` it copies the vault's jrp notes (the author's
# ticks are in them) to a local stage, python reads and writes only the stage, and after
# the run bash copies back the notes the run wrote. Nothing in the vault is deleted, and a
# note the run did not touch is not copied back (an edit made during the run survives).
#
# What python cannot report, this script does (Slack only when JRP_SLACK_NOTIFY=1, through
# the same harness script as pipeline/notify.py; the log always): a run past
# JRP_RUN_TIMEOUT_S (default 3600 s; a normal run takes ~15-20 min) is killed with its whole
# process group — the notes it wrote so far are still copied back — and a wrapper that
# fails before python starts (env, uv missing, staging) says so instead of exiting unseen.
# Before `jrp run` it runs `jrp doctor` (pipeline/doctor.py) under the same watchdog and logs
# its lines, so the log shows whether launchd could reach the writer's login (Claude Code's
# sits in the keychain); a failing doctor is notified and the run still goes ahead.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${JRP_ENV_FILE:-${HOME}/.config/jrp/env}"
UV="${JRP_UV:-${HOME}/.local/bin/uv}"  # both overridable for tests/test_launchd_wrapper.py
NOTIFY_SCRIPT="${HOME}/.claude/scripts/notify-slack.sh"
CMD="${1:-}"
STARTED=0  # 1 once jrp is started: from then on python (or the watchdog) reports
WHY=""
MARK=""
DOCTOR_OUT=""
DOCTOR_TIMEOUT_S=120  # the doctor answers in seconds; a keychain prompt nobody sees never does
TIMED_OUT=0

notify() {  # notify <title> <body>: the log always, Slack when JRP_SLACK_NOTIFY=1
  echo "$1: $2" >&2
  if [[ "${JRP_SLACK_NOTIFY:-}" == "1" ]]; then
    bash "$NOTIFY_SCRIPT" "$1" "$2" || echo "slack notify failed" >&2
  fi
}

die() {  # die <why>: stop before jrp starts; on_exit notifies with the reason
  WHY="$1"
  echo "$1" >&2
  exit 1
}

# limited <seconds> <cmd...>: cmd as a job of its own process group (job control on for it),
# so a kill reaches uv's python and whatever it started, not only uv. Past <seconds> the
# group gets TERM, then KILL 10 s later. Sets TIMED_OUT; returns cmd's exit status.
CHILD=""  # the job limited() is running: a TERM to the wrapper is passed on to its group
limited() {
  local limit=$1 pid
  shift
  TIMED_OUT=0
  set -m
  "$@" </dev/null &
  pid=$!
  CHILD=$pid
  set +m
  local deadline=$((SECONDS + limit))
  while kill -0 "$pid" 2>/dev/null; do
    if ((SECONDS >= deadline)); then
      TIMED_OUT=1
      kill -TERM -- "-$pid" 2>/dev/null
      for _ in 1 2 3 4 5 6 7 8 9 10; do  # until the whole group is gone: python unwinds
        kill -0 -- "-$pid" 2>/dev/null || break  # after uv may already have exited
        sleep 1
      done
      kill -KILL -- "-$pid" 2>/dev/null
      break
    fi
    sleep 1
  done
  wait "$pid"
  local status=$?
  CHILD=""
  return "$status"
}

# A TERM to the wrapper (launchctl, a shutdown) would otherwise orphan the job: it sits in
# a process group of its own, which launchd's cleanup of the wrapper's group never reaches,
# and it would go on spending the prose plan with nothing to copy its notes back.
# shellcheck disable=SC2329  # called by the TERM trap
on_term() {
  if [[ -n "$CHILD" ]]; then kill -TERM -- "-$CHILD" 2>/dev/null; fi
  exit 143
}
trap on_term TERM

# shellcheck disable=SC2329  # called by the EXIT trap
on_exit() {
  local status=$?
  if [[ -n "$MARK" ]]; then rm -f "$MARK"; fi
  if [[ -n "$DOCTOR_OUT" ]]; then rm -f "$DOCTOR_OUT"; fi
  if ((status != 0 && STARTED == 0)); then
    notify "jrp ${CMD} FAILED" "launchd-jrp.sh stopped before jrp started: ${WHY:-exit ${status}, see the log}"
  fi
}
trap on_exit EXIT

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi
cd "$REPO"
[[ -x "$UV" ]] || die "uv not found at ${UV} (JRP_UV)"

if [[ "$CMD" != "run" ]]; then
  STARTED=1
  exec "$UV" run --project "$REPO" --frozen jrp "$@"
fi

NOTES="daily-research"
TIMEOUT="${JRP_RUN_TIMEOUT_S:-3600}"
[[ "$TIMEOUT" =~ ^[1-9][0-9]*$ ]] || die "JRP_RUN_TIMEOUT_S is not a number of seconds: ${TIMEOUT}"
VAULT="${JRP_VAULT_DIR:-}"
[[ -n "$VAULT" ]] || die "JRP_VAULT_DIR is not set"
[[ -n "${JRP_VAULT_STAGE:-}${JRP_STORE_DIR:-}" ]] || die "JRP_STORE_DIR is not set"
STAGE="${JRP_VAULT_STAGE:-${JRP_STORE_DIR}/vault-stage}"
mkdir -p "$STAGE/$NOTES" "$VAULT/$NOTES" || die "cannot create ${STAGE}/${NOTES} or ${VAULT}/${NOTES}"

# vault -> stage: every jrp note, so the harvest sees the author's ticks
rsync -a --include='*_jrp_*.md' --exclude='*' "$VAULT/$NOTES/" "$STAGE/$NOTES/" ||
  die "cannot stage the vault's notes (rsync)"

# doctor: logged always, notified when it fails, never a reason to skip the run. It sees
# the stage as its vault, like the run: python never touches the iCloud path.
DOCTOR_OUT="$(mktemp "${TMPDIR:-/tmp}/jrp-doctor.XXXXXX")" || die "cannot create a temp file (mktemp)"
set +e
limited "$DOCTOR_TIMEOUT_S" env JRP_VAULT_DIR="$STAGE" "$UV" run --project "$REPO" --frozen jrp doctor >"$DOCTOR_OUT"
doctor_status=$?
set -e
cat "$DOCTOR_OUT"
if ((TIMED_OUT)); then
  notify "jrp doctor FAILED" "no answer in ${DOCTOR_TIMEOUT_S} s and killed; the run goes ahead"
elif ((doctor_status != 0)); then
  failed_checks="$(grep '^FAIL' "$DOCTOR_OUT" | tr '\n' ';' || true)"
  notify "jrp doctor FAILED" "${failed_checks:-exit ${doctor_status}, see the log} the run goes ahead"
fi

MARK="$(mktemp "${TMPDIR:-/tmp}/jrp-run-mark.XXXXXX")" || die "cannot create the run mark (mktemp)"
STARTED=1
set +e
limited "$TIMEOUT" env JRP_VAULT_DIR="$STAGE" "$UV" run --project "$REPO" --frozen jrp "$@"
status=$?
timed_out=$TIMED_OUT
set -e

# stage -> vault: only the notes this run wrote (newer than the mark) — a killed run's too
# A copy that fails does not stop the others, and is said: python already reported the run
# as done, but the author reads the vault, not the stage.
copied=0
uncopied=""
while IFS= read -r -d '' note; do
  if cp -p "$note" "$VAULT/$NOTES/"; then
    echo "vault ← $(basename "$note")"
    copied=$((copied + 1))
  else
    uncopied="${uncopied} $(basename "$note")"
  fi
done < <(find "$STAGE/$NOTES" -name '*_jrp_*.md' -newer "$MARK" -print0)

if [[ -n "$uncopied" ]]; then
  notify "jrp run FAILED" "not copied to the vault (still in ${STAGE}/${NOTES}):${uncopied}"
fi
if ((timed_out)); then
  notify "jrp run TIMED OUT" "killed after ${TIMEOUT} s (JRP_RUN_TIMEOUT_S); ${copied} note(s) it wrote before the kill copied to the vault"
  exit 124
fi
if [[ -n "$uncopied" ]] && ((status == 0)); then
  exit 1
fi
exit "$status"
