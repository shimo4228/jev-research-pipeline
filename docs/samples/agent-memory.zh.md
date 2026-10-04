---
date: 2026-10-01
category: jrp
kind: report
tags: [jrp, agent-memory]
topic: "Agent memory — 1 个问题"
line: agent-memory
jrp_report: "https://shimo4228.github.io/shimo4228/jrp/report/f37bc927de604c7f9917c890fff29782"
---

<!-- jrp 笔记样例 (JRP_NOTE_LANG=zh)，来自 2026-10-01 对单个方向的一次试运行。第三方文本已省略: claim 原句、出处旁的摘录、未判定的 claim 文本都只保留链接。正文和运行部分是 jrp 自己的输出。 版式已用 2026-10-04 的渲染重新生成 (plan note-layout)。 -->

# Agent memory — 2026-10-01

## 哪些记忆设计能可测地改变 LLM 智能体的正确率?

### 今日变化

今天有两项研究提供了带数字的结果。第一项面向软件智能体：后面的任务要依赖前几轮工作留下的信息。在这种多轮设定的后续一轮审核中，不带外部记忆时只通过了 180 次中的 21 次，带上三种记忆配置后，通过次数为 82 到 97 次。第二项面向个性化对话智能体：在一个长期记忆评测上逐项调整六个设计维度，检索阶段几项调整带来的提升，大于存入阶段把对话按句切分带来的提升。[4][5]

**DreamBench-SWE**

DreamBench-SWE 关心的是写代码的智能体在多次会话之间能否用好记忆。它的难点在于，后面的软件任务需要前几次会话里的证据。这些证据无法从当前任务中推断出来(non-inferable)，不记住就做不对。评分用的是可执行的隐藏检查程序(executable hidden oracles)。也就是说，智能体交出的结果要实际跑过检查，不靠人或模型打分。研究者先跑了一轮原始实验。之后又设计了一轮后续审核，并在查看结果之前把方案冻结下来，这种做法叫预注册(preregistered)。后续这一轮完成了全部 360 个工作单元，比较四种条件，每种条件各有 180 次任务。(S4)

后续这一轮的结果如下。不带外部记忆时，180 次中通过 21 次(通过率 0.1167)。逐字保存事件的确定性记忆通过 82 次(0.4556)，作为参照的一种记忆配置通过 83 次(0.4611)。另一种是托管记忆服务 Mem0 按字面原样存储的一个固定配置，通过 97 次(0.5389)。三种记忆与无记忆的比较，在多重比较校正(Holm correction)之后都显示出差异。Mem0 字面存储和逐字事件记忆之间的比较只是次要分析，不作为确证，结论会随敏感性设定而变。在原始那一轮里，主要的对比没有显示差异(95/180 对 89/180)。作者特别说明，这不能当作两者等效的证据。按作者的说法，这轮审核支持把它当作能区分不同配置的评测，并刻画了一个具体的托管记忆配置。[4] (S4)

**MemMachine**

MemMachine 面向需要长期记忆的个性化 LLM 智能体，这类智能体要记住用户、保持事实前后一致，还要做跨度很长的推理。作者指出，单靠上下文窗口或常规的检索增强生成(RAG，先检索资料再生成回答)时，多次会话之后效果会变差。MemMachine 是一个开源记忆系统，把短期记忆、长期的情景记忆和用户画像记忆整合在一起。它的设计意图是保留原始真相(ground-truth-preserving)：保存整段对话原文，少用会丢信息的 LLM 抽取步骤。检索时，它会把命中的片段连同前后文一起取出。这样设计，是为了应对相关证据跨越多轮对话的情况。(S5)

在评测集 LongMemEvalS(发表于 ICLR 2025)上，作者从六个维度逐项拆解设计的作用，这种做法叫消融实验(ablation)，最终得到 93.0% 的准确率。几项调整的贡献差别明显。调整检索深度，也就是取回多少条记忆，带来 +4.2%。按句切分对话是存入阶段的做法，只带来 +0.8%。上下文的排版方式(+2.0%)、检索提示词设计(+1.8%)和查询偏差校正(+1.4%)也都属于检索阶段。摘录里，这些提升均写作 percent，没有注明是百分点还是相对比例。[5] (S5)

