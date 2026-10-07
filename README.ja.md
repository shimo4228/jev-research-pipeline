# jrp — jev-research-pipeline

[English](README.md) | **日本語**

**追いかけている問いについて、毎朝リサーチのノートを。費用は LLM エージェントに任せていたときのおよそ 10 分の 1 です。新しい論文のふるい分けは判定専用のモデルが、文章だけを LLM が受け持ちます。**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![Status: pilot](https://img.shields.io/badge/status-pilot-orange.svg)](docs/pilot-log.md)

[ノートの見本](#毎朝届くもの) · [なぜ jrp か](#なぜ-jrp-か) · [試す](#試す) · [現状と限界](#現状と限界)

<p align="center">
  <img src="assets/overview.ja.svg" width="540" alt="「あなたの問い」を中心に 4 つの枠が回るループの図。毎朝、新しい論文と repo を集める。Jev が一つずつ、あなたの問いの答えに役立つかを判定し、採る・保留・捨てるに振り分ける。LLM が問いごとに短い節を書く。その日のノートが Obsidian に届き、読む価値があったものに印を付けると、点線の矢印のとおり、その印が翌朝の実行に効く。">
</p>

jrp は、1 人で研究分野を追いかけるためのコマンドラインのツールです。テーマごとに、まだ答えの出ていない問いを 2〜4 本立てておくと、jrp は毎朝、輪番で次の 3 テーマを選び（数は設定で変えられます）、新しい論文とリポジトリ（arXiv、Hugging Face、Semantic Scholar、OpenAlex、GitHub）をその問いに照らして確かめ、テーマごとに 1 枚の Markdown のノートをフォルダ（ふつうは Obsidian の vault）に書きます。ループを回すのは素の Python のコードです。途中の判定（この論文はこの問いの答えに役立つか、どの文が証拠か）はすべて Jev に聞きます。Jev は TypeSafe 社がホストする有料のモデルで、答えの決まった質問に確率で答え、文章は書きません。説明の文章だけを、選んだ LLM（ChatGPT か Claude のサブスクリプション、または Qwen）が書きます。ノートは英語・中国語・日本語で書けます。

## 毎朝届くもの

見本のノートからの抜粋です（日本語、Claude Opus が執筆。既定の書き手は GPT-6 Luna です）。

> **LLM エージェントの記憶の設計は、正答をどれだけ変えるか**
>
> ソフトウェア作業を何回かのセッションに分けて行うエージェントの試験の追加の検証では、外部の記憶を持たない条件で 180 回中 21 回だった合格が、記憶を持たせた三つの条件では 180 回中 82〜97 回に増えた。科学論文を読んで答えるエージェントでは、制御役・資料・呼び出し回数の上限 6 回をそろえたうえで、記録の形だけを変えた。順序のない概念のつながりから、順序を保った経路の形の記録に替えると、正しい出典を拾える割合が 61.3% から 82.9% に上がった。[3][2]
>
> *（このあと研究ごとに、設定と数値を述べる短い段落が続きます）*
>
> 【推論】二つの研究を合わせると、このラインにとって次の見方がありうる。記憶を持つかどうかの差は大きい。一方、どの記憶方式を選ぶかの差は、測り方によっては見えにくい。…
>
> **証拠:** MemCodex（arXiv）· PathAnchor（arXiv）· ほか 3 件\
> ☐ 読む価値があった

`[n]` はどれも、出典から一字一句そのまま写した 1 文を指し、言い換えではないので、引用は必ず確かめられます。読む価値があったものに印を付けると、その印は翌朝の推薦の種（印を付けた論文に近い論文を探す）になり、`jrp fit` が閾値の見直し案（適用するのはあなたです）を出すときのラベルにもなります。ノートの全体を読んで、文章の出来はご自身で判断してください: [英語](docs/samples/agent-memory.en.md) · [中国語](docs/samples/agent-memory.zh.md) · [日本語](docs/samples/agent-memory.ja.md)（第三者の文はリンクに置き換えています。本文は jrp 自身の出力です）。

## なぜ jrp か

jrp は、前に使っていた仕組み（Web 検索ができる Opus のエージェントにループ全体を任せる）を置き換えるために作りました。

| | Opus のエージェント | jrp |
|---|---|---|
| 測った期間 | 2026-09-15〜09-22 | 2026-10-03〜10-07 |
| 何を読むかを決める | エージェント。1 朝 107〜242 回のモデルとの往復 | Jev。答えの決まった質問を 1 問ずつ。ループはコード |
| 書く | エージェント | LLM。新しい証拠が出た問いごとに短い節を 1 つ |
| 1 朝の費用（テーマ 3〜4 本） | $8〜15 | $1.1〜1.5（書き手を Opus 5.5 の API 単価で換算し、Jev の $0.03〜0.17 を足したもの） |

この表が比べているのは費用で、品質ではありません。2 つは別々のノートを書いたので、上の見本を読んで判断してください。

- **往復が無いので安い。** エージェントは、モデルと往復するたびに、膨らんだ文脈を読み直します。jrp は Jev に 1 問 1 セント未満の小さな質問を数千問聞き、書き手は 1 節につきおよそ 2 回呼ぶだけです。ChatGPT か Claude のサブスクリプションなら、書き手の分はプランの利用枠から出ます。
- **1 つのテーマに偏らない。** 前のエージェントは、動かし始めて 3 か月で選んだ 238 の調査題目のうち、88（37%）が同じ 1 つの主題でした。jrp では、実行中にモデルが検索語を書くことはありません。どの資料源を何回探すかはコードが決め、ノートは毎回、残した論文が何種類の分野にまたがるかを数えるので、偏り始めると数が減って分かります。

判定モデルで足りる理由: 論文が問いに関わるかどうかは、要旨から読み取れる判定です。この種の判定について、Carnegie Mellon 大学の独立した研究（[arXiv 2609.26550](https://arxiv.org/abs/2609.26550)、英語）は、Jev が最先端の LLM 判定役との差 3 パーセントポイント以内に収まり、料金は 0.36% だったと報告しています。導出を確かめる必要がある判定では差が開きます。jrp もすべての判定を信じるわけではなく、Jev の確信が低い論文はノートの Review の一覧に回し、あなたに判断を任せます。

経緯の全体は記事「[LLMに任せていたリサーチの判定を、判定専用モデルJevに移す](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)」に書きました。

## 試す

Python 3.12 と [uv](https://docs.astral.sh/uv/) のほかに、アカウントが 2 つ要ります。

- **Jev 用の TypeSafe の API key**（[docs.typesafe.ai](https://docs.typesafe.ai)、英語）。有料で、無料枠は公表されていません。料金は入力 10 億トークンあたり $42（2026-10-07 時点）で、1 問およそ $0.00002 です。私の運用では 1 朝 $0.03〜0.17、1 か月で $1〜5 でした。ChatGPT か Claude をすでに契約していれば、新しく増える支払いは Jev だけです。Jev は差し替えられません。ループの判定はすべて Jev への質問で、手元で動くモデルを 4 つ試しましたが、どれも Jev の判定を再現できませんでした（[記事](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)）。
- **本文の書き手を 1 つ**。`JRP_PROSE_MODEL` で選びます。
  - ChatGPT のサブスクリプション（既定）、`openai-codex:gpt-6-luna`: Codex を含む ChatGPT のプランと、1 回の `jrp codex login`。
  - Claude のサブスクリプション、`claude-code:claude-opus-5-5`: ログイン済みの Claude Code CLI（`claude auth login`）。
  - Qwen（従量課金）、`dashscope:qwen3.7-max`: `DASHSCOPE_API_KEY`（Alibaba Cloud Model Studio）。

そのうえで、次を実行します。

```bash
uv tool install jrp
jrp init --lang ja              # ~/.config/jrp/ に env、config.toml、questions/agent-memory.md を書く
```

`~/.config/jrp/env` を開き、`JRP_VAULT_DIR`（ノートの置き場）と `TYPESAFE_API_KEY` を埋め、`JRP_PROSE_MODEL` で書き手を選びます。それから設定を確かめ、最初のノートを作ります。

```bash
set -a; source ~/.config/jrp/env; set +a
jrp doctor                      # 実行に要るものを、実行せずにすべて確かめる
jrp try --line agent-memory     # 使い捨てのフォルダに 1 回だけ回し、ノートの置き場所を出す
```

`jrp try` は vault に何も書きません。macOS で毎朝走らせるときは、`jrp schedule install --hour 5` が launchd の定期実行の設定を書き、読み込み方を表示します。Linux の cron と systemd、Slack やデスクトップへの通知は [docs/scheduling.md](docs/scheduling.md)（英語）に、すべての設定は [docs/configuration.md](docs/configuration.md)（英語）にあります。インストールせずに試すときは、`jrp init`、`jrp doctor`、`jrp try` の前に `uvx` を付けます。

## 問いが探索を決める

実行が見つけられるものは問いで決まるので、あなたが書くのは問いです。テーマ（CLI では line、config.toml では track と呼びます）は `~/.config/jrp/config.toml` に名前つきの `[tracks.<テーマ>]` を 2 行足せば作れ、その問いは `~/.config/jrp/questions/<テーマ>.md` に置く短いブロックに書きます。ブロックには、問いそのもの、何についての問いで *ない* か、資料源ごとの検索語、必ず残すべき論文（その論文が落ちた日は、ふるい分けがずれた印としてノートに出ます）を書きます。`jrp init` が例のテーマを書き、新しいテーマを `config.toml` に足したあとは、`jrp questions new --line <テーマ>` で、その問いを書く手順を進める Claude Code のセッションが開きます。実行がこれらのファイルを書き換えることはありません。

## 現状と限界

- **試験運用（pilot）です。** 2026-09-24 から毎朝、私自身の 7 つのテーマで動かしています。macOS（launchd）と Linux（cron か systemd）で動き、ライセンスは MIT です。
- **中核は 1 社に依存しています。** TypeSafe が Jev を値上げすれば、あなたの費用もそのぶん上がります。提供をやめれば、代わりの判定役が無いので jrp は止まります。
- **閾値は手で調整したものです。** Jev の振り分けの閾値は、まだ印から再推定していないので、各ノートの Review の一覧には境界の論文が出てきます。
- **英語と中国語のノートは、まだ誰も読んでいません。** 私が読めるのは日本語だけです。英語と中国語のプロンプトは、Claude Opus が書いた草稿の自動の測定だけで受け入れました（草稿を出典と照らす判定を通ったのは、英語 32 件中 28 件、中国語 32 件中 32 件）。既定の書き手の GPT-6 Luna は、どちらの言語でもまだ測っていません。英語か中国語を読む方が見本を読んだら、読みにくいところを [読みの感想の issue](https://github.com/shimo4228/jev-research-pipeline/issues/new?template=reading-feedback.yml)（どの言語でも可。引用は短く）で教えてください。

## さらに詳しく

- [jrp の仕組み](docs/how-it-works.md)（英語）: 毎朝の実行の手順、ノートの中身、問いのファイル、資料の集め方、文章の書かせ方と点検、費用の内訳、エージェントでなく判定モデルに聞く理由。
- [設計の記録](docs/design/pipeline-design.md)（英語）: すべての判断と、その根拠にした証拠。
- 土台: [TypeSafe Jev](https://docs.typesafe.ai) を [Pydantic AI の `typesafe:` モデル](https://pydantic.dev/docs/ai/models/typesafe/)（英語）経由で使い、書き手には [Pydantic AI の OpenAI Codex provider](https://github.com/pydantic/pydantic-ai/blob/main/docs/models/openai-codex.md)（英語）、[Claude Code](https://docs.anthropic.com/en/docs/claude-code)（英語）、[DashScope の Qwen](https://www.alibabacloud.com/help/en/model-studio/models)（英語）を使います。

## 著者のほかの仕事

Jev を使った実験は、どれも記事にしています（日本語は Zenn、英語は Dev.to）。

- 「[文章を書かないモデルJevのスキル選択は、0.3秒でOpusにどこまで近づくか](https://zenn.dev/shimo4228/articles/jev-vs-opus-skill-selection)」: 150 件の状況で、Jev と Opus の一致は Opus 同士の一致の約半分、費用は約 560 分の 1 でした。
- 「[Jevの判断をローカルで再現するには何が要るか](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)」: 手元で動く 4 つのモデルに同じ 150 件を解かせ、4 つとも、それぞれ別の理由で届きませんでした。
- 「[JevのスキルルーターをClaude Codeに足して、スキル一覧を書き換える手前で引き返した](https://zenn.dev/shimo4228/articles/jev-retrofit-limits)」: どのスキルがプロンプトに合うかを Jev に尋ねるフック（[コード](https://github.com/shimo4228/jev-skill-router)）と、それが強いモデルの助けになりにくい理由。

このパイプラインが見張っているテーマは、[Agent Knowledge Cycle](https://github.com/shimo4228/agent-knowledge-cycle) や [Authorship Strategy](https://github.com/shimo4228/authorship-strategy) など、私自身の長期のプロジェクトです。すべてのプロジェクトは [github.com/shimo4228](https://github.com/shimo4228) から、記事の一覧は [Zenn](https://zenn.dev/shimo4228)（日本語）と [Dev.to](https://dev.to/shimo4228)（英語）からたどれます。
