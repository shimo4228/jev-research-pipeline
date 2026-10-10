# jrp — jev-research-pipeline

**English** | [日本語](https://github.com/shimo4228/jev-research-pipeline/blob/main/README.ja.md)

**A research note each morning on the questions you follow, at about a tenth of what an LLM agent cost me: a judgment-only model screens the new papers, and an LLM writes only the prose.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/shimo4228/jev-research-pipeline/blob/main/LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://github.com/shimo4228/jev-research-pipeline/blob/main/pyproject.toml)
[![Status: pilot](https://img.shields.io/badge/status-pilot-orange.svg)](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/pilot-log.md)

[A sample note](https://github.com/shimo4228/jev-research-pipeline#what-you-get-each-morning) · [Why jrp](https://github.com/shimo4228/jev-research-pipeline#why-jrp) · [Try it](https://github.com/shimo4228/jev-research-pipeline#try-it) · [Status and limits](https://github.com/shimo4228/jev-research-pipeline#status-and-limits)

<p align="center">
  <img src="https://raw.githubusercontent.com/shimo4228/jev-research-pipeline/main/assets/overview.svg" width="540" alt="A loop of four boxes around a center labelled Your questions: gather new papers and repos every morning; Jev judges whether each one helps answer one of your questions and marks it keep, review or drop; an LLM writes a short section per question; you read the day's note in your Obsidian vault and tick what was worth reading, and a dashed arrow shows the ticks steering tomorrow's run.">
</p>

jrp is a command-line tool for one person keeping up with a research field. You keep two to four
open questions per topic. Every morning jrp takes the next three topics in turn (how many a morning
is a setting), checks new papers and repositories against their questions, and writes one Markdown note per topic into a
folder, usually an Obsidian vault. Plain Python code runs
the loop. Every screening call in it (does this paper help answer this question? which sentence is the
evidence?) goes to Jev, a paid hosted model from TypeSafe that answers fixed-choice questions (yes
or no, or one of a few options) with a probability for each answer and writes no text. An LLM you
choose, on your ChatGPT or Claude subscription or on Qwen, writes the explanation and checks its own
draft once; Jev then scores the finished section. Notes come in English, Chinese or Japanese.

## What you get each morning

An excerpt from a sample note, written in English by Claude Opus (the default writer is GPT-6 Luna, OpenAI's model on a ChatGPT plan):

> **Which memory designs measurably change what an LLM agent gets right?**
>
> Today's work finds that, in a test where software agents must reuse facts from earlier work
> sessions, giving the agent any of three external memory designs raised its pass count from 21 of
> 180 tasks without memory to between 82 and 97 of 180, under one fixed setup. Separately, a
> conversational memory system reports that tuning how memories are retrieved added more accuracy on
> a long-conversation test than tuning how they are stored. [1][2]
>
> *(two short paragraphs per study follow, with its setup and numbers)*
>
> [Inference] Taken together, these results suggest that the largest measured gap is between having
> memory and having none. Among memory designs, the differences are smaller and harder to confirm. …
>
> **Evidence:** DreamBench-SWE (arXiv) · MemMachine (Hugging Face papers) · 3 more\
> ☐ Worth reading

Each `[n]` points to a sentence copied word for word from its source, never a paraphrase, so every
citation can be checked. You tick what was worth reading (type `[-]` instead for one that was not).
The ticks seed the next run's recommendations, papers related to the ones you ticked. They also become
the labels from which `jrp fit` proposes new thresholds, the cut-offs on Jev's probabilities that sort
papers into keep, review and drop; `jrp fit` only proposes and never applies them
([how-it-works](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/how-it-works.md#status)). Read whole notes and
judge the prose yourself:
[English](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/samples/agent-memory.en.md) ·
[Chinese](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/samples/agent-memory.zh.md) ·
[Japanese](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/samples/agent-memory.ja.md)
(third-party sentences are replaced by links; the prose is jrp's own output).

## Why jrp

I built jrp to replace my previous setup, an Opus agent with web search that ran the whole loop.

| | Opus agent | jrp |
|---|---|---|
| measured | 2026-09-15 to 09-22 | 2026-10-03 to 10-07 |
| decides what to read | the agent, over 107 to 242 model turns a morning | Jev, one fixed-choice question at a time; code runs the loop |
| writes | the agent | an LLM, one short section per question with new evidence |
| cost a morning, 3 or 4 topics | $8 to $15 | $1.1 to $1.5 (my writer, Opus 5.5 on a Claude subscription, priced at API rates, plus $0.03 to $0.17 of Jev) |

The table compares cost, not quality. The two wrote different notes, so the samples above are there
for you to judge.

- **Cheap because there are no turns.** An agent re-reads its growing context on every turn. jrp
  asks Jev a few thousand small questions, each a fraction of a cent, and calls the writer about
  twice per section. On a ChatGPT or Claude subscription, the writer's share comes out of your plan.
- **No model chooses the searches.** The old agent, left to pick its own searches, put 88 of the 238 topics it chose in
  its first three months (37%) on one theme ([how-it-works](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/how-it-works.md#why-judgment-not-generation)).
  In jrp no model writes a search query at run time: code fixes which sources are searched and how
  often, and every note counts how many distinct subject areas its kept papers cover, so any drift
  that remains shows up as a falling number.

Why a judgment model is enough here: deciding whether a paper bears on a question is a call you can
read off its abstract. On calls of that kind, an independent study from Carnegie Mellon
([arXiv 2609.26550](https://arxiv.org/abs/2609.26550)) found Jev's accuracy, scored against blinded human
adjudication, within three percentage points of a state-of-the-art LLM judge at 0.36% of its price; the gap widens where a derivation has to be
checked. jrp does not trust every call either: when Jev is unsure, the paper goes to the note's
Review list for you to decide.

## Try it

You need Python 3.12, [uv](https://docs.astral.sh/uv/), and two accounts:

- **A TypeSafe API key for Jev** ([docs.typesafe.ai](https://docs.typesafe.ai)). It is paid, with no
  free tier published. TypeSafe bills $42 per billion input tokens (as of 2026-10-07), roughly
  $0.00002 a question: $0.03 to $0.17 a morning in my runs, or $1 to $5 a month. If you already pay
  for ChatGPT or Claude, Jev is the only new bill. Jev is not swappable: every screening call in the loop
  is a Jev question, and none of the four local models I tried could reproduce its decisions
  ([article](https://dev.to/shimo4228/what-does-it-take-to-reproduce-jevs-decisions-locally-3i0n)).
- **One writer**, set with `JRP_PROSE_MODEL`:
  - ChatGPT subscription (default), `openai-codex:gpt-6-luna`: a ChatGPT plan that includes Codex.
  - Claude subscription, `claude-code:claude-opus-5-5`: the Claude Code CLI, signed in
    (`claude auth login`).
  - Qwen, pay per token, `dashscope:qwen3.7-max`: `DASHSCOPE_API_KEY` (Alibaba Cloud Model Studio).

**What leaves your machine:** your questions' search queries go to arXiv (through OpenAlex), Hugging Face, GitHub and, if you set `TAVILY_API_KEY`, Tavily; the IDs of papers you ticked and papers Jev kept go to Semantic Scholar's recommender (with the papers you marked `[-]` as negatives, or random papers when there are none yet) and to OpenAlex to find papers citing them; the papers and passages Jev judges go to TypeSafe; and each section's evidence goes to the writer you picked. Notes stay in your folder; the optional Slack notification carries note names, claim counts, failure reasons and the path of any question file with no open question, not the notes' content.

Then install it and write the starter config. To try it without installing, put `uvx` in front of
the `jrp init`, `jrp doctor` and `jrp try` commands below instead; scheduling needs the installed copy.

```bash
uv tool install jrp
jrp init --lang en              # writes ~/.config/jrp/{env, config.toml, questions/agent-memory.md}
```

Open `~/.config/jrp/env`, fill in `JRP_VAULT_DIR` (where notes go) and `TYPESAFE_API_KEY`, and pick a
writer with `JRP_PROSE_MODEL` (for the default writer, run `jrp codex login` once). Then check the setup and get a first note:

```bash
set -a; source ~/.config/jrp/env; set +a
jrp doctor                      # every check a run needs, without running one
jrp try --line agent-memory     # one run of the starter topic into a throwaway folder; prints the note's path
```

`jrp try` writes nothing to your vault. To run every morning on macOS, `jrp schedule install --hour 5`
 writes a launchd job (the macOS scheduler) and prints how to load it. Cron and systemd on Linux, and Slack or desktop
notifications, are in
[docs/scheduling.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/scheduling.md);
every setting is in
[docs/configuration.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/configuration.md).

## Your questions steer it

The questions set what a run can find, so they are what you write. A topic (the CLI calls it a
line, config.toml a track) is a two-line `[tracks.<topic>]` entry in `~/.config/jrp/config.toml`,
and its questions are short blocks in `~/.config/jrp/questions/<topic>.md`; what goes in a block is
in [the question file](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/how-it-works.md#the-question-file).
`jrp questions new --line <topic>` opens a Claude Code session that walks you through writing them.
A run never edits either file.

## Status and limits

- **A pilot.** I have run it every morning since 2026-09-24 on seven topics of my own. It runs on
  macOS (launchd) or Linux (cron or systemd).
- **One vendor at the core.** If TypeSafe raises Jev's price, your cost rises with it; if TypeSafe
  shuts Jev down, jrp stops, because there is no fallback judge.
- **Thresholds are hand-tuned.** Jev's routing thresholds have not been refit on ticks yet, so expect
  borderline papers in each note's Review list.
- **English and Chinese notes have no human reader yet.** I read Japanese only. The English and
  Chinese prompts were accepted on automated measurements of Claude Opus drafts alone (on the offline prose bench, an Opus judge that
  checks each draft against its sources passed 28 of 32 English drafts and 32 of 32 Chinese ones);
  the default writer, GPT-6 Luna, has not been measured in either language. If you read a sample, tell me where it reads badly:
  [open a reading-feedback issue](https://github.com/shimo4228/jev-research-pipeline/issues/new?template=reading-feedback.yml)
  (any language; quote short passages only).

> 中文读者：中文正文只经过自动测量就被采用，我不读中文。请读一读[中文样例](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/samples/agent-memory.zh.md)，
> 告诉我哪里读不顺、哪里让人误解：[提交阅读反馈](https://github.com/shimo4228/jev-research-pipeline/issues/new?template=reading-feedback.yml)（可用中文）。

## Learn more

- [How jrp works](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/how-it-works.md):
  a morning run step by step, what a note contains, the question file, where sources come from, how
  the prose is written and checked, the cost in detail, and why jrp asks a judgment model instead of
  an agent.
- [Design record](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/design/pipeline-design.md):
  every decision and the evidence behind it.
- Built on [TypeSafe Jev](https://docs.typesafe.ai) through
  [Pydantic AI's `typesafe:` model](https://pydantic.dev/docs/ai/models/typesafe/); the writers use
  [Pydantic AI's OpenAI Codex provider](https://github.com/pydantic/pydantic-ai/blob/main/docs/models/openai-codex.md),
  [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or
  [Qwen on DashScope](https://www.alibabacloud.com/help/en/model-studio/models).

## More from the author

Each of my experiments with Jev is an article, in English on Dev.to and in Japanese on Zenn:

- **[Moving My Research Pipeline's Judgment Calls from an LLM to Jev, a Judgment-Only Model](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj)** ([日本語](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)): the story of jrp itself: which of the Opus agent's judgments moved to Jev, and why the writing stays with an LLM.
- **[How Close to Opus Does Jev, a Model That Writes No Text, Get at Skill Selection in 0.3 Seconds?](https://dev.to/shimo4228/how-close-to-opus-does-jev-a-model-that-writes-no-text-get-at-skill-selection-in-03-seconds-1nfj)** ([日本語](https://zenn.dev/shimo4228/articles/jev-vs-opus-skill-selection)): on 150 situations, Jev agrees with Opus about half as often as Opus agrees with itself, at about 1/560th of the cost.
- **[What Does It Take to Reproduce Jev's Decisions Locally?](https://dev.to/shimo4228/what-does-it-take-to-reproduce-jevs-decisions-locally-3i0n)** ([日本語](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)): four local models replay the same 150 choices, and each fails for a different reason.
- **[I Added Jev's Skill Router to Claude Code and Turned Back Just Before Rewriting the Skill Listing](https://dev.to/shimo4228/i-added-jevs-skill-router-to-claude-code-and-turned-back-just-before-rewriting-the-skill-listing-34in)** ([日本語](https://zenn.dev/shimo4228/articles/jev-retrofit-limits)): a hook that asks Jev which skill fits each prompt, and why it is unlikely to help a strong model.

Related repositories:

- **[jev-skill-router](https://github.com/shimo4228/jev-skill-router)**: a Claude Code hook that asked TypeSafe Jev which installed skill fits each prompt and logged the answer; run for a week, then removed, and kept as a reference implementation. Read it beside jrp to see why Jev's effect could not be read inside an agent loop but can be in a fixed pipeline.
- **[daily-research](https://github.com/shimo4228/daily-research)**: a research feedback engine for your own repos: each morning `claude -p` runs inside the repo of one of my research projects, picked in rotation, and writes an explanatory note to an Obsidian vault. It is the Opus-agent setup that the table in [Why jrp](https://github.com/shimo4228/jev-research-pipeline#why-jrp) compares against.
- **[shimo4228 (hub)](https://github.com/shimo4228/shimo4228)**: my hub, with the long-running research projects and their DOIs (among them the topics this pipeline watches, such as Agent Knowledge Cycle and Authorship Strategy) and the tools for Claude Code and TypeSafe Jev.

All articles are on [Dev.to](https://dev.to/shimo4228) (English) and [Zenn](https://zenn.dev/shimo4228) (Japanese).

## License

MIT; see [LICENSE](https://github.com/shimo4228/jev-research-pipeline/blob/main/LICENSE).

<details>
<summary>For tools and AI assistants</summary>

jrp (jev-research-pipeline) is a command-line research monitor for one person keeping up with a research field: every morning it checks new papers and repositories against the open questions you wrote and writes one Markdown note per topic, usually into an Obsidian vault.

It exists because the author's previous setup, an Opus agent with web search that ran the whole loop in [daily-research](https://github.com/shimo4228/daily-research), cost $8 to $15 a morning over 107 to 242 model turns and drifted onto one theme (88 of the 238 topics it chose in its first three months). In jrp, plain Python owns the loop and fixes which sources are searched; every screening call (does this paper help answer this question? which sentence is the evidence?) goes to TypeSafe's Jev, a hosted model that answers fixed-choice questions with probabilities and writes no text; and an LLM writes the prose and checks its own draft once, after which Jev scores the section on a rubric.

Canonical facts. License: MIT. Language: Python 3.12, installed with uv (`uv tool install jrp`; the package is `jrp` on PyPI). Status: a pilot, maintained by hand in this repository and run by the author every morning since 2026-09-24 on seven of the author's own topics; macOS (launchd) or Linux (cron or systemd). Paid keys: a TypeSafe API key for Jev is required (paid, no free tier published; $42 per billion input tokens as of 2026-10-07, $0.03 to $0.17 a morning in the author's runs), and Jev cannot be swapped out. The writer is one of a ChatGPT plan that includes Codex (`openai-codex:gpt-6-luna`, the default), a Claude subscription through the Claude Code CLI (`claude-code:claude-opus-5-5`), or Qwen on DashScope, paid per token (`dashscope:qwen3.7-max`). Notes come in English, Chinese or Japanese; only the Japanese prompt has had a human reader (the author's own blind reading). Data that leaves the machine: each question's search queries go to arXiv (through OpenAlex), Hugging Face papers, GitHub and, with a key, Tavily; the IDs of ticked and kept papers go to Semantic Scholar's recommendation API (with papers marked `[-]` as negatives, or random papers when none are marked) and to OpenAlex for citing papers; the text Jev judges goes to TypeSafe; and the evidence for each section goes to the chosen writer. Optional Slack notifications carry each note's name and claim count, the reasons a run was degraded (a draft or a source that failed, for example) or a topic failed, and the path of any question file with no open question, not the claims themselves.

Example: `jrp init --lang en` writes `~/.config/jrp/{env, config.toml, questions/agent-memory.md}`; after filling `JRP_VAULT_DIR`, `TYPESAFE_API_KEY` and `JRP_PROSE_MODEL` in the env file, `jrp doctor` checks the setup without running, and `jrp try --line agent-memory` runs that topic once into a throwaway folder and prints the note's path. A note has one short section per question with new evidence; each `[n]` cites a sentence copied word for word from its source, uncertain papers go to a Review list, and a "Worth reading" checkbox per section feeds the next run. Measured cost: $1.1 to $1.5 a morning for 3 or 4 topics (2026-10-03 to 10-07, Opus 5.5 as the writer priced at API rates, plus Jev), against $8 to $15 for the Opus agent it replaced.

Pointers: [docs/how-it-works.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/how-it-works.md) (a run step by step, costs, the question file), [docs/design/pipeline-design.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/design/pipeline-design.md) (every decision and its evidence), [docs/configuration.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/configuration.md) and [docs/scheduling.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/scheduling.md), [docs/pilot-log.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/pilot-log.md), the sample notes in [docs/samples/](https://github.com/shimo4228/jev-research-pipeline/tree/main/docs/samples), and the author's hub, [shimo4228/shimo4228](https://github.com/shimo4228/shimo4228).

</details>
