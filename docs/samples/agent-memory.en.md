---
date: 2026-10-01
category: jrp
kind: report
tags: [jrp, agent-memory]
topic: "Agent memory — 1 questions"
line: agent-memory
jrp_report: "https://shimo4228.github.io/shimo4228/jrp/report/f37bc927de604c7f9917c890fff29782"
---

<!-- A sample jrp note (JRP_NOTE_LANG=en), from a one-line test run on 2026-10-01. Third-party text is left out: each claim's own sentence, the excerpts beside sources, and unjudged claim texts are replaced by their links. The prose and the operations section are jrp's own output. -->

> Where does this read badly or mislead? [Open a reading-feedback issue](https://github.com/shimo4228/jev-research-pipeline/issues/new?template=reading-feedback.yml).

# Agent memory — 2026-10-01

### Which memory designs measurably change what an LLM agent gets right?

What changed today

Today's work finds that, in a test where software agents must reuse facts from earlier work sessions, giving the agent any of three external memory designs raised its pass count from 21 of 180 tasks without memory to between 82 and 97 of 180, under one fixed setup. Separately, a conversational memory system reports that tuning how memories are retrieved added more accuracy on a long-conversation test than tuning how they are stored. [1][2]

**DreamBench-SWE**

DreamBench-SWE targets software agents working across several sessions. Later coding tasks depend on evidence from earlier sessions that the agent cannot infer. Hidden test programs check whether the code actually works. The authors call the quality they are testing "memory hygiene." The excerpt describes it only through this setup. The authors first ran a scaled version of the benchmark. In that run, their primary comparison showed no difference, at 95/180 versus 89/180 passes. The authors stress that this does not prove the two conditions are equal. They then designed a successor audit and preregistered it, meaning they fixed the analysis plan before looking at any outcomes. That run completed all 360 planned work units across four conditions. (S1)

In the successor audit, the agent with no external memory passed 21/180 tasks. It passed 82/180 with a memory that stores past events word for word, and 83/180 with a reference memory that keeps both typed (structured) records and raw text. It passed 97/180 with one specific setup of Mem0, a hosted memory service, configured to store text literally. All three memory designs beat no memory after a statistical correction for running several comparisons at once. The comparison of the Mem0 setup with word-for-word storage did not count as confirmatory, and its result depended on analysis choices. The comparison with the reference memory showed no clear difference. The two planned tests of why memory helps could not be run, because those conditions failed a conformance check before evaluation. The authors say the result characterizes one exact hosted configuration. [1] (S1)

**MemMachine**

Standard approaches can lose information over many sessions with a user. These approaches either keep everything in the model's context window or use retrieval-augmented generation (RAG), which fetches stored snippets into the prompt. MemMachine is an open-source memory system for personalized LLM agents. It stores whole conversation episodes and reduces reliance on an LLM to extract facts, an extraction step the authors describe as lossy. When it finds a matching passage, it also pulls in the surrounding turns. The aim is to catch evidence that spans several turns of dialogue. (S2)

The authors tested MemMachine on LongMemEvalS. They ran an ablation across six design dimensions, meaning they turned individual choices on and off to see how much each one mattered. The best configuration reached 93.0 percent accuracy. Changes to the retrieval stage contributed more than changes to storage. Tuning how many results to retrieve added 4.2 percent, while splitting stored text into sentences added 0.8 percent. Better context formatting (+2.0 percent), search prompt design (+1.8 percent) and query bias correction (+1.4 percent) also beat the storage-side gain. Under matched conditions, MemMachine used roughly 80 percent fewer input tokens than Mem0. [2] (S2)

[Inference] Taken together, these results suggest that the largest measured gap is between having memory and having none. Among memory designs, the differences are smaller and harder to confirm. In DreamBench-SWE, the designs sat at 82 to 97 passes out of 180, and the head-to-head comparisons did not hold up firmly. If that pattern holds, then retrieval choices such as how much to fetch and how to format it may matter more for accuracy than the storage format itself. That would match MemMachine's ablation. Note, however, that MemMachine measured its own system on a conversational test, not software tasks. The next check is to run retrieval-depth and formatting variations inside a benchmark like DreamBench-SWE, using preregistered contrasts. This reading would be wrong if well-powered head-to-head tests showed that storage design alone (word-for-word versus extracted or typed records) reliably separates designs, or if MemMachine's retrieval gains vanished outside its own pipeline.

Evidence

- DreamBench-SWE: A Multi-Session Memory-Hygiene Benchmark for Software Agents — [link](https://arxiv.org/abs/2608.20664)
- MemMachine: A Ground-Truth-Preserving Memory System for Personalized AI Agents — [link](https://huggingface.co/papers/2604.04853)
- ElasticMem: Latent Memory as a Learnable Resource for LLM Agents — [link](https://huggingface.co/papers/2605.30690)
- Context Language Models — [link](https://huggingface.co/papers/2609.37725)
- VideoLoop: Looped Working Memory Against Semantic Thrashing in Long-Form Video Agents — [link](https://huggingface.co/papers/2609.38119)

- [ ] Worth reading <!-- jrp:qday:https://shimo4228.github.io/shimo4228/jrp/question/f15c2baf731e8b33a676e725a8b71258:2026-10-01 -->

## Review

- [ ] APM-Bench: Benchmarking Cross-session Persistent Memory for Egocentric Streaming Video Assistants — "Which memory designs measurably change what an LLM agent gets right?": borderline: weighted 0.58 (cut 0.60) — [link](https://huggingface.co/papers/2609.37559) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/3d859952ceacfc8c57b0cd102ddda498 -->
- [ ] EnSIMem: Entity-Structured Indexing for Long-Term Agent Memory — "Which memory designs measurably change what an LLM agent gets right?": low certainty: 0.36 (< 0.50) — [link](https://arxiv.org/abs/2609.27279) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/18ee36829a0ff3873178b1150ce39284 -->
- [ ] Locomo-Plus: Beyond-Factual Cognitive Memory Evaluation Framework for LLM Agents — "Which memory designs measurably change what an LLM agent gets right?": borderline: weighted 0.52 (cut 0.60) — [link](https://huggingface.co/papers/2602.10715) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/ef35b15027ea01c1f4c0dc3e554faf5f -->
- [ ] HiMem: Hierarchical Long-Term Memory for LLM Long-Horizon Agents — "Which memory designs measurably change what an LLM agent gets right?": low certainty: 0.42 (< 0.50) — [link](https://huggingface.co/papers/2601.06377) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/e181ed34c211505eb2ecb3db658eb156 -->
- [ ] AtomMem: Building Simple and Effective Memory System for LLM Agents via Atomic Facts — "Which memory designs measurably change what an LLM agent gets right?": low certainty: 0.33 (< 0.50) — [link](https://huggingface.co/papers/2606.19847) <!-- jrp:source:https://shimo4228.github.io/shimo4228/jrp/source/556763cf1ef68e4801dec1e20ec3cb7c -->

## Bridges

- Keep It InMind: Benchmarking the Implicit-Association Blind Spot in Agent Memory — [link](https://arxiv.org/abs/2607.24368)
- Persistent Context Graphs for Efficient Memory Compaction in LLM Agents — [link](https://arxiv.org/abs/2609.40118)
- Working Around the Compute Ceiling: Byte-Exact Memory in Galahad Makes LLM Reading a One-Time Cost LLM Reading a One-Time Cost — [link](https://arxiv.org/abs/2609.39358)

> [!note]- Claims

> - [ ] **memory-designs [1]** (the claim's own sentence is left out of this sample; see the source) — [source](https://arxiv.org/abs/2608.20664) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/15f3f348fa7d9102d866a007892e46eb -->
> - [ ] **memory-designs [2]** (the claim's own sentence is left out of this sample; see the source) — [source](https://huggingface.co/papers/2604.04853) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/3ccec6bf1e7bc98aa9a96d9f962c5f27 -->
> - [ ] **memory-designs [3]** (the claim's own sentence is left out of this sample; see the source) — [source](https://huggingface.co/papers/2605.30690) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/3aa697bcddbaf5308726e41829421004 -->
> - [ ] **memory-designs [4]** (the claim's own sentence is left out of this sample; see the source) — [source](https://huggingface.co/papers/2609.37725) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/d10a23f3b9bbf7724e31e4e381877d8d -->
> - [ ] **memory-designs [5]** (the claim's own sentence is left out of this sample; see the source) — [source](https://huggingface.co/papers/2609.38119) <!-- jrp:claim:https://shimo4228.github.io/shimo4228/jrp/claim/a824cc071bfde1378bb546f08950616c -->

## Unjudged

- [question_screening] PathAnchor: Path-Structured Evidence for Scientific Agents
- [claim_detection] (the claim's own sentence is left out of this sample; see the source)
- [novelty] (the claim's own sentence is left out of this sample; see the source)

## Operations

- Jev questions: 1929
- Generation tokens (claude-code:claude-opus-5-5): in 13556 / out 5002
- claude_calls: 0
- cost: $0.0386 (generation is on a flat subscription, counted as 0)
- Fill rate (previous run): none
- Open questions: 1
- rubric grounded: mean 0.97 / gold agreement not measured
- rubric relevant: mean 0.93 / gold agreement not measured
- rubric novel: mean 0.99 / gold agreement not measured
- rubric actionable: mean 0.77 / gold agreement not measured
- Sources per net: firehose 300, keyword 58
- Accept share per net: firehose 0.40, keyword 0.60
- Topic clusters: 0
- Convergence estimate f: not enough data (under 3 runs)
- Time-to-Discovery: not measured
- openalex credit: 10
- rule candidate: relevance_triage is accept when text_len>=100 (n=65, agreement 1.00)
- rule candidate: relevance_triage is accept when text_len>=300 (n=65, agreement 1.00)
- rule candidate: relevance_triage is accept when text_len>=1000 (n=63, agreement 1.00)
- Jev failures on (source, question) pairs: 1 / 357 (0.3%); full screen 65 pairs
- No text: 1 (not screened)
- Stage times: queries 0s / fetch 8s / prefilter 2s / triage 3s / screen 5s / claims 6s / novelty 2s / support 0s / canary 0s / sections 51s / rubric 0s
- harvest: 0 labels / 0 withdrawn
- query: 3 from the question file
- firehose: the 250 most relevant (529 left out)
- keyword/arxiv: 2 skipped (failed validation)
- 1 same-title duplicates judged as one
- Bridges: 40 pairs over the bar, the 3 likeliest shown
- memory-designs: 5 of 78 claims shown
- memory-designs prose draft 1: written 50.2s
