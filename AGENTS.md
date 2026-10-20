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

## 入口を比べる（intake eval）

クエリの集合・net の on/off・firehose の上限と並べ方・本文の床を変える前に、候補の設定と現行の設定を
同じ凍結した取得の上で比べる。設計の正本は design「Intake eval」。

- 役割の違い: `jrp queries check` は書いたクエリを 1 回ずつ送り、ヒット数と上位の題を見る（的外れで
  ないかを書いた直後に確かめる。保存も判定もしない）。`jrp eval intake` は候補と現行の差を見る
  （問いに合う新規の論文の数 N_ot の差・区間・雑音の床・費用。判定役は本番の prefilter）
- 候補は TOML 1 本。書かない鍵は本番のまま:
  ```toml
  name = "firehose-backlog-7"
  body_floor = 150            # 要旨の床（文字）。省略 = 本番の 200
  [firehose]
  max = 300                   # 1 line-run の上限。省略 = config.toml の [nets] firehose_max
  backlog_days = 7            # 一覧が枠を余らせた日に、過去 7 日の未判定の溢れを BM25 順で足す
  [nets]
  recommendation = false      # false の net は送らない
  [queries.aap]
  drop = ["hf: agents violating their own rules"]   # questions/aap.md の行をそのまま
  add = ["github: agent approval workflow"]
  ```
- 回し方: `uv run jrp eval intake --candidate <toml> [--line <slug>]... [--days 14] [--freeze]`。
  `--freeze` は今日の firehose と両方の設定の keyword クエリを 1 回ずつ取得して凍結する（同じ日の 2 回目は
  何も送らない。rate limit が出た取得元は以降のラインでも送らず、2 つの取得元で出たら止まって exit 2。OpenAlex は
  config の credit 上限まで）。書くのは
  `<JRP_STORE_DIR>/evals/intake/`（`JRP_EVAL_DIR` で移せる）だけで、store の partition は読むだけ。試すときは
  `JRP_EVAL_DIR` を scratch に向ける
- 費用: 保存済みの判定が無い source だけを Jev に聞く。送る前に高めに見積もり、`--max-usd`（既定 $0.50）を
  超えるなら何も送らず exit 2。`TYPESAFE_API_KEY` が無ければ聞かず、N_ot は下限として出る。Jev が 429 を 3 回返したら聞くのを止めて exit 2。雑音の床は
  bench に jitter の行が無いとき最初に測る（`--jitter 40` = 40 source を聞き直す）
- 読み方: 判定の行が「差あり」になるのは、日ごとの差の t 区間が 0 を含まず、符号反転の p < 0.05 で、
  差が雑音の床の外のときだけ。「差のうち境界の論文」が多い差は、判定役の境目に乗った差として割り引く。
  self-check が外れた日は、再生が本番の仕組みを写せていない日として名指される
