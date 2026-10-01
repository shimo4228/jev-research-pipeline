# 英語圏・中国語圏の人が使える道具へ（2026-10-01）

著者との合意（2026-10-01）: 想定する最初の利用者は英語圏と中国語圏（著者の GitHub フォロワーの大半）。
ノートの言語は ja / en / zh を選べるようにする。README は英語と日本語のまま、中国語版は作らない。
前の goal（docs/plans/daily-tool-hardening.md、自分が毎日頼れる道具）の上に積む。

## 出発点（2026-10-01）

- 日本語に固定: 本文プロンプト v15 + check9（`generation/prose.py`）、ノートの見出しと運用欄
  （`report/`、`pipeline/run.py`）、bench の判定役・読み手シミュレーションの指示文。
  tick の読み戻しは HTML コメントの id なので言語に依存しない
- 導入の障壁: 設定が別 repo（`~/MyAI_Lab/daily-research/config.toml`）と repo 内 `questions/` に
  散らばる / graph.jsonld を持つ repo を指さないラインはローテーションに入らない / 定期実行は
  launchd の plist を手で書き換える / 通知が著者の harness（`~/.claude/scripts/notify-slack.sh`）頼み /
  配布は git clone + `uv sync`
- 問いの書き方（brief / method / evidence / not / canary / クエリ行）が探索の天井を決めるが、
  手順は AGENTS.md「問いとクエリを書く」にしか無い
- 減らせない前提: TypeSafe の有料 key（Jev がこの設計の中心）と、書き手 1 つ
  （Claude Code / ChatGPT の Codex / DashScope）

## Goal（全部満たしたら完了）

**P0 前の goal の残り: Opus の本文を本番の点検に通す**（P1 より先）
- 著者は本番の書き手を Claude Opus 5.5 にすると決めた（2026-10-01、blind 読み 5/5）。だが scratch の
  本番 run（jev ライン、v15 + check9、`claude-code:claude-opus-5-5`）で、3 問中 2 問が 2 稿とも
  `rubric_report@fidelity_v1`（段落ごとの `exceeds_claims ≥ 0.6`）に落ちてテンプレートになった。
  bench の判定役は材料全体を見るが、本番の点検は段落が引用した claim と抜粋だけを見る
  （`quality.py` の `cited_claims` / `cited_excerpts`）。前提の説明・言い換え・2 段落構成がずれの候補
- 原因を Decision / Judgment から段落単位で特定し、本番の点検か本文の書き方のどちらを直すかを決める
  （点検を緩めるなら、bench の足切りで忠実さが落ちないことを同時に示す）。scratch の本番 run で、
  Opus の節がテンプレートに落ちないことを確かめてから、env を `claude-code:claude-opus-5-5` にする
- それまで本番は `openai-codex:gpt-6-luna` + v15（env はそう戻してある）。GPT × v15 が本番の点検を
  通るかは未実測なので、翌朝のノートの運用欄で「本文生成なし (template)」の数を確かめる
- scratch の材料: `<scratchpad>/opus-smoke/`（前のセッションのもの。無ければ作り直す: 実 store を
  scratch に rsync、config は jev + desire だけ）


**P1 言語**（最優先）
- `JRP_NOTE_LANG=ja|en|zh`（既定 ja）。見出し・運用欄・空の日の文面は言語ごとの表から引く。
  既存の日本語ノートの tick 読み戻しは変わらない（テストで固定）
- 本文プロンプトを言語ごとに持つ（en / zh は v15 の設計を各言語の書き方で書き起こす。訳すだけにしない）。
  bench の判定役・読み手シミュレーションの指示文も各言語に。ケース（材料）は共通
- 受け入れ: en / zh それぞれ Opus で 32 件、忠実さの足切りが ja-v15 と同水準、読み手の指標が
  ノイズの範囲で ja-v15 と並ぶ。en は著者の blind 読みで受け入れる。zh は著者が読めないので
  代理指標だけで受け入れ、その旨を README に書く（読み手を募る導線は P4）
- Jev への状態（問いの文面など）が en / zh でも判定が崩れないことを scratch run で確かめる

**P2 最初の 1 時間**
- `jrp init`: `~/.config/jrp/` に env の雛形・`config.toml`・`questions/` を作る。repo を fork せずに使える
  （`JRP_QUESTIONS_DIR` の既定を repo の外へ。既存の著者環境は env で今の場所を指したまま動く）
- repo を指さないラインもローテーションに入る（graph.jsonld は任意の語彙源）
- 問いを立てる skill を repo に同梱（`.claude/skills/`。書く前に skill: `skill-creator` を通す）:
  テーマを聞く → 答えの出ていない問いを 2〜4 本 → `not:` → 今週の語彙を検索してクエリ → `jrp queries check`
  で試し打ち → canary 候補。`jrp questions new` は同じ手順を `claude -p` で回す薄い入口
- `jrp try --line <slug>`: scratch の store / vault に 1 回だけ回し、ノートのパスを出す（翌朝を待たない）

**P3 運用の汎用化**
- 通知: `JRP_SLACK_WEBHOOK_URL` を直接叩く、または macOS の通知センター。著者の harness script は
  任意の上書きとして残す
- `jrp schedule install`: launchd の plist をこの環境のパスで生成して表示する（読み込みは利用者が行う）。
  Linux 向けに cron / systemd の例を docs に置く
- Obsidian 以外の Markdown ビューアで崩れない書式か確認（`[-]` の印、`> [!note]-` の折りたたみ）

**P4 配布と入口**
- PyPI 用のパッケージ設定と `uvx jrp init` で始まる Quick start（公開そのものは著者が行う）
- README（英語・日本語）を作り直す（skill: `readme-writer`）
- **レポートの見本**（著者 2026-10-01）: en / zh / ja のノートの実例を repo に置き、README から直接開ける
  ようにする。第三者の原文（claim の引用）を含むので、公開してよい形（引用の量・リンクのみ）を決めてから
- **費用の概算**（著者 2026-10-01）: 1 朝あたりの Jev 費用（運用欄の実測。4 ラインで $0.02〜0.3 程度）と、
  書き手ごとの消費（サブスクの使用量の目安、DashScope なら従量の金額）を、ライン数・問い数から見積もる
  表を README に置く。数値は実測から作り、測った日付を付ける

## 境界

- PyPI への公開・GitHub の release・README を含む公開物の push は著者に渡す
- 著者の本番（`~/.config/jrp/env`、launchd、実 vault / 実 store）の既定挙動は変えない。新しい既定は
  著者の env で今の値に固定してから入れる
- tick の used rate（遅れて付く暗黙のラベル）は製品の本命候補だが、設計判断なので提案まで

## 停止条件

- 同じ方針で 2 回失敗したらその phase を止め、他を続ける
- Claude の usage / rate limit に当たったら止めて報告する。GPT / DashScope は使わない
- 上限: scratch の live run 10 回 / Jev $3 / 言語ごとのプロンプト候補 6 版

## 順序

P0 → P1（見出しの表 → en プロンプト → zh プロンプト → scratch run）→ P2 → P3 → P4。
P1 の en を著者が読む時点で一度止めて報告する。
