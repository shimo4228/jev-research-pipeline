---
date: 2026-10-01
category: jrp
kind: report
tags: [jrp, agent-memory]
topic: "Agent memory — 1 問い"
line: agent-memory
jrp_report: "https://shimo4228.github.io/shimo4228/jrp/report/f37bc927de604c7f9917c890fff29782"
---

<!-- jrp のノートの見本 (JRP_NOTE_LANG=ja)。2026-10-01 に 1 ラインを試しに回したもの。第三者の文は省いている: claim の原文、出典の横の抜粋、未判定の claim の文はリンクだけにした。本文と運用欄は jrp 自身の出力。 レイアウトは 2026-10-04 の描画 (plan note-layout) で描き直した。 -->

# Agent memory — 2026-10-01

## LLM エージェントの記憶の設計は、正答をどれだけ変えるか

### 今日の変化

ソフトウェア作業を何回かのセッションに分けて行うエージェントの試験の追加の検証では、外部の記憶を持たない条件で 180 回中 21 回だった合格が、記憶を持たせた三つの条件では 180 回中 82〜97 回に増えた。科学論文を読んで答えるエージェントでは、制御役・資料・呼び出し回数の上限 6 回をそろえたうえで、記録の形だけを変えた。順序のない概念のつながりから、順序を保った経路の形の記録に替えると、正しい出典を拾える割合が 61.3% から 82.9% に上がった。[3][2]

**DreamBench-SWE**

この研究は、ソフトウェアを扱うエージェントが、過去の作業の記憶を正しく使えるかを試すためのものである。試験は複数のセッションにまたがる。後のセッションの作業は、前のセッションで出てきた証拠に頼る作りになっている。その証拠は、その場の情報からは推し量れない。採点には、エージェントからは見えない実行可能な判定役(hidden oracle)を使う。研究者は最初の大規模な試験を行い、その後に追加の検証を行った。追加の検証は、最初の試験の後に設計した。結果を見る前に計画を固定し、事前に登録してある(preregistered)。追加の検証では、四つの条件で計 360 の作業単位をすべて終えた。条件ごとの試行数は 180 回である。四つの条件は、記憶なし、出来事をそのまま書き写して残す記憶、型付きの記録と生の記録を併せた参照用の記憶、外部サービスで文字どおりに保存する記憶の一つの設定である。[3] (S3)

外部の記憶なしでは、合格は 180 回中 21 回だった。記憶を持たせた三つの条件では 82〜97 回だった。記憶ありの三条件は、どれも記憶なしと比べて差があると判断された。この判断は、複数の比較をまとめて補正した検定(Holm 補正)の後でも変わらなかった。一方、記憶ありの方式どうしの差ははっきりしなかった。文字どおりに保存する設定と、そのまま書き写す記憶を比べた結果は、確証にならなかった。この結果は、分析の条件を変えると揺らいだ。参照用の記憶との差は、統計的に差があるとは判断されなかった。最初の試験でも主な比較は 180 回中 95 回と 89 回だった。この比較でも差は出ておらず、著者はこれを同等の証拠ではないとしている。[3] (S3)

**PathAnchor**

この研究は、科学の論文を読んで答えるエージェントを対象にしている。こうしたエージェントは、関係する文章を取り出せても誤りを起こすことがある。一つは、物事の機能上の順序を失うことである。ほかに、複数の出典の証拠を混ぜることもある。さらに、取り出した記録が支える範囲を超えた結論を述べることもある。PathAnchor は、証拠を道筋の形で保存する作業場を使う。文章や抜き出した概念を、ばらばらの単位として扱わない。材料からセンサー、信号、システムへと続く道筋を、出典に結びつけて取り出す。その道筋は、各段階の役割と向きを保つ。各段階のつながりを支える証拠も保つ。制御役は、読み取り専用の三つの道具を使う。一つ目は論文ごとの道筋を探す道具である。二つ目は候補の出典をまたいで道筋をたどる道具である。三つ目は元の証拠をそのまま開く道具である。最後に、主張ごとに出典を付けた答えを返す。その際、証拠が及ぶ範囲も明示する。評価には、柔らかく曲がるセンサーに関する 120 問を使った。問いには、論文 1 本で答えるものと、複数の論文にまたがるものがある。[2] (S2)

