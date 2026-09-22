# jev-research-pipeline

毎朝、研究ラインごとに 1 本のレポートを Obsidian の vault に書く pipeline。制御の流れは
コードが持ち、判断は TypeSafe Jev に狭い質問の束として投げ、文章が要る 2 箇所だけ Qwen が書く。
設計の正本は [docs/design/pipeline-design.md](docs/design/pipeline-design.md)。

```bash
uv run jrp run            # 記入を取り込み → 輪番で次の 3 ライン → note を書く
uv run jrp fit            # 閾値の再推定を提案ファイルに書く（自動適用はしない）
uv run jrp export-cases   # ⭕❌ の付いた claim を pydantic-evals の Case に出す
uv run jrp drift          # 録画した Jev 入力を live に投げ直して確率差を出す
```

## 環境変数

秘密は repo に置かず `~/.config/jrp/env` に書く（`scripts/launchd-jrp.sh` が読む）。

| 変数 | 要否 | 用途 |
|---|---|---|
| `JRP_VAULT_DIR` | 必須 | vault の root。未設定なら何も書かずに止まる |
| `JRP_STORE_DIR` | 推奨 | pipeline の store（既定は `./var/store`） |
| `TYPESAFE_API_KEY` | 必須 | Jev |
| `DASHSCOPE_API_KEY` | 必須 | Qwen（DashScope の intl endpoint） |
| `JRP_COST_CAP_USD` | 推奨 | 1 ライン分の費用上限。超えたら以降を省いて partial report |
| `JRP_JEV_USD_PER_QUESTION` | 推奨 | Jev の単価。未設定だと費用計算に Jev が乗らない |
| `TAVILY_API_KEY` | 任意 | web 検索。未設定ならその adapter は skip（運用節に記録） |
| `GITHUB_TOKEN` | 任意 | GitHub 検索の上限を 10/分 → 30/分 に上げる |
| `JRP_PROSE_TIMEOUT_S` | 任意 | 本文生成の timeout（既定 300 秒） |
| `JRP_SLACK_NOTIFY` | 任意 | `1` で実行結果を Slack に 1 行通知 |
| `JRP_DRIFT_LIVE` | 任意 | `1` で `jrp drift` が live に投げる |
| `JRP_DAILY_RESEARCH_CONFIG` | 任意 | ライン一覧の config.toml の path |

### GITHUB_TOKEN の入れ方

未認証だと GitHub の検索は 10 回/分で、超えると 403 が返る（初回 live run で発生）。token を
入れると 30 回/分になる。

```bash
gh auth token   # gh CLI の token をそのまま使う（repo 等の広い scope が付く）
```

公開 repo の検索だけなら、権限を 1 つも付けない fine-grained PAT で足りる（fine-grained token は
公開 repo への read を常に持つ）。常用にはこちらを薦める。どちらも
`GITHUB_TOKEN=...` として `~/.config/jrp/env` に書く。

## Observability

トレースは OpenTelemetry。`OTEL_EXPORTER_OTLP_ENDPOINT` が未設定なら SDK を初期化せず、
span は no-op になる。ローカルで見るには Docker 不要の viewer を入れる:

```bash
brew tap ctrlspice/otel-desktop-viewer
brew trust ctrlspice/otel-desktop-viewer      # untrusted tap なのでこれが先に要る（2026-09-23 実測）
brew install --cask otel-desktop-viewer
```

`~/.config/jrp/env` に 3 行:

```bash
export OTEL_SERVICE_NAME="jev-research-pipeline"
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"   # path は SDK が足す
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
```

UI は `http://localhost:8000`。出る span は `jrp.line` / `jrp.stage.*`（stage ごとの所要時間）、
`jev.<関数名>`（質問数・subject 数・model・結果）、Qwen 2 箇所（pydantic-ai 内蔵の計装。
prompt 本文は送らない）、HTTP（httpx2 の計装）。研究の数値は store と運用節が正本で、
OTel は実行中の観察用。

## 定期実行

[launchd/README.md](launchd/README.md) を見る（plist を 2 つ置いて `launchctl load`）。

## 開発

```bash
.claude/verify.sh          # format / lint / 型 / bandit / deptry / test（offline、key 不要）
uv run pytest -q
```

テストは外部 API を呼ばず、`tests/cassettes/` の記録を再生する。記録を作り直すときは
`JRP_CASSETTE_SYNTHETIC=1`（tests/fakes.py の偽 upstream から合成）、live 記録は
`JRP_CASSETTE_RECORD=1`（key が要る。書き先は gitignore された `tests/cassettes/live/`）。
