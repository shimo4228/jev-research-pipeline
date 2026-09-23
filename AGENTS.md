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

本番の run は Claude を呼ばない。本文の改善は開発時のループで行う（design「Prose bench」、
`docs/prose-rubric.md`）。材料は非公開の `<JRP_STORE_DIR>/prose_bench/` にだけ置く。

1. `uv run jrp prose export --from <store> ...` — 本文のある question-day を固定する
2. 候補のプロンプトを `bench/prose/prompts/<name>.md` に書き、
   `uv run jrp prose bench --variant <name> --prompt <file> [--sources] --model qwen3.7-max`
   （基準版は `--prompt` 無し。磨く作業は本番と別の無料枠のモデルで）
3. `uv run jrp prose pairs --a <基準> --b <候補>` — case ごとに順番違いの 2 ファイルができる
4. 判定: pair ファイル 1 つにつき、文脈を持たない Opus のサブエージェントを 1 つ起動し、
   ファイルだけを読ませて `pairs/<a>__vs__<b>/verdicts/<同名>.json` に書かせる。
   実装者（このセッション）は判定に口を出さない
5. `uv run jrp prose tally --a <基準> --b <候補>` — 両方の順番で一致した軸だけが勝ち
6. 採用は dev で勝ち、holdout で負けないとき。最後に著者が数件を blind で読む

## 触ってはいけないもの

- `~/MyAI_Lab/daily-research/config.toml` は旧 pipeline と共有で gitignore（git で戻せない）。
  トラックを外すときは外したブロックを退避してから
- 実 vault / 実 store への書き込みを伴う `jrp run` は著者の指示があるときだけ。試験は
  `JRP_VAULT_DIR` / `JRP_STORE_DIR` を scratch に向けて回す（docs/pilot-log.md の運用）