研究者は、資料の整理の仕方の効き目を確かめた。制御役、資料の集まり、道具を呼ぶ回数の上限 6 回はそろえた。そのうえで、順序のない概念のつながり(concept graph)を、道筋の形の記録に置き換えた。すると、必要な出典を拾えた割合(source recall)は 61.3% から 82.9% に上がった。答えの中の主張がすべて、実際に開いた証拠を引用していた答えの割合は、69.2% から 90.0% に上がった。道具を呼んだ回数も減った。著者は、エージェントの資源を固定した条件でも、証拠の整理の仕方が拾える出典と引用の漏れの少なさを左右すると述べている。[2] (S2)

【推論】二つの研究を合わせると、このラインにとって次の見方がありうる。記憶を持つかどうかの差は大きい。一方、どの記憶方式を選ぶかの差は、測り方によっては見えにくい。DreamBench-SWE では、記憶ありの方式どうしの差がはっきりしなかった。PathAnchor では、ほかの条件をそろえて記録の形だけを変えると、出典を拾える割合が大きく動いた。もしこの違いが、作業の種類や記録に求められる順序の重要さから来ているなら、設計の効き目は課題ごとに大きく違うことになる。次に確かめたいのは、条件をそろえた比較で、記録の形の違いが最終的な正答や合格の数まで動かすかである。PathAnchor の比較で動いたのは、出典の拾い方と引用の完全さだった。DreamBench-SWE の数字は 180 回という規模であり、方式どうしの小さな差を見分けるには足りないおそれもある。この読みが外れるとすれば、次のような場合である。科学論文での差が、その分野の材料からシステムへという特有の順序に強く依存していたなら、一般の記憶設計には広がらない。また、ソフトウェア作業での方式どうしの差が、試行を増やしてもやはり小さいままなら、この読みも外れる。

### 証拠

