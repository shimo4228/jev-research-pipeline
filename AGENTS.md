# jev-research-pipeline — agent 向け作業手順

入口は [README.md](README.md)、設計の正本は [docs/design/pipeline-design.md](docs/design/pipeline-design.md)。
機械ゲートは `.claude/verify.sh`（offline、PASS 時は無出力）。ここには repo 固有の作業手順だけを置く。

## 問いとクエリを書く

問い（`questions/<slug>.md`）は著者が持つ。著者が気づいたときに更新する — pipeline が自動で
新設・退役することはない（design「Authored queries」節）。agent がやるのは、著者の指示で
問いを書き換えることと、その問いの検索クエリを書くこと。手順の正本は repo の skill
`jrp-question`（[.claude/skills/jrp-question/SKILL.md](.claude/skills/jrp-question/SKILL.md)）—
テーマを聞く → 問い 2〜4 本と `not:` → 今週の語彙を検索 → アダプタごとのクエリ → `jrp queries check`
で試し打ち → canary → `jrp try`。この repo では skill の `jrp …` を `uv run jrp …` で呼ぶ。

**いつ**: 問いを足した・書き換えたとき / あるラインの note に 2 週間続けて動いた問いが無いとき /
著者に頼まれたとき。

この repo の著者環境では、`JRP_QUESTIONS_DIR` が main の checkout の `questions/` を指す
（`~/.config/jrp/env`）。書き換えたら **commit して main に入れる** — launchd の 05:00 の run は
main の checkout を読むので、次の tick から効く。

## 本文を磨く（prose bench）

本文の改善は開発時のループで行う。下書き・判定・読み手シミュレーションは Claude のサブスクリプション
（`claude -p`）で回し、GPT / Qwen の枠は本番モデルへの転移確認にだけ使う。ループの組み方の正本は
skill: `author-calibrated-eval`、この repo での経緯と決定は design「Prose bench」。材料は非公開の
`<JRP_STORE_DIR>/prose_bench/` にだけ置く（第三者の原文を含むため）。

役割: 読みやすさの正解は**著者の blind 読み**。判定役（Opus）は**忠実さの足切りだけ**を草稿 1 本ずつ
判定する（`docs/prose-rubric.md`）。読み手シミュレーション（草稿だけを読む Haiku が持ち帰った中身を、
材料だけを見る Sonnet が採点）は読みやすさの代理指標で、受け入れは著者が決める。形式はコードが見る。

1. `uv run jrp prose export` — 本文のある question-day を固定する（dev / holdout は id で決まる）
2. `uv run jrp prose bench --variant <name> --prompt bench/prose/prompts/<file> --check bench/prose/prompts/<check> --sources --model claude-code:opus --cases <ids>`
   — 候補の草稿を作る。`--model` は `JRP_PROSE_MODEL` と同じ形（`claude-code:` / `openai-codex:` / `dashscope:`）
3. `uv run jrp prose gate --variant <name> --cases <ids>` → `uv run jrp prose judge --variant <name>`
   — 草稿 1 本ごとの gate ファイルを作り、`claude -p` の判定役が verdict を書く（入力が変わった判定は
   自動でやり直す）
4. `uv run jrp prose comprehend --variant <name> --cases <ids>` — 読み手シミュレーション
5. `uv run jrp prose scores --variants <a>,<b>,... --cases <ids>` — 共通のケースで並べる
6. `uv run jrp prose read --variants <a>,<b>,... --cases <ids> --out <scratchpad>/read.md`
   — 著者向けの blind 読み比べ。聞くのは「一番良いのはどれか・なぜか」だけ。対応表は `read.key.json`

ぶれ（2026-10-01 実測、18 件）: 同じ草稿の判定し直しで facts ±0.01・誤解 ±2・止まった箇所 ±0.5、
**同じプロンプトでの書き直し**で facts ±0.07・誤解 ±7・足切り ±1。18 件の差は足切り以外ほぼ判別できない。
dev と holdout を合わせた 32 件で比べ、改善は holdout で崩れないことを確かめる。usage limit に当たると
コマンドは止まる（再試行しない）。

本番の本文プロンプトは `bench/prose/prompts/v10.md` + `check6.md`（`generation/prose.py` の
`INSTRUCTIONS` と同文）。本番のモデルは `openai-codex:gpt-6-luna`。候補は v14 + check8 で、Opus では
足切り 31/32 だが GPT-6 Luna には転移しなかった（design「Prose bench on claude -p」）。

## trace を見る（OTel）

本番（launchd）の run は trace を送らない。`~/.config/jrp/env` の `OTEL_EXPORTER_OTLP_ENDPOINT`
はコメントアウトしてあり、endpoint が無ければ SDK は初期化されない（`telemetry.py`）。
endpoint を env に戻さない — 05:00 に受け側が起動していないと、送信失敗の retry と Traceback が
`~/Library/Logs/jrp-run.log` を埋め、run も延びる（2026-09-25 に実際に起きた）。

trace を見たいときは、デバッグする run にだけ endpoint を足す。受け側はローカルの
`otel-desktop-viewer`（入れ方は `telemetry.py` の docstring）を先に起動しておく:

```bash
set -a; source ~/.config/jrp/env; set +a
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uv run jrp run ...
```

実 vault / 実 store に書く run になる場合は下の「触ってはいけないもの」に従う。

## 触ってはいけないもの

- `~/MyAI_Lab/daily-research/config.toml` は旧 pipeline と共有で gitignore（git で戻せない）。
  トラックを外すときは外したブロックを退避してから
- 実 vault / 実 store への書き込みを伴う `jrp run` は著者の指示があるときだけ。試験は
  `JRP_VAULT_DIR` / `JRP_STORE_DIR` を scratch に向けて回す（docs/pilot-log.md の運用）