- クエリの差し替えを本番に入れるかは著者が決める。agent は結果（差・区間・費用、枯渇したクエリ）を渡す。
  入れると決まったら skill `jrp-question` の手順で questions/*.md を直す

## 本文を磨く（prose bench）

本文の改善は開発時のループで行う。下書き・判定・読み手シミュレーションは Claude のサブスクリプション
（`claude -p`）で回す。本番（`anthropic:`）への転移確認は数件だけ `--model anthropic:claude-opus-5-5` で
草稿を作って行う（1 件約 $0.2、API クレジットから引かれる）。ループの組み方の正本は
skill: `author-calibrated-eval`、この repo での経緯と決定は design「Prose bench」。材料は非公開の
`<JRP_STORE_DIR>/prose_bench/` にだけ置く（第三者の原文を含むため）。

役割: 読みやすさの正解は**著者の blind 読み**。判定役（Opus）は**忠実さの足切りだけ**を草稿 1 本ずつ
判定する（`docs/prose-rubric.md`）。読み手シミュレーション（草稿だけを読む Haiku が持ち帰った中身を、
材料だけを見る Sonnet が採点）は読みやすさの代理指標で、受け入れは著者が決める。形式はコードが見る。

1. `uv run jrp prose export` — 本文のある question-day を固定する（dev / holdout は id で決まる）
2. `uv run jrp prose bench --variant <name> --prompt bench/prose/prompts/<file> --check bench/prose/prompts/<check> --sources --model claude-code:opus --cases <ids>`
   — 候補の草稿を作る。`--model` は `JRP_PROSE_MODEL` と同じ形（`claude-code:` / `anthropic:` / `openai-codex:` /
   `dashscope:`）。省略すると本番の書き手（`anthropic:`、API クレジットで課金）になる
3. `uv run jrp prose gate --variant <name> --cases <ids>` → `uv run jrp prose judge --variant <name>`
   — 草稿 1 本ごとの gate ファイルを作り、`claude -p` の判定役が verdict を書く（入力が変わった判定は
   自動でやり直す）
4. `uv run jrp prose comprehend --variant <name> --cases <ids>` — 読み手シミュレーション
5. `uv run jrp prose scores --variants <a>,<b>,... --cases <ids>` — 共通のケースで並べる
6. `uv run jrp prose read --variants <a>,<b>,... --cases <ids> --out <scratchpad>/read.md`
   — 著者向けの blind 読み比べ。聞くのは「一番良いのはどれか・なぜか」だけ。対応表は `read.key.json`

ぶれ（2026-10-01 実測、18 件）: 同じ草稿の判定し直しで facts ±0.01・誤解 ±2・止まった箇所 ±0.5、
**同じプロンプトでの書き直し**で facts ±0.07・誤解 ±7・足切り ±1。18 件の差は足切り以外ほぼ判別できない。
dev と holdout を合わせた 32 件で比べ、改善は holdout で崩れないことを確かめる。書き手の上限（Claude Code の
usage limit、API の 429・key の拒否・クレジット切れ）に当たるとコマンドは止まる（再試行しない）。

本番の本文プロンプトは言語ごとに `src/jev_research_pipeline/generation/prompts/` にあり、bench の
ファイルと同文であることをテストが固定している: ja = `v16.md` + `check10.md`（本番は 2026-10-20 の run から）、en = `en2.md` + `en-check1.md`、
zh = `zh1.md` + `zh-check1.md`。言語のベンチは `jrp prose bench --lang en|zh`（判定役の rubric と
読み手の指示文も言語に従う）。本番のモデルは `anthropic:claude-opus-5-5`（2026-10-21 の run から。同じ Opus 5.5 を
Claude API で、`claude -p` と同じ effort medium で呼ぶ。2026-10-03〜10-20 は `claude-code:claude-opus-5-5` で、
著者の blind 読み 5/5）。Jev の claim_fidelity は記録だけで足切りではない（design「Production check vs the prose bench」）。

## 選別と根拠化の候補を比べる（gate eval）

S（prefilter・triage・trust・screening）と X（claim_detection・novelty・掲載枠の並べ順）の変更は、
週報を待たずに固定データで基準（今の run）と比べる。正本は design「Gate eval: S and X on frozen data」、
調査は `docs/plans/research/2026-10-20-sx-eval-loop.md`。本番 store は読むだけにし、写しに向けて回す:

```bash
cp -cR "$JRP_STORE_DIR"/{lines,pipeline.jsonld} <scratch>/store/   # APFS の複製
JRP_STORE_DIR=<scratch>/store uv run jrp eval gate freeze            # 評価集合を凍結（--set で名前）
JRP_STORE_DIR=<scratch>/store uv run jrp eval gate --candidate bench/gate/candidates/<name>.toml
```

1. 候補は `bench/gate/candidates/*.toml` に 1 ファイル 1 変更で書く（閾値の名前・並べ順・screen の言い回し。
   形は `evals/gate_score.py` の docstring）。閾値と並べ順は保存済みの Judgment から再計算するので 0 円、
   言い回しの候補は標本の state に Jev を聞き直す（`--max-questions` で上限、既定 600 問）
2. 読む順は holdout の判定 → 変わる対・line-day → silver の行。比べるのは区間の重ならない差だけにする。
   holdout の label 付きで変わる項目が 85 未満のあいだは回帰 gate として読み、候補の間で選ぶのは著者
3. silver label: `uv run jrp eval gate label`（`ANTHROPIC_API_KEY`、週 `JRP_EVAL_WEEKLY_USD` 既定 $10。
   key が無ければ未測定のまま）。付いたら `jrp eval gate check --out <scratch>/check.md` で 30 件の blind
   確認ファイルを作って著者に渡し、`--read` で一致率を読む
4. 雑音の床: `uv run jrp eval gate jitter`（同じ state を Jev に聞き直す。既定 40 件・400 問）

候補を本番に入れるのは著者の判断。入れたら 1 週に 1 つにし、週報の分解で転移を確かめる。

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

## 週報を読む

本番では月曜の 05:00 の run の後に launchd の wrapper が `jrp wbr` を回し、朝のノートが vault に届いてから
週報のノートを届ける（失敗は `jrp wbr FAILED` / `jrp wbr TIMED OUT` の通知になり、job の exit は run のまま。
launchd/README.md）。`uv run jrp wbr --week <YYYY-Www> --out <scratchpad>` で、その週の週報を何度でも作り直せる。store の
partition は読むだけ。書くのはノート 1 本と `<JRP_STORE_DIR>/metrics/weekly.jsonl` への 1 行の追記。
`ANTHROPIC_API_KEY` が env にあると、監視 judge（`pipeline/monitor.py`）が Claude API を呼んで課金される。
上限は ISO 週ごとの `JRP_MONITOR_WEEKLY_USD`（既定 $5）で、呼び出しは送る前に自分の上限額を `metrics/judge.jsonl`
に予約し、終わったら実費の行で置き換える。打ち切られた呼び出しも、同時に走るもう 1 本の週報も、この予約の合計で
上限に収まる（隣の `judge.jsonl.lock` で順番に判定する）。試すときは `JRP_STORE_DIR` を store の写しに向け、
`env -u ANTHROPIC_API_KEY uv run jrp wbr …` で回す（1. の監視の行は「未測定 (key なし)」になる）。監視 judge の答えは
週報の表示にだけ使う。読む順は 2.（例外）→ 9.（計器）→ 1.（出力）→ 3.（分解）。比べるのは数値で出ている数だけにする。
ラインのセルは 0 より大きければ数で出て、registry が失敗か宣言済みの 0 と呼ぶ日を含む週は「19 ※」になり、表の
下の注記がその日と状態を名指す（「※ W40 jev: 2026-09-29 は未説明の 0」）。状態の語が出るのは、live とも暦どおりとも
呼ばれないラインの 0 だけ。全ラインの合計と分解・6.・7. の行は数値のまま、疑わしいラインを後ろに添える。その合計に
入るラインの分が 0 より大きいライン（セルなら数で出る）は「jev は一部の日が未説明の 0」、分が 0 のライン（セルなら
状態の語になる）は「ans は未説明の 0」と書き分ける。分解ではラインの分は、その行の因子に入る cohort のそのラインの分
（N_new・N_ot・O1_c は数、p_sel・p_wri は分母）で、行は 2 つの cohort の列を並べるので、どちらかの列で分が 0 より
大きいラインが「一部の日が」になる。※ 付きの数と注記つきの合計は、名指された日とラインの分を割り引いて読む。止まった問いの段が
I 入口ならクエリを skill `jrp-question` で差し替え（agent だけで進む）、S 選別か X 根拠化なら問いの文言と `not:` の
見直しを著者に渡す。v0 が出すのは分解まで。来週の 1 手は著者が選ぶ。数の定義の正本は
`src/jev_research_pipeline/pipeline/wbr.py` の docstring。

## 触ってはいけないもの

- `~/MyAI_Lab/daily-research/config.toml` は旧 pipeline と共有で gitignore（git で戻せない）。
  トラックを外すときは外したブロックを退避してから
- 実 vault / 実 store への書き込みを伴う `jrp run` は著者の指示があるときだけ。試験は
  `JRP_VAULT_DIR` / `JRP_STORE_DIR` を scratch に向けて回す（docs/pilot-log.md の運用）
