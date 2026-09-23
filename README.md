# jev-research-pipeline

毎朝、研究ラインの **open な「問い」ごと**に、今日その答えが何に動いたかを Obsidian の vault に
書く pipeline。制御の流れはコードが持ち、判断は TypeSafe Jev に狭い質問として投げ、文章が要る
2 箇所だけ Qwen が書く。設計の正本は
[docs/design/pipeline-design.md](docs/design/pipeline-design.md)。

問いは著者が `questions/<スラッグ>.md` に手で書く。**問いが 1 つも open でないラインは走らない**
（「問い未設定」として報告されて次のラインに進む）。

```bash
uv run jrp run            # 記入を取り込み → 輪番で次の 3 ライン → note を書く
uv run jrp fit            # 閾値の再推定を提案ファイルに書く（自動適用はしない）
uv run jrp export-cases   # ⭕❌ の付いた claim を pydantic-evals の Case に出す
uv run jrp drift          # 録画した Jev 入力を live に投げ直して確率差を出す
uv run jrp migrate --dry-run   # store を現行 schema に上げる計画を表示（--dry-run なしで実行）
```

## 最初にやること: 問いを立てる

ライン 1 本につき 1 ファイル。`questions/akc.md` の例:

```markdown
<!-- jrp:questions:akc -->

## エージェントの記憶は何で決まるのか
- slug: agent-memory
- version: 1
- status: open
- opened: 2026-09-23
- retire: 三ヶ月 evidence が増えなければ閉じる
- brief: 記憶機構の違いが下流の精度をどれだけ動かすか。
- method: RAG
- method: 長文 context
- evidence: 測定されたもの。主張だけのものは採らない
- not: プロンプト技法一般
- canary: https://arxiv.org/abs/2609.01234
```

- `slug` と `version` が Question ノードの identity。**問いの文面を直したら version を上げる**
  （上げないと、前の文面で下された判定が新しい文面の判定として数えられる）
- `status` は `open` / `answered` / `dropped`。open だけが走る
- `not:` は「隣接していて毎回ひっかかるが、この問いではないもの」。screening の hard gate が使う
- `canary:` は「この問いなら絶対に拾ってほしい論文」。screening がそれを落とした日は運用節に
  「canary 落下」が出る = screening がずれた合図
- 毎日の note の「## 問いの候補」に pipeline からの提案が並ぶ。**チェックを付けた候補だけ**が
  次回の harvest でこのファイルに追記される（pipeline がこのファイルに書くのはこの 1 経路だけ）

## 読み方 (note の構成)

```
### <問い>          ← 今日動いた問いだけ節になる
今日の変化           ← 本文。[n] は証拠 claim の番号。【推論】で始まる段落だけが推論
証拠                ← その日の source
- [ ] 読む価値があった   ← 記入率の単位。⭕ は引用された claim と source にも伝播する
## Review           ← 判定保留 (境界 / 確信度 0.9 未満)。⭕❌ が次の閾値再推定に効く
## 問いの候補         ← チェック = 採用
## 橋渡し            ← 語彙の外から繋がったもの (exploration net)
> [!note]- Claims   ← 畳まれた claim 一覧。claim 単位の記入もできる
```

## 探索 (net)

keyword 検索だけでは収束する（実測: 30 日で単一テーマ 37%）。コードが順序を固定した 5 本の net を
持ち、モデルは「どこを探すか」を決めない。

| net | 何を引くか | 既定の予算/run |
|---|---|---|
| firehose | arXiv 新着 RSS（カテゴリ固定）+ HF daily papers。query なし | 2 |
| recommendation | Semantic Scholar 推薦（⭕ と採用 claim の論文が positive、❌ と乱択が negative） | 1 |
| citation | OpenAlex の前向き引用（採用済み論文を引いた論文） | 3 |
| keyword | 問いごとに Qwen が書き Jev が選ぶ検索語（従来の net） | 12 |
| exploration | 隣の OpenAlex topic。keyword 予算の一部を回す | 1 |

`config.toml` に `[nets]` を書くと変えられる:

