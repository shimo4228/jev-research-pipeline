# jrp — jev-research-pipeline

[English](README.md) | **日本語**

**追いかけている問いについて、毎朝リサーチのノートを。費用は LLM エージェントに任せていたときのおよそ 10 分の 1 です。新しい論文のふるい分けは判定専用のモデルが、文章だけを LLM が受け持ちます。**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![Status: pilot](https://img.shields.io/badge/status-pilot-orange.svg)](docs/pilot-log.md)

[ノートの見本](#毎朝届くもの) · [なぜ jrp か](#なぜ-jrp-か) · [試す](#試す) · [現状と限界](#現状と限界)

<p align="center">
  <img src="assets/overview.ja.svg" width="540" alt="「あなたの問い」を中心に 4 つの枠が回るループの図。毎朝、新しい論文とリポジトリを集める。Jev が一つずつ、あなたの問いの答えに役立つかを判定し、採る・保留・捨てるに振り分ける。LLM が問いごとに短い節を書く。その日のノートが Obsidian に届き、読む価値があったものに印を付けると、点線の矢印のとおり、その印が翌朝の実行に効く。">
</p>

jrp は、1 人で研究分野を追いかけるためのコマンドラインのツールです。テーマごとに、まだ答えの出ていない問いを 2〜4 本立てておくと、jrp は毎朝、輪番で次の 3 テーマを選び（1 朝に選ぶ数は設定で変えられます）、新しい論文とリポジトリをその問いに照らして確かめ、テーマごとに 1 枚の Markdown のノートをフォルダ（ふつうは Obsidian の vault）に書きます。ループを回すのは素の Python のコードです。ふるい分けの判定（この論文はこの問いの答えに役立つか、どの文が証拠か）はすべて Jev に聞きます。Jev は TypeSafe 社がホストする有料のモデルで、答えの決まった質問（はい・いいえや、いくつかの選択肢）に、答えごとの確率で答え、文章は書きません。説明の文章は、選んだ LLM（ChatGPT か Claude のサブスクリプション、または Qwen）が書き、自分の草稿を 1 回見直します。仕上がった節は Jev が採点します。ノートは英語・中国語・日本語で書けます。

## 毎朝届くもの

見本のノートからの抜粋です（日本語、Claude Opus が執筆。既定の書き手は、ChatGPT のプランで使う OpenAI のモデル GPT-6 Luna です）。

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

`[n]` はどれも、出典から一字一句そのまま写した 1 文を指し、言い換えではないので、引用は必ず確かめられます。読む価値があったものに印を付けると（なかったものには `[-]` と打ちます）、その印は翌朝の推薦の種（印を付けた論文に近い論文を探す）になります。印は、`jrp fit` が閾値の見直し案を出すときのラベルにもなります。閾値とは、Jev の確率で論文を採る・保留・捨てるに振り分ける境目です。`jrp fit` は案を出すだけで、適用はしません（[jrp の仕組み](docs/how-it-works.md#status)、英語）。ノートの全体を読んで、文章の出来はご自身で判断してください: [英語](docs/samples/agent-memory.en.md) · [中国語](docs/samples/agent-memory.zh.md) · [日本語](docs/samples/agent-memory.ja.md)（第三者の文はリンクに置き換えています。本文は jrp 自身の出力です）。

## なぜ jrp か

jrp は、前に使っていた仕組み（Web 検索ができる Opus のエージェントにループ全体を任せる）を置き換えるために作りました。

| | Opus のエージェント | jrp |
|---|---|---|
| 測った期間 | 2026-09-15〜09-22 | 2026-10-03〜10-07 |
| 何を読むかを決める | エージェント。1 朝 107〜242 回のモデルとの往復 | Jev。答えの決まった質問を 1 問ずつ。ループはコード |
| 書く | エージェント | LLM。新しい証拠が出た問いごとに短い節を 1 つ |
| 1 朝の費用（テーマ 3〜4 本） | $8〜15 | $1.1〜1.5（私の書き手は Claude のサブスクリプションで使う Opus 5.5。それを API 単価で換算し、Jev の $0.03〜0.17 を足したもの） |

この表が比べているのは費用で、品質ではありません。2 つは別々のノートを書いたので、上の見本を読んで判断してください。

- **往復が無いので安い。** エージェントは、モデルと往復するたびに、膨らんだ文脈を読み直します。jrp は Jev に 1 問 1 セント未満の小さな質問を数千問聞き、書き手は 1 節につきおよそ 2 回呼ぶだけです。ChatGPT か Claude のサブスクリプションなら、書き手の分はプランの利用枠から出ます。
- **検索をモデルに選ばせない。** 選ぶのを任された前のエージェントは、動かし始めて 3 か月で選んだ調査題目 238 のうち 88（37%）を同じ 1 つの主題に寄せました（[jrp の仕組み](docs/how-it-works.md#why-judgment-not-generation)、英語）。jrp では、実行中にモデルが検索語を書くことはありません。どの資料源を何回探すかはコードが決め、ノートは毎回、残した論文が何種類の分野にまたがるかを数えるので、それでも偏り始めれば数が減って分かります。

判定モデルで足りる理由: 論文が問いに関わるかどうかは、要旨から読み取れる判定です。この種の判定について、Carnegie Mellon 大学の独立した研究（[arXiv 2609.26550](https://arxiv.org/abs/2609.26550)、英語）は、人が盲検で裁定した結果を正解とする正解率で、Jev が最先端の LLM 判定役との差 3 パーセントポイント以内に収まり、料金は 0.36% だったと報告しています。導出を確かめる必要がある判定では差が開きます。jrp もすべての判定を信じるわけではなく、Jev の確信が低い論文はノートの保留（Review）の一覧に回し、あなたに判断を任せます。

## 試す

Python 3.12 と [uv](https://docs.astral.sh/uv/) のほかに、アカウントが 2 つ要ります。

- **Jev 用の TypeSafe の API キー**（[docs.typesafe.ai](https://docs.typesafe.ai)、英語）。有料で、無料枠は公表されていません。料金は入力 10 億トークンあたり $42（2026-10-07 時点）で、1 問およそ $0.00002 です。私の運用では 1 朝 $0.03〜0.17、1 か月で $1〜5 でした。ChatGPT か Claude をすでに契約していれば、新しく増える支払いは Jev だけです。Jev は差し替えられません。ループのふるい分けの判定はすべて Jev への質問で、手元で動くモデルを 4 つ試しましたが、どれも Jev の判定を再現できませんでした（[記事](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)）。
- **本文の書き手を 1 つ**。`JRP_PROSE_MODEL` で選びます。
  - ChatGPT のサブスクリプション（既定）、`openai-codex:gpt-6-luna`: Codex を含む ChatGPT のプラン。
  - Claude のサブスクリプション、`claude-code:claude-opus-5-5`: ログイン済みの Claude Code CLI（`claude auth login`）。
  - Qwen（従量課金）、`dashscope:qwen3.7-max`: `DASHSCOPE_API_KEY`（Alibaba Cloud Model Studio）。

**外に出るもの**: 問いの検索語は arXiv（OpenAlex 経由）、Hugging Face、GitHub、`TAVILY_API_KEY` を設定すれば Tavily へ、印を付けた論文と Jev が残した論文の ID は Semantic Scholar の推薦（`[-]` を付けた論文を負例として添え、まだ無いときは無作為の論文を使います）と、引用している論文を探す OpenAlex へ、Jev が判定する論文と箇所は TypeSafe へ、各節の証拠は選んだ書き手へ送られます。ノートは手元のフォルダに残ります。任意の Slack 通知が送るのはノートの名前、主張の件数、失敗の理由、未解決の問いが無い問いのファイルの場所で、ノートの中身は送られません。

そのうえで、インストールして最初の設定を書きます。インストールせずに試すときは、以下の `jrp init`、`jrp doctor`、`jrp try` の前に代わりに `uvx` を付けます。定期実行にはインストールした jrp が要ります。

```bash
uv tool install jrp
jrp init --lang ja              # ~/.config/jrp/ に env、config.toml、questions/agent-memory.md を書く
```

`~/.config/jrp/env` を開き、`JRP_VAULT_DIR`（ノートの置き場）と `TYPESAFE_API_KEY` を埋め、`JRP_PROSE_MODEL` で書き手を選びます（既定の書き手なら `jrp codex login` を 1 回実行します）。それから設定を確かめ、最初のノートを作ります。

```bash
set -a; source ~/.config/jrp/env; set +a
jrp doctor                      # 実行に要るものを、実行せずにすべて確かめる
jrp try --line agent-memory     # 最初のテーマを使い捨てのフォルダに 1 回だけ回し、ノートの置き場所を出す
```

`jrp try` は vault に何も書きません。macOS で毎朝走らせるときは、`jrp schedule install --hour 5` が launchd（macOS の定期実行の仕組み）の設定を書き、読み込み方を表示します。Linux の cron と systemd、Slack やデスクトップへの通知は [docs/scheduling.md](docs/scheduling.md)（英語）に、すべての設定は [docs/configuration.md](docs/configuration.md)（英語）にあります。

## 問いが探索を決める

実行が見つけられるものは問いで決まるので、あなたが書くのは問いです。テーマ（CLI では line、config.toml では track と呼びます）は `~/.config/jrp/config.toml` に `[tracks.<テーマ>]` を 2 行足せば作れ、その問いは `~/.config/jrp/questions/<テーマ>.md` に置く短いブロックに書きます。ブロックに書くことは [問いのファイル](docs/how-it-works.md#the-question-file)（英語）にあります。`jrp questions new --line <テーマ>` で、問いを書く手順を進める Claude Code のセッションが開きます。実行がこれらのファイルを書き換えることはありません。

## 現状と限界

- **試験運用（pilot）です。** 2026-09-24 から毎朝、私自身の 7 つのテーマで動かしています。macOS（launchd）と Linux（cron か systemd）で動きます。
- **中核は 1 社に依存しています。** TypeSafe が Jev を値上げすれば、あなたの費用もそのぶん上がります。提供をやめれば、代わりの判定役が無いので jrp は止まります。
- **閾値は手で調整したものです。** Jev の振り分けの閾値は、まだ印から再推定していないので、各ノートの保留（Review）の一覧には境界の論文が出てきます。
- **英語と中国語のノートは、まだ誰も読んでいません。** 私が読めるのは日本語だけです。英語と中国語のプロンプトは、Claude Opus が書いた草稿の自動の測定だけで受け入れました（開発時の `jrp prose bench` で、草稿を出典と照らす Opus の採点役に通ったのは、英語 32 件中 28 件、中国語 32 件中 32 件）。既定の書き手の GPT-6 Luna は、どちらの言語でもまだ測っていません。英語か中国語を読む方が見本を読んだら、読みにくいところを [読みの感想の issue](https://github.com/shimo4228/jev-research-pipeline/issues/new?template=reading-feedback.yml)（どの言語でも可。引用は短く）で教えてください。

## さらに詳しく

- [jrp の仕組み](docs/how-it-works.md)（英語）: 毎朝の実行の手順、ノートの中身、問いのファイル、資料の集め方、文章の書かせ方と点検、費用の内訳、エージェントでなく判定モデルに聞く理由。
- [設計の記録](docs/design/pipeline-design.md)（英語）: すべての判断と、その根拠にした証拠。
- 土台: [TypeSafe Jev](https://docs.typesafe.ai) を [Pydantic AI の `typesafe:` モデル](https://pydantic.dev/docs/ai/models/typesafe/)（英語）経由で使い、書き手には [Pydantic AI の OpenAI Codex provider](https://github.com/pydantic/pydantic-ai/blob/main/docs/models/openai-codex.md)（英語）、[Claude Code](https://docs.anthropic.com/en/docs/claude-code)（英語）、[DashScope の Qwen](https://www.alibabacloud.com/help/en/model-studio/models)（英語）を使います。

## 著者のほかの仕事

Jev を使った実験は、どれも記事にしています（日本語は Zenn、英語は Dev.to）。

- **[LLMに任せていたリサーチの判定を、判定専用モデルJevに移す](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)**（[English](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj)）: jrp そのものの経緯です。Opus のエージェントがしていた判定のどれを Jev に移したか、文章をなぜ LLM に残したかを書きました。
- **[文章を書かないモデルJevのスキル選択は、0.3秒でOpusにどこまで近づくか](https://zenn.dev/shimo4228/articles/jev-vs-opus-skill-selection)**（[English](https://dev.to/shimo4228/how-close-to-opus-does-jev-a-model-that-writes-no-text-get-at-skill-selection-in-03-seconds-1nfj)）: 150 件の状況で、Jev と Opus の一致は Opus 同士の一致の約半分、費用は約 560 分の 1 でした。
- **[Jevの判断をローカルで再現するには何が要るか](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)**（[English](https://dev.to/shimo4228/what-does-it-take-to-reproduce-jevs-decisions-locally-3i0n)）: 手元で動く 4 つのモデルに同じ 150 件を解かせ、4 つとも、それぞれ別の理由で届きませんでした。
- **[JevのスキルルーターをClaude Codeに足して、スキル一覧を書き換える手前で引き返した](https://zenn.dev/shimo4228/articles/jev-retrofit-limits)**（[English](https://dev.to/shimo4228/i-added-jevs-skill-router-to-claude-code-and-turned-back-just-before-rewriting-the-skill-listing-34in)）: どのスキルがプロンプトに合うかを Jev に尋ねるフックと、それが強いモデルの助けになりにくい理由。

関連するリポジトリ:

- **[jev-skill-router](https://github.com/shimo4228/jev-skill-router)**: プロンプトのたびにどのスキルが合うかを TypeSafe の Jev に尋ねてログに残す Claude Code のフック。1 週間動かして外し、参照実装として残しています。jrp と並べて読むと、Jev の効果がエージェントのループの中では読めず、固定したパイプラインでは読める理由が分かります。
- **[daily-research](https://github.com/shimo4228/daily-research)**: 自分の研究リポジトリについて調べ、その結果を解説として返す仕組み。毎朝、輪番で選ばれた私の研究プロジェクトのリポジトリの中で `claude -p` が動き、解説ノートを Obsidian vault に書きます。「[なぜ jrp か](#なぜ-jrp-か)」の表が比べている Opus のエージェントは、この仕組みです。
- **[shimo4228（ハブ）](https://github.com/shimo4228/shimo4228)**: 私のハブ。長期の研究プロジェクトとその DOI（このパイプラインが見張っている Agent Knowledge Cycle や Authorship Strategy などのテーマもここに並びます）と、Claude Code と TypeSafe Jev のためのツールがあります。

記事の一覧は [Zenn](https://zenn.dev/shimo4228)（日本語）と [Dev.to](https://dev.to/shimo4228)（英語）にあります。

## ライセンス

MIT です。[LICENSE](LICENSE) を見てください。

<details>
<summary>ツールと AI アシスタント向けの資料</summary>

jrp（jev-research-pipeline）は、1 人で研究分野を追いかける人のためのコマンドラインのリサーチ監視ツールです。毎朝、あなたが書いた未解決の問いに照らして新しい論文とリポジトリを確かめ、テーマごとに 1 枚の Markdown のノートを、ふつうは Obsidian の vault に書きます。

これがあるのは、著者が前に使っていた仕組み（[daily-research](https://github.com/shimo4228/daily-research) で、Web 検索ができる Opus のエージェントにループ全体を任せていたもの）が、1 朝 107〜242 回のモデルとの往復で $8〜15 かかり、1 つの主題に偏った（動かし始めて 3 か月で選んだ 238 の調査題目のうち 88）からです。jrp では、ループは素の Python のコードが持ち、どの資料源を探すかもコードが決めます。ふるい分けの判定（この論文はこの問いの答えに役立つか、どの文が証拠か）はすべて TypeSafe 社の Jev（答えの決まった質問に確率で答え、文章は書かないホスト型のモデル）に聞き、文章は LLM が書いて自分の草稿を 1 回見直し、仕上がった節を Jev が採点基準に沿って採点します。

ライセンスは MIT です。言語は Python 3.12 で、uv で入れます（`uv tool install jrp`。PyPI のパッケージ名は `jrp`）。状態は試験運用（pilot）で、このリポジトリで手で保守し、著者が 2026-09-24 から毎朝、自分の 7 つのテーマで動かしています。macOS（launchd）と Linux（cron か systemd）で動きます。有料の鍵として、Jev 用の TypeSafe の API キーが必要です（有料で無料枠は公表されていません。2026-10-07 時点で入力 10 億トークンあたり $42、著者の運用で 1 朝 $0.03〜0.17）。Jev は差し替えられません。書き手は、Codex を含む ChatGPT のプラン（`openai-codex:gpt-6-luna`、既定）、Claude Code CLI 経由の Claude のサブスクリプション（`claude-code:claude-opus-5-5`）、従量課金の DashScope の Qwen（`dashscope:qwen3.7-max`）のどれか 1 つです。ノートは英語・中国語・日本語で書け、人が読んで確かめたのは日本語のプロンプトだけです（著者自身が目隠しで読み比べました）。外に出るデータとして、問いの検索語は arXiv（OpenAlex 経由）、Hugging Face papers、GitHub、鍵があれば Tavily へ、印を付けた論文と残した論文の ID は Semantic Scholar の推薦 API（`[-]` を付けた論文を負例として添え、まだ無いときは無作為の論文を使う）と、引用している論文を探す OpenAlex へ、Jev が判定する文章は TypeSafe へ、各節の証拠は選んだ書き手へ送られます。任意の Slack 通知が送るのは、ノートごとの名前と主張の件数、実行がうまくいかなかった理由（下書きや資料源の失敗など）やテーマが失敗した理由、未解決の問いが無い問いのファイルの場所で、主張そのものは送りません。

例: `jrp init --lang ja` が `~/.config/jrp/{env, config.toml, questions/agent-memory.md}` を書きます。env ファイルに `JRP_VAULT_DIR`、`TYPESAFE_API_KEY`、`JRP_PROSE_MODEL` を埋めたあと、`jrp doctor` が実行せずに設定を確かめ、`jrp try --line agent-memory` がそのテーマを使い捨てのフォルダに 1 回だけ回してノートの置き場所を表示します。ノートは、新しい証拠が出た問いごとに短い節を 1 つ持ちます。`[n]` はどれも出典から一字一句写した 1 文を指し、確信の低い論文は保留（Review）の一覧に回り、節ごとの「読む価値があった」の印が翌朝の実行に効きます。測った費用は、テーマ 3〜4 本で 1 朝 $1.1〜1.5（2026-10-03〜10-07、書き手の Opus 5.5 を API 単価で換算し、Jev を足したもの）で、置き換えた Opus のエージェントは $8〜15 でした。

参照先は、[docs/how-it-works.md](docs/how-it-works.md)（毎朝の実行の手順、費用、問いのファイル、英語）、[docs/design/pipeline-design.md](docs/design/pipeline-design.md)（すべての判断と根拠、英語）、[docs/configuration.md](docs/configuration.md) と [docs/scheduling.md](docs/scheduling.md)（英語）、[docs/pilot-log.md](docs/pilot-log.md)（英語）、[docs/samples/](docs/samples/) のノートの見本、著者のハブ [shimo4228/shimo4228](https://github.com/shimo4228/shimo4228) です。

</details>
