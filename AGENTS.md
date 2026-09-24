# jev-research-pipeline — agent 向け作業手順

入口は [README.md](README.md)、設計の正本は [docs/design/pipeline-design.md](docs/design/pipeline-design.md)。
機械ゲートは `.claude/verify.sh`（offline、PASS 時は無出力）。ここには repo 固有の作業手順だけを置く。

## 問いとクエリを書く

問い（`questions/<slug>.md`）は著者が持つ。著者が気づいたときに更新する — pipeline が自動で
新設・退役することはない（design「Authored queries」節）。agent がやるのは、著者の指示で
問いを書き換えることと、その問いの検索クエリを書くこと。

**いつ**: 問いを足した・書き換えたとき / あるラインの note に 2 週間続けて動いた問いが無いとき /
著者に頼まれたとき。

1. **問いの block を読む**: 見出し・`brief`・`method`・`evidence`・`not`。クエリはこの問いの
   答えを動かしうる文献を拾うためのもので、ラインの語彙全般ではない。`not:` の話題に当たる語は
   クエリに入れない
2. **今の語彙を確かめる（記憶から書かない）**: この分野の用語は週単位で変わる。直近の arXiv /
   HF papers / GitHub を検索して、実際の論文・repo が使っている語を拾う。store にこの問いで
   Keep された source があれば、そのタイトルの語も使う
3. **アダプタごとに書く**（原則英語、1 行 1 クエリ、1 アダプタにつき 1–2 本）:
   - `- arxiv:` 2–4 語。全語 AND（`all:w1 AND all:w2`）なので語を足すほど狭まる。引用符・
     ブール演算子は書かない
   - `- github:` 短いキーワード。`topic:x` などの GitHub 修飾子は使える
   - `- hf:` 自然な英語の句（HF papers の検索）
   - `- web:` Tavily の Web 検索（`TAVILY_API_KEY` が要る。無料枠は月 1,000 回、basic 1 回 1 クレジット）。
     一次資料が日本語の問い（個人ブログ・note など）は日本語のクエリも書いてよい
   - 問いの見出し・`brief` は変えない（文面を変えたら `version` を上げる — evidence は新しい
     版に引き継がれない）
4. **試し打ちする**（repo root で。live に 1 クエリ 1 リクエスト、store には何も書かない）:

   ```bash
   set -a; source ~/.config/jrp/env; set +a
   uv run jrp queries check --line <slug>
   ```

   - 0 件 → 語を減らす・言い換える
   - 上位が別分野 → 語を足す・分野の語に替える
   - 429 の `失敗` → 相手の rate limit。時間を置く。繰り返し回さない（arXiv は特に厳しい）
   - 「クエリ未設定」の問いは実行時に keyword 検索を 1 本も送らない（他の net は走る）。必ず書く
5. **commit して main に入れる**。launchd は main の checkout の `questions/` を読むので、
   次の tick から効く

## 本文を磨く（prose bench）

本番の run は Claude を呼ばない。本文の改善は開発時のループで行う。ループの組み方の正本は
skill: `author-calibrated-eval`、この repo での経緯と決定は design「Prose bench」。材料は非公開の
`<JRP_STORE_DIR>/prose_bench/` にだけ置く（第三者の原文を含むため）。

役割: 読みやすさの正解は**著者の blind 読み**。LLM の判定役（`.claude/agents/prose-judge.md`）は
**忠実さの足切りだけ**を草稿 1 本ずつ判定する（`docs/prose-rubric.md`）。形式はコードが見る。

1. `uv run jrp prose export --from <store> ...` — 本文のある question-day を固定する（dev / holdout は id で決まる）
2. `uv run jrp prose bench --variant <name> --prompt bench/prose/prompts/<file> --check bench/prose/prompts/check6.md --sources --model qwen3.7-max --cases <ids>`
   — 候補の草稿を作る（磨く作業は本番と別の無料枠のモデルで。難所セットの数件に絞る）
3. `uv run jrp prose read --variants <a>,<b>,... --cases <ids> --out <scratchpad>/read.md`
   — 著者向けの blind 読み比べを作り、著者に送る。聞くのは「一番良いのはどれか・なぜか」か
   「読めるか・どこで止まったか」だけ。対応表は `read.key.json`
4. `uv run jrp prose gate --variant <name> --cases <ids>` — 草稿 1 本ごとの gate ファイルを作り、
   1 ファイルにつき prose-judge を 1 つ起動して verdict を書かせる。worktree のセッションからは
   base の store に Write できない（hook）ので、書き出し先は session の scratchpad にする
5. `uv run jrp prose gate --variant <name> --verdicts <dir>` — pass / fail の集計
6. 難所セットで著者の読みと足切りの両方を通ったら、holdout から型の違う数件で 3〜5 を繰り返す

現行の本文プロンプトの候補は `bench/prose/prompts/v7.md` + `check6.md`（著者の読みと足切りを
難所セットと holdout で通した版）。

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