- MemCodex: Self-Programming Hierarchical Memory for Language Agents — [link](https://arxiv.org/abs/2609.39765)
- PathAnchor: Path-Structured Evidence for Scientific Agents — [link](https://arxiv.org/abs/2609.38766)
- DreamBench-SWE: A Multi-Session Memory-Hygiene Benchmark for Software Agents — [link](https://arxiv.org/abs/2608.20664)
- ElasticMem: Latent Memory as a Learnable Resource for LLM Agents — [link](https://huggingface.co/papers/2605.30690)
- Context Language Models — [link](https://huggingface.co/papers/2609.37725)

- [ ] 読む価値があった <!-- jrp:qday:https://shimo4228.github.io/shimo4228/jrp/question/f15c2baf731e8b33a676e725a8b71258:2026-10-01 -->

---

> [!info]- Review — 境界の資料 10 件
> - [ ] [LongEmo: Towards Emotion Understanding and Reasoning in Long Videos](https://arxiv.org/abs/2609.40079) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 確信度不足: 0.48 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/eaaf429e430ae9faf1850e237bab0f36 -->
> - [ ] [EvoAgentBench: Benchmarking Agent Self-Evolution via Ability Transfer](https://arxiv.org/abs/2607.05202) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 境界: 重み付き 0.59 (採用線 0.60) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/0c11c6b6bd47fae3be10dc33d891ae42 -->
> - [ ] [Learning Reliable GUI Agents under Imperfect Priors](https://arxiv.org/abs/2609.39547) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 境界: 重み付き 0.58 (採用線 0.60) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/beaf215cb18c2aa2183e62a896c05aca -->
> - [ ] [APM-Bench: Benchmarking Cross-session Persistent Memory for Egocentric Streaming Video Assistants](https://huggingface.co/papers/2609.37559) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 境界: 重み付き 0.58 (採用線 0.60) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/3d859952ceacfc8c57b0cd102ddda498 -->
> - [ ] [EngramBench: A Capability-Grounded Benchmark for Skill-Evolution Harnesses](https://arxiv.org/abs/2609.39284) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 確信度不足: 0.45 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/ce4dcebd44b0d8d15d60d61f1cd5ed50 -->
> - [ ] [RECON: Benchmarking Agent Memory for Compositional Reasoning over Long Contexts](https://arxiv.org/abs/2607.16716) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 確信度不足: 0.46 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/6784acf1e645fa1e1e2a1885ab6e0451 -->
> - [ ] [CoMemBench: Benchmarking Collaborative Memory Boundaries across Multi-Agent Workflow Topologies](https://arxiv.org/abs/2609.32192) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 境界: 重み付き 0.55 (採用線 0.60) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/23252a2b413fce0692e6b4c3d30a2526 -->
> - [ ] [Locomo-Plus: Beyond-Factual Cognitive Memory Evaluation Framework for LLM Agents](https://huggingface.co/papers/2602.10715) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 境界: 重み付き 0.54 (採用線 0.60) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/ef35b15027ea01c1f4c0dc3e554faf5f -->
> - [ ] [EnSIMem: Entity-Structured Indexing for Long-Term Agent Memory](https://arxiv.org/abs/2609.27279) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 確信度不足: 0.34 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/18ee36829a0ff3873178b1150ce39284 -->
> - [ ] [Autoresearch in Mixed-Integer Linear and Nonlinear Programming](https://arxiv.org/abs/2609.39360) — 「LLM エージェントの記憶の設計は、正答をどれだけ変えるか」: 確信度不足: 0.44 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/4f9a0690b733c0b4bc7b7653133d318b -->

> [!info]- 橋渡し — 3 件
> - Persistent Context Graphs for Efficient Memory Compaction in LLM Agents — [link](https://arxiv.org/abs/2609.40118)
> - ElasticMem: Latent Memory as a Learnable Resource for LLM Agents — [link](https://huggingface.co/papers/2605.30690)
> - Working Around the Compute Ceiling: Byte-Exact Memory in Galahad Makes LLM Reading a One-Time Cost LLM Reading a One-Time Cost — [link](https://arxiv.org/abs/2609.39358)

> [!info]- Claims — 5 件
> - [ ] **memory-designs [1]** (見本では claim の原文を省略。出典を参照) — [source](https://arxiv.org/abs/2609.39765) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/306a1a4b5ac102074153ffb0e2cc7801 -->
> - [ ] **memory-designs [2]** (見本では claim の原文を省略。出典を参照) — [source](https://arxiv.org/abs/2609.38766) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/769c3bcb291a12ec0182d52beefc0103 -->
> - [ ] **memory-designs [3]** (見本では claim の原文を省略。出典を参照) — [source](https://arxiv.org/abs/2608.20664) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/15f3f348fa7d9102d866a007892e46eb -->
> - [ ] **memory-designs [4]** (見本では claim の原文を省略。出典を参照) — [source](https://huggingface.co/papers/2605.30690) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/3aa697bcddbaf5308726e41829421004 -->
> - [ ] **memory-designs [5]** (見本では claim の原文を省略。出典を参照) — [source](https://huggingface.co/papers/2609.37725) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/d10a23f3b9bbf7724e31e4e381877d8d -->

> [!info]- 未判定 — 1 件
> - [novelty] (見本では claim の原文を省略。出典を参照)

> [!info]- 運用
> - Jev 質問数: 2170
> - 生成 token (claude-code:claude-opus-5-5): in 28366 / out 13431
> - claude_calls: 0
> - cost: $0.0434 (生成はサブスクリプション定額で 0 計上)
> - 記入率 (前回): なし
> - open な問い: 1 件
> - rubric grounded: 平均 0.98 / gold 一致 未計測
> - rubric relevant: 平均 0.86 / gold 一致 未計測
> - rubric novel: 平均 0.98 / gold 一致 未計測
> - rubric actionable: 平均 0.77 / gold 一致 未計測
> - net 取得数: firehose 300, keyword 58
> - net 採用率: firehose 0.60, keyword 0.40
> - topic クラスタ数: 0
> - 収束推定 f: データ不足 (3 run 未満)
> - Time-to-Discovery: 未計測
> - openalex credit: 10
> - rule 候補: relevance_triage は adapter=arxiv のとき accept (n=43, 一致率 1.00)
> - rule 候補: relevance_triage は text_len>=100 のとき accept (n=76, 一致率 0.96)
> - rule 候補: relevance_triage は text_len>=300 のとき accept (n=73, 一致率 0.97)
> - rule 候補: relevance_triage は text_len>=1000 のとき accept (n=67, 一致率 1.00)
> - (source, 問い) 対の Jev 失敗: 0 / 358 (0.0%); full screen 73 対
> - 段の所要: queries 0s / fetch 7s / prefilter 1s / triage 3s / screen 6s / claims 7s / novelty 3s / support 0s / canary 0s / sections 135s / rubric 0s
> - harvest: label 0 件 / 取り消し 0 件
> - query: 問いファイルの 3 件を使用
> - firehose: 関連度順に上位 250 件 (529 件を省略)
> - keyword/arxiv: 検証落ちで 2 件 skip
> - 同じタイトルの重複 1 件を 1 件にまとめて判定
> - Review: 13 件のうち境界に近い 10 件を表示
> - 橋渡し: 37 対が閾値を超え、確率上位 3 件を表示
> - memory-designs: claim 107 件のうち 5 件を掲載
> - memory-designs prose 第1稿: 生成 70.9s
> - memory-designs prose 第2稿: 生成 62.8s