```toml
[nets]
firehose = 2
recommendation = 1
citation = 3
keyword = 12
exploration = 1
exploration_share = 0.2          # keyword 予算のうち探索に回す割合
arxiv_categories = ["cs.AI", "cs.CL", "cs.LG", "cs.HC"]
openalex_daily_credits = 400     # keyless は 1 日 1,000 credit ($0.10)
firehose_max = 300               # 1 ライン 1 回の firehose 取り込み上限
arxiv_keyword_max = 1            # 1 ラインあたりの arXiv API 検索数 (429 を避ける)
```

運用節には net ごとの取得数・採用率、OpenAlex の topic クラスタ数（**減ったら収束の警報**）、
収束推定 f = 1 - exp(-n/tau) が出る。「n 件連続で無関係だった」は収束の証拠として扱わない。

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
| `JRP_PROSE_TIMEOUT_S` | 任意 | 本文生成の timeout（既定 900 秒。本文は thinking ありで書くため長い） |
| `JRP_PROSE_THINKING` | 任意 | 本文の thinking: `always`（既定）/ `rewrite`（書き直し稿だけ）/ `off` |
| `JRP_JEV_CONCURRENCY` | 任意 | 同時に投げる Jev request の数（既定 12）。rate は別に 1,200 回/分で抑える |
| `JRP_PROSE_CONCURRENCY` | 任意 | 同時に走らせる Qwen 呼び出しの数（既定 3。検索語の生成と問いごとの本文） |
| `JRP_SLACK_NOTIFY` | 任意 | `1` で実行結果を Slack に 1 行通知 |
| `JRP_DRIFT_LIVE` | 任意 | `1` で `jrp drift` が live に投げる |
| `JRP_DAILY_RESEARCH_CONFIG` | 任意 | ライン一覧と `[nets]` を書く config.toml の path |
| `JRP_QUESTIONS_DIR` | 任意 | 問いファイルの置き場（既定 `./questions`） |
| `SEMANTIC_SCHOLAR_API_KEY` | 任意 | 推薦 net。未設定だと共有枠で 429 になりやすく、その日は黙る |
| `OPENALEX_API_KEY` | 任意 | 引用 net の 1 日上限を $0.10 → $1 に上げる |
| `HF_TOKEN` | 任意 | HF daily papers の rate limit を上げる |

### GITHUB_TOKEN の入れ方

未認証だと GitHub の検索は 10 回/分で、超えると 403 が返る（初回 live run で発生）。token を
入れると 30 回/分になる。

```bash
gh auth token   # gh CLI の token をそのまま使う（repo 等の広い scope が付く）
```

公開 repo の検索だけなら、権限を 1 つも付けない fine-grained PAT で足りる（fine-grained token は
公開 repo への read を常に持つ）。常用にはこちらを薦める。どちらも
`GITHUB_TOKEN=...` として `~/.config/jrp/env` に書く。

## 速さ

1 回の実行では輪番の 3 ラインと daily のライン（jev）を並べて走らせ、各ラインの中でも同じ段の判定を
並列に投げる（`JRP_JEV_CONCURRENCY`）。screening は安い prefilter（問いごとの on_topic 1 問）を先に
全 source に聞き、通った対だけに full bundle を聞く。問いごとの本文生成も並列（`JRP_PROSE_CONCURRENCY`）。
取得は ToU の間隔を守ったまま（arXiv 3 秒、GitHub / HF 6 秒）、届いた net の分から判定を始める。
並列度を変えても、note と store に書かれる中身は変わらない（並列度 1 と同じ bytes になることを
テストで固定している）。

## store の schema が変わったとき

古い build が書いた store は、どのコマンドも最初に検査する。

- **追加だけの変更**（新しい項目が増えただけ）: その場で現行 schema に書き直し、運用節に 1 行残す
- **非互換**（項目の削除・意味の変更、今の model で読めないノード）: 何も読み書きせずに 1 行で止まる。
  `store/lines/<ライン>.jsonld は旧 schema (…)。` の形

止まったら `jrp migrate --dry-run` で計画を見て、`jrp migrate` で実行する。非互換のファイルは
消さずに `<store>/retired/<日付>/` へ移すので、そのラインは空の store からやり直しになる。

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
