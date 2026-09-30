# 毎日頼れる道具へ — 自律実行の goal（2026-10-01）

著者との合意（2026-10-01）: 対象は著者 1 人が毎朝信頼して読める道具（OSS 化はしない）。
範囲は本文の質 / 発見の穴 / tick ループ / 運用の堅牢性の 4 本。開発中の評価用の本文生成は
Claude（`claude -p`、サブスク枠）で行う — GPT / Qwen は枠が小さく評価の反復で尽きるため。
本番の書き手は当面 GPT-6 Luna のまま、ただし本番からも Claude を呼べる backend を用意する。
著者は途中で読まず、最後にまとめて読む。

## 出発点（2026-10-01 の実測）

- 本番は 9/24 から毎日完走（`~/Library/Logs/jrp-run.log`）。v10 + check6 は gpt-6-luna の
  難所 3 件でしか検証しておらず、holdout 未実施。固定ケースは pilot 期の 19 件のみ
- `ans` は直近 4 回すべて 0 claims（9/30: 取得 411 → 問いの対 5 → Keep 0）、`desire` は
  直近 4 回中 2 回 0。firehose は arXiv CS カテゴリ
- 記入率 0.00。10/1 desire の harvest が `label 9 / 取り消し 26`（上書き疑い、未確認）。
  10/1 akc の `## 未判定` に問いの見出しと claim 文が混入（表示バグ疑い、未確認）
- 失敗通知なし。コード既定 `gpt-5.6-sol` と env の `gpt-6-luna` がずれている。README Status は 9/25 時点

## Goal（全部満たしたら完了、著者の最終読みで受け入れ）

**G1 本文**
- 固定ケースを 9/24 以降の本番ノートから拡充して ≥40 件（dev / holdout は id で決まる既存規則）
- 候補プロンプトが、dev 全件と holdout ≥10 件で:
  - 忠実さの足切り（prose-judge）pass 率 ≥90%、かつ同じケースで v10 以上
  - 読み手シミュレーション（下記）の要点回収率 ≥0.8、かつ v10 以上
  - 字数は評価の基準にしない（比較表に参考表示のみ。著者判断 2026-10-01。問い 1 つの本文が 2,000〜3,000 字でも、ノートに本文が複数あってそれ以上になっても構わない）
  - 形式のコード検査 全 pass
- 転移確認: 最終候補を本番モデル gpt-6-luna で holdout 5 件書き、上の足切りと回収率が
  Claude 草稿から大きく落ちない（落ちたらモデル差として報告し、本番切替は保留）
- 著者向け blind 読み比べ `read.md`（v10 vs 候補、いずれも gpt-6-luna 草稿）を用意する

**G2 発見**
- `ans` / `desire` の 0 claims の原因を段ごとの数字で特定し、scratch store での live run で
  両ラインとも ≥1 問いに Keep が付く（付かない原因が「世界に新しい文献が無い」なら、その証拠を示す）

**G3 tick ループ**
- 取り消し 26 件と未判定への混入を、実ノートの形を使った再現テストで確かめ、バグなら直す
- 実 vault のノート形式（iCloud stage 経由を含む）で tick → harvest → store の往復がテストで通る
- `jrp fit` が既存ラベルで最後まで走る（提案ファイルを書くだけ。適用はしない）

**G4 運用**
- run の失敗（非ゼロ終了・stage timeout・Codex / Claude の認証失敗）が当日中に著者に届く
- `jrp doctor`（仮）: 書き手の認証・各 API の到達性を 1 コマンドで確認
- コード既定モデルを本番と揃える（cassette 再録）。README / README.ja の Status を同期（skill: readme-writer）

## 実装の骨子

**`claude-code` backend**（`generation/client.py` に 1 分岐、`JRP_PROSE_MODEL=claude-code:<model>`）
- `claude -p` を subprocess で呼ぶ。`--bare` は OAuth を読まない（2.1.285 の help で確認）ので使わず、
  `--setting-sources` / `--strict-mcp-config` / `--tools ""` / `--system-prompt` / `--no-session-persistence`
  / `--output-format json` で文脈と tool を絞る。harness の CLAUDE.md・hook が入らないことを Phase 0 で実測
- launchd 下で keychain の OAuth が読めるかを Phase 0 で実測（iCloud と同種の罠がありうる）
- 本番の cost 行は subscription と同じ扱い（token は数える、0 計上）

**評価の役割分担**（開発時のみ。本番の run は評価しない）
| 役割 | 担当 |
|---|---|
| 候補草稿 | Claude Sonnet（反復量のため。Phase 0 で Opus と 3 件比べて決める） |
| 忠実さの足切り | 既存 `prose-judge`（Opus）を `claude -p --agent` で草稿 1 本ずつ |
| 読み手シミュレーション | 素材を渡さず草稿だけを読ませ、固定の問い（どの研究か / 何の問題か / 何をしたか / 何が分かったか / 数字と比較対象）に答えさせ、素材と照合して回収率を出す。書き手と別モデル |
| 上限の参照 | Opus の参照草稿（原因がモデルか指示かの切り分け） |
| 受け入れ | 著者の最終 blind 読み。その判定を記録し、将来の判定役の較正データにする |

**本番への反映の境界**
- G2 / G3 / G4 のバグ修正・機能は verify と review を通して main に ff-only で入れてよい（翌 05:00 から効く）
- 本番の本文プロンプト（`generation/prose.py` の `INSTRUCTIONS`）の差し替えは著者の最終読みの後
- `~/.config/jrp/env`・launchd plist・`~/MyAI_Lab/daily-research/config.toml` は変えない。
  変更が要るなら差分を最終報告に載せて著者に渡す（config.toml は git 管理外）
- 問いのクエリ行の追加・書き換えはしてよい（AGENTS.md の手順）。見出し・brief の変更は提案まで
- used rate（design「Evaluation and self-improvement」の延期候補）は、記入率 0 を受けて
  設計提案までにとどめる（実装しない）

## 停止条件

- 同じ方針で 2 回失敗したら、その workstream を止め、他は続ける
- Claude の usage limit / rate limit に当たったら burst を止めて報告（`debugging.md`）
- 上限: gpt-6-luna 20 リクエスト / Jev（scratch の live run）$3 / scratch live run 10 回 /
  プロンプト候補 10 版
- 実 vault・実 store に書く run はしない（`JRP_VAULT_DIR` / `JRP_STORE_DIR` は scratch）

## 順序

0. `claude-code` backend、`claude -p` の文脈隔離と launchd 下の認証を実測。ケース拡充（export）
1. 並行: G4 と G3 の調査・修正（本番を守る側なので先に入れる）/ G2 の段別診断
2. G1 の反復（難所セット → dev 全件 → holdout）
3. gpt-6-luna への転移確認、`read.md`、README 同期、最終報告（未達の goal と理由、著者に渡す差分）
