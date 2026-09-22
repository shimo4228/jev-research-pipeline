#!/usr/bin/env bash
# .claude/verify.sh — この repo の機械ゲート、唯一の入口。
#
# 契約 (~/.claude の verify-bootstrap skill が定める。ハーネス側の hook はこれだけを知る):
#   引数     --staged = commit 境界の高速検査 (staged ファイルのみ、数秒)
#            引数なし  = repo 全体の完全検査 (type / test / 依存監査を含む)
#   exit     0 = PASS / 1 = FAIL (commit を止める) / 2 = 検査不能 (fail-soft)
#   stdout   FAIL 時は人間と LLM が読んで直せる検出行。PASS 時は無出力
#
# --staged は index の内容を tmpdir に展開してから検査する (working tree ではない)。
# 部分 staged のファイルで未 staged の変更を巻き込まないため。
#
# offline 前提: API key もネットワークも要らない (外部 API の応答は cassette で再生する)。
# ツールの版は pyproject.toml の [dependency-groups] dev が正本 (uv run で解決)。
# 選定根拠・選定日・再調査トリガーは .claude/verify.md。

set -uo pipefail

# root の決め方 (契約): VERIFY_REPO_ROOT → 自分自身の位置。cwd 起点にすると hook 経由で
# 別 repo を検査して無言で PASS する fail-open になる
if [[ -n "${VERIFY_REPO_ROOT:-}" ]]; then
  ROOT="$VERIFY_REPO_ROOT"
else
  ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P) || exit 2
fi
git -C "$ROOT" rev-parse --show-toplevel >/dev/null 2>&1 || { echo "[verify] git repo ではない"; exit 2; }
MODE=full
[[ "${1:-}" == "--staged" ]] && MODE=staged

FAIL=0

# check <label> <cmd...> — 非ゼロ終了を FAIL として報告する
check() {
  local label=$1 out
  shift
  if out=$("$@" 2>&1); then
    return 0
  fi
  printf '[%s] %s\n' "$label" "$out"
  FAIL=1
}

if ! command -v uv >/dev/null 2>&1; then
  echo "[verify] uv が無いため Python ゲートを実行できません (brew install uv)"
  exit 2
fi
UV=(uv run --project "$ROOT" --frozen --quiet)   # --project は cwd を変えない
# bandit: -ll -ii = medium 以上の severity と confidence。出力は 1 検出 1 行
BANDIT=(bandit -q -r -ll -ii -f custom --msg-template '{relpath}:{line} [{test_id}] {msg}')

# ---------------------------------------------------------------- staged mode
if [[ "$MODE" == "staged" ]]; then
  staged=$(git -C "$ROOT" diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
  py=$(printf '%s\n' "$staged" | grep -E '\.py$')
  [[ -z "$py" ]] && exit 0

  TMP=$(mktemp -d) || exit 2
  trap 'rm -rf "$TMP"' EXIT

  while IFS= read -r f; do
    [[ -z "$f" || "$f" == *..* ]] && continue
    mkdir -p "$TMP/$(dirname "$f")"
    git -C "$ROOT" show ":$f" > "$TMP/$f" 2>/dev/null || true
  done <<< "$py"
  # ツール設定も index 側から。無いと既定値で判定して偽陽性になる
  git -C "$ROOT" show ":pyproject.toml" > "$TMP/pyproject.toml" 2>/dev/null || true

  cd "$TMP" || exit 2
  check format   "${UV[@]}" ruff format --check .
  check lint     "${UV[@]}" ruff check --no-cache .
  # tests/ は assert が本体なので bandit の対象外 (full モードと同じ範囲)
  if [[ -d src ]]; then
    check security "${UV[@]}" "${BANDIT[@]}" src
  fi
  exit $FAIL
fi

# ------------------------------------------------------------------ full mode
cd "$ROOT" || exit 2

check format   "${UV[@]}" ruff format --check src tests
check lint     "${UV[@]}" ruff check --no-cache src tests
check type     "${UV[@]}" pyright
check security "${UV[@]}" "${BANDIT[@]}" src
check deps     "${UV[@]}" deptry --no-ansi src
check test     "${UV[@]}" pytest -q

exit $FAIL
