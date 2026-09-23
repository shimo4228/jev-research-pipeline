<!-- jrp:questions:authorship -->

## 生成エンジン最適化（GEO）で、AI 検索や AI の回答に拾われ引用されるために実際に効いている手段は何か
- slug: geo-what-works
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: ChatGPT・Perplexity・Gemini・AI Overviews などで、出典として拾われる・名前が出る率を動かした手段（書き方、構造、引用・統計の入れ方、置き場所）。個人の作り手が真似できる規模のもの
- method: 引用率・言及率の前後比較や A/B
- method: GEO の実験・ベンチマーク
- evidence: 施策と測定がセットになっているもの
- not: 測定のない how-to やチェックリスト
- not: 従来 SEO の順位対策だけのもの
- arxiv: GEO generative engines
- github: generative engine optimization benchmark
- hf: AI search visibility

## 知識を LLM に届けるための新しい置き場所・置き方には何があり、どれが実際に使われているか
- slug: llm-knowledge-placement
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: Web ページ以外の経路 — llms.txt、MCP サーバ、エージェント向け API や docs、データセット公開、コードリポジトリや DeepWiki 型の自動 wiki、パッケージレジストリなど。LLM やエージェントが知識を見つけて使う経路として、どれが採用され、どれが拾われている証拠があるか
- method: 実践者の導入記録
- method: AI エージェント・検索が実際に参照したログや実測
- evidence: 導入した結果（拾われた・使われた）が示されているもの
- not: 規格や形式の紹介だけで、使われた証拠のないもの
- arxiv: llms.txt
- github: llms.txt
- github: mcp documentation server
- hf: agent readable documentation

## LLM 検索や AI エージェントは、何を手がかりに情報源を選んで引用しているか
- slug: llm-source-selection
- version: 1
- status: open
- opened: 2026-09-23
- retire: 六ヶ月 evidence が増えなければ閉じる
- brief: AI 検索・deep research・コーディングエージェントが、検索結果の中からどのページや文書を読み、どれを引用するかを決める仕組み（検索 API の順位、鮮度、ドメインの信頼、構造、既存の引用関係など）。置き方の戦略を仕組みから逆算するための材料
- method: 引用元の大規模な集計・分析
- method: 検索・引用の挙動を操作した実験
- method: 提供元の公式 docs
- evidence: 集計か実験の数値、または提供元の一次情報
- not: 推測だけの「AI に好かれるコツ」
- arxiv: AI search citation
- hf: AI search citation