【推论】如果这两项结果在别的设定下也成立，那么值得投入的问题可能会变化：不再只是“要不要加记忆”，而是“记忆存什么、检索阶段怎么调”。软件任务里，有无记忆的差距远大于不同记忆配置之间的差距。对话记忆里，检索深度这类检索端参数的影响，大于存入时的切分方式。下一步该确认三件事。第一，Mem0 字面存储的领先，换到其他固定配置或其他任务时是否还在。第二，检索深度 +4.2% 这类数字，究竟是百分点还是相对提升。第三，换用别的模型或评测集后，各项调整的贡献排序是否不变。以下几种情况会让这个判断落空：后续实验里，记忆配置之间的差异随设定反复翻转；有无记忆的差距，只出现在“后续任务必须依赖前次信息”这种专门构造的评测中；或者检索端的收益，只在某一个模型上才出现。

### 证据

- PathAnchor: Path-Structured Evidence for Scientific Agents — [link](https://arxiv.org/abs/2609.38766)
- VideoLoop: Looped Working Memory Against Semantic Thrashing in Long-Form Video Agents — [link](https://huggingface.co/papers/2609.38119)
- TAGGRAPH: Tag-Augmented Graphs for Graph Retrieval of Agent Persistent Histories — [link](https://arxiv.org/abs/2609.38353)
- DreamBench-SWE: A Multi-Session Memory-Hygiene Benchmark for Software Agents — [link](https://arxiv.org/abs/2608.20664)
- MemMachine: A Ground-Truth-Preserving Memory System for Personalized AI Agents — [link](https://huggingface.co/papers/2604.04853)

- [ ] 值得一读 <!-- jrp:qday:https://shimo4228.github.io/shimo4228/jrp/question/f15c2baf731e8b33a676e725a8b71258:2026-10-01 -->

---

> [!info]- Review — 边界资料 9 条
> - [ ] [APM-Bench: Benchmarking Cross-session Persistent Memory for Egocentric Streaming Video Assistants](https://huggingface.co/papers/2609.37559) — 「哪些记忆设计能可测地改变 LLM 智能体的正确率?」: 置信度不足: 0.31 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/3d859952ceacfc8c57b0cd102ddda498 -->
> - [ ] [CoMemBench: Benchmarking Collaborative Memory Boundaries across Multi-Agent Workflow Topologies](https://arxiv.org/abs/2609.32192) — 「哪些记忆设计能可测地改变 LLM 智能体的正确率?」: 临界: 加权 0.56 (采纳线 0.60) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/23252a2b413fce0692e6b4c3d30a2526 -->
> - [ ] [Learning Reliable GUI Agents under Imperfect Priors](https://arxiv.org/abs/2609.39547) — 「哪些记忆设计能可测地改变 LLM 智能体的正确率?」: 置信度不足: 0.41 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/beaf215cb18c2aa2183e62a896c05aca -->
> - [ ] [LongEmo: Towards Emotion Understanding and Reasoning in Long Videos](https://arxiv.org/abs/2609.40079) — 「哪些记忆设计能可测地改变 LLM 智能体的正确率?」: 置信度不足: 0.47 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/eaaf429e430ae9faf1850e237bab0f36 -->
> - [ ] [VoxMem: Benchmarking Multimodal Memory in Large Audio Language Models](https://huggingface.co/papers/2609.32607) — 「哪些记忆设计能可测地改变 LLM 智能体的正确率?」: 临界: 加权 0.56 (采纳线 0.60) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/471e167467b0fa5187868801f38b85c5 -->
> - [ ] [RECON: Benchmarking Agent Memory for Compositional Reasoning over Long Contexts](https://arxiv.org/abs/2607.16716) — 「哪些记忆设计能可测地改变 LLM 智能体的正确率?」: 临界: 加权 0.56 (采纳线 0.60) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/6784acf1e645fa1e1e2a1885ab6e0451 -->
> - [ ] [Locomo-Plus: Beyond-Factual Cognitive Memory Evaluation Framework for LLM Agents](https://huggingface.co/papers/2602.10715) — 「哪些记忆设计能可测地改变 LLM 智能体的正确率?」: 临界: 加权 0.54 (采纳线 0.60) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/ef35b15027ea01c1f4c0dc3e554faf5f -->
> - [ ] [Autoresearch in Mixed-Integer Linear and Nonlinear Programming](https://arxiv.org/abs/2609.39360) — 「哪些记忆设计能可测地改变 LLM 智能体的正确率?」: 置信度不足: 0.47 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/4f9a0690b733c0b4bc7b7653133d318b -->
> - [ ] [When Context Changes: Understanding Update Failures in LLMs](https://arxiv.org/abs/2609.38866) — 「哪些记忆设计能可测地改变 LLM 智能体的正确率?」: 置信度不足: 0.48 (< 0.50) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/cb5b6c9e10d5e802c9668da6f927d394 -->

> [!info]- 桥接 — 3 条
> - Persistent Context Graphs for Efficient Memory Compaction in LLM Agents — [link](https://arxiv.org/abs/2609.40118)
> - Keep It InMind: Benchmarking the Implicit-Association Blind Spot in Agent Memory — [link](https://arxiv.org/abs/2607.24368)
> - MemLife: Curating and Reasoning over Long-Term Egocentric Video Memories — [link](https://arxiv.org/abs/2609.40195)

> [!info]- Claims — 5 条
> - [ ] **memory-designs [1]** (样例中省略 claim 原文，请见出处) — [source](https://arxiv.org/abs/2609.38766) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/769c3bcb291a12ec0182d52beefc0103 -->
> - [ ] **memory-designs [2]** (样例中省略 claim 原文，请见出处) — [source](https://huggingface.co/papers/2609.38119) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/a824cc071bfde1378bb546f08950616c -->
> - [ ] **memory-designs [3]** (样例中省略 claim 原文，请见出处) — [source](https://arxiv.org/abs/2609.38353) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/f273aacd9af966e46927e27b99523a2b -->
> - [ ] **memory-designs [4]** (样例中省略 claim 原文，请见出处) — [source](https://arxiv.org/abs/2608.20664) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/15f3f348fa7d9102d866a007892e46eb -->
> - [ ] **memory-designs [5]** (样例中省略 claim 原文，请见出处) — [source](https://huggingface.co/papers/2604.04853) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/3ccec6bf1e7bc98aa9a96d9f962c5f27 -->

> [!info]- 未判定 — 1 条
> - [claim_detection] (样例中省略 claim 原文，请见出处)

> [!info]- 运行
> - Jev 问题数: 2263
> - 生成 token (claude-code:claude-opus-5-5): in 27538 / out 11852
> - claude_calls: 0
> - cost: $0.0453 (生成按订阅定额计为 0)
> - 填写率 (上次): 无
> - 开放问题: 1 个
> - rubric grounded: 平均 0.96 / gold 一致率 未测量
> - rubric relevant: 平均 0.84 / gold 一致率 未测量
> - rubric novel: 平均 0.99 / gold 一致率 未测量
> - rubric actionable: 平均 0.73 / gold 一致率 未测量
> - 各 net 获取数: firehose 300, keyword 58
> - 各 net 采纳率: firehose 0.60, keyword 0.40
> - topic 聚类数: 0
> - 收敛估计 f: 数据不足 (少于 3 次 run)
> - Time-to-Discovery: 未测量
> - openalex credit: 10
> - rule 候选: relevance_triage 在 adapter=arxiv 时为 accept (n=44, 一致率 1.00)
> - rule 候选: relevance_triage 在 text_len>=100 时为 accept (n=75, 一致率 0.96)
> - rule 候选: relevance_triage 在 text_len>=300 时为 accept (n=73, 一致率 0.97)
> - rule 候选: relevance_triage 在 text_len>=1000 时为 accept (n=69, 一致率 1.00)
> - (source, 问题) 对的 Jev 失败: 0 / 357 (0.0%); full screen 72 对
> - 无正文: 1 条 (未筛选)
> - 各阶段耗时: queries 0s / fetch 7s / prefilter 1s / triage 3s / screen 5s / claims 8s / novelty 3s / support 0s / canary 0s / sections 128s / rubric 0s
> - harvest: label 0 条 / 撤销 0 条
> - query: 使用问题文件中的 3 条
> - firehose: 按相关度取前 250 条 (省略 529 条)
> - keyword/arxiv: 2 条未通过校验，跳过
> - 1 条同标题重复合并为 1 条判定
> - 桥接: 48 对超过阈值，显示概率最高的 3 条
> - memory-designs: 110 条 claim 中刊载 5 条
> - memory-designs prose 第1稿: 已生成 64.8s
> - memory-designs prose 第2稿: 已生成 62.0s
