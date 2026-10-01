# jrp — jev-research-pipeline

**English** | [日本語](https://github.com/shimo4228/jev-research-pipeline/blob/main/README.ja.md)

**A research note each morning for the topics you follow: your questions steer the search, Jev (a judgment-only model) decides what counts, an LLM you choose explains it, in English, Chinese or Japanese.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/shimo4228/jev-research-pipeline/blob/main/LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://github.com/shimo4228/jev-research-pipeline/blob/main/pyproject.toml)
[![Status: pilot](https://img.shields.io/badge/status-pilot-orange.svg)](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/pilot-log.md)

<p align="center">
  <img src="https://raw.githubusercontent.com/shimo4228/jev-research-pipeline/main/assets/overview.svg" width="760" alt="A loop of four boxes around a center labelled Your questions: gather new papers and repos every morning; Jev judges whether each one helps answer one of your questions and marks it keep, review or drop; an LLM writes a short section per question; you read the day's note in your Obsidian vault and tick what was worth reading, and a dashed arrow shows the ticks steering tomorrow's run.">
</p>

jrp is a command-line pipeline for one person keeping up with research. For each topic (a *line*) you
keep two to four open questions. Every morning jrp takes the next lines in turn (three a morning by
default), checks new papers and repositories against their questions, and writes one Markdown note
per line into a folder, usually an Obsidian vault, with a section for each question that moved. Plain Python code runs the loop the same way every time. Jev,
a judgment model from the API company TypeSafe, never writes text: it answers questions with a fixed
set of answers (yes or no, a score, one pick from a list) with probabilities, and here it decides
whether each source helps answer a question. A general-purpose LLM writes only the explanation. You
close the loop by ticking checkboxes in the note, and the ticks steer the next run.

It is a pilot that I have run every morning since 2026-09-24. It is MIT licensed, needs Python 3.12,
and runs on macOS (scheduled with launchd) or Linux (cron or systemd).

## What you need

Besides Python 3.12 and [uv](https://docs.astral.sh/uv/), two accounts cannot be avoided:

- **A paid TypeSafe API key** for Jev ([docs.typesafe.ai](https://docs.typesafe.ai)). Jev is the design:
  every judgment in the loop is a Jev question.
- **One writer** for the prose, any of:

| writer | `JRP_PROSE_MODEL` | what it needs |
|---|---|---|
| ChatGPT subscription (default) | `openai-codex:gpt-6-luna` | a ChatGPT plan that includes Codex; `jrp codex login` once |
| Claude subscription | `claude-code:claude-opus-5-5` | the Claude Code CLI, signed in (`claude auth login`) |
| Qwen, pay per token | `dashscope:qwen3.7-max` | `DASHSCOPE_API_KEY` (Alibaba Cloud Model Studio) |

Everything else is optional: source-API keys raise free quotas, and `TAVILY_API_KEY` adds web search.

## Quick start

```bash
uv tool install jrp
jrp init --lang en              # writes ~/.config/jrp/{env, config.toml, questions/agent-memory.md}
```

Open `~/.config/jrp/env` and fill in `JRP_VAULT_DIR` (where notes go) and `TYPESAFE_API_KEY`, and pick
a writer with `JRP_PROSE_MODEL`. Then check the setup and see a note the same hour:

```bash
set -a; source ~/.config/jrp/env; set +a
jrp doctor                      # every check a run needs, without running one
jrp try --line agent-memory     # one run into a throwaway folder; prints the note's path
```

`jrp init` leaves any file that already exists alone, and `jrp try` writes neither to your vault nor to
the store (jrp's own record of past sources and judgments, one JSON-LD file per line). To run it every
morning:

```bash
jrp schedule install --hour 5   # macOS: writes a launchd job and prints how to load it
```

On Linux, [docs/scheduling.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/scheduling.md) has cron and systemd examples. Notifications go
to a Slack webhook, macOS Notification Center, or both (same page). Every variable and the full
`config.toml` are in [docs/configuration.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/configuration.md). To try it without
installing, put `uvx` in front of each `jrp` command (`uvx jrp init --lang en`).

## Sample notes

The same line and question, run on the same morning in each language with Claude Opus as the writer:
[English](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/samples/agent-memory.en.md) · [Chinese](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/samples/agent-memory.zh.md) ·
[Japanese](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/samples/agent-memory.ja.md). Third-party text is left out of the samples: each claim
(a sentence jrp quotes from a source) and the excerpts beside sources are replaced by links. The prose
and the operations section (the note's last block: questions asked, cost, what each search returned)
are jrp's own output.

## What it costs

Measured on my machine from the notes' own operations sections, 2026-09-24 to 2026-10-01.

| | per line-run (3 open questions) | per morning (4 lines) |
|---|---|---|
| Jev questions | 200 to 2,600 | 2,470 to 8,191 |
| Jev cost at $0.00002 a question | $0.004 to $0.05 | $0.05 to $0.16 |
| prose sections written | 0 to 3 (one per question that moved) | 5 to 8 |

A section costs the writer one draft and one self-check, about 8,000 to 12,000 input and 1,500 to
4,000 output tokens on `openai-codex:gpt-6-luna`, and about 11,000 input and 5,000 output tokens on
`claude-code:claude-opus-5-5`; a rejected draft is written once more. On a subscription writer
these count against the plan's usage, not in dollars; on DashScope multiply by the model's token
price. The $0.00002 is the Jev price set in my env for the cost line: check TypeSafe's
current pricing. Searching costs nothing without keys; OpenAlex's free daily budget is shared by
all lines.

## Questions are the unit

One file per line at `~/.config/jrp/questions/<slug>.md` (or wherever `JRP_QUESTIONS_DIR` points).
The questions set the ceiling on what a run can find, so they get their own procedure: ask the theme,
draft two to four questions nobody has settled yet, name what each one is *not* about, search this
week's vocabulary, write the search queries per source, try them, and name a few papers each question
must always keep. The procedure is the Claude Code skill
[`jrp-question`](https://github.com/shimo4228/jev-research-pipeline/blob/main/.claude/skills/jrp-question/SKILL.md), and `jrp questions new --line <slug>` opens a
Claude Code session that walks you through it. An example block:

```markdown
<!-- jrp:questions:agent-memory -->

## Which memory designs measurably change what an LLM agent gets right?
- slug: memory-designs
- version: 1
- status: open
- opened: 2026-10-01
- retire: close it when three months bring no new evidence
- brief: Which design choices move downstream accuracy, and by how much, on public benchmarks.
- method: benchmark comparisons with the answering model held fixed
- evidence: measured results; a claim without a number is not enough
- not: prompt techniques in general
- canary: https://arxiv.org/abs/2608.20664
- arxiv: agent memory benchmark
- github: agent memory
- hf: long-term memory for LLM agents
```

`slug` and `version` identify the question: change the wording, bump the version. `brief`, `method`
and `evidence` go into what Jev sees for every (source, question) pair; `not:` lines give Jev's
yes/no checks the neighbouring topics that would otherwise pass every day. `canary:` names a paper or
repo the question must always keep: if no search brings it in, it is fetched and screened anyway, and a
dropped canary shows up in the note as a sign that screening drifted. The `arxiv:`, `github:`, `hf:`
and `web:` lines are this question's search queries, sent as written; `jrp queries check --line
<slug>` sends each one once and prints the first hits, storing nothing. A run never edits this file.

## Languages

`JRP_NOTE_LANG` (`en`, `zh` or `ja`) sets the note's language: the headings, the operations section and
the prose, whose prompt and checks were written for each language rather than translated. The
machine-read parts of a note are the same in every language, so ticks work alike.

I read Japanese only. The Japanese prompt was chosen by my own blind reading. The English and
Chinese prompts were accepted on the prose bench's measurements alone (the bench redrafts the
sections of past days with each candidate prompt and has them judged): over the same 32 past
question-days (one question on one day), drafts written by Claude Opus passed a fidelity judge
(another Opus, checking each draft against its sources) 28 of 32 times in English and 32 of 32 in
Chinese (Japanese: 28 of 32), and a simulated reader that saw only the draft took away at least as
much of each study as from the Japanese one. The default writer, GPT-6 Luna, has not been measured
in English or Chinese. No English or Chinese reader has read them yet, so a reader's word on
where they read badly is the most useful feedback this project can get: read a
[sample](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/samples/agent-memory.zh.md) or a note of your own and
[open a reading-feedback issue](https://github.com/shimo4228/jev-research-pipeline/issues/new?template=reading-feedback.yml) (any language; quote short passages only).

> 中文读者：中文正文只经过自动测量就被采用，作者不读中文。请读一读[中文样例](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/samples/agent-memory.zh.md)，
> 告诉我们哪里读不顺、哪里让人误解：[提交阅读反馈](https://github.com/shimo4228/jev-research-pipeline/issues/new?template=reading-feedback.yml)（可用中文）。

The record
is in [docs/design/pipeline-design.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/design/pipeline-design.md) ("Prose in English", "Prose in
Chinese").

## How a morning run works

Each morning:

1. Harvest your ticks from the line's earlier notes.
2. Pick the next three lines in rotation, plus any line marked daily.
3. For each open question, fetch candidates from five fixed discovery channels, the
   [source nets](#source-nets).
4. Jev screens each (source, question) pair: a cheap on-topic check first, then hard gates as yes/no
   questions and weighted scores. Code applies the thresholds and routes the pair to Keep, Review
   (borderline), Drop, Incomplete (the source had no abstract to judge) or Unjudged (the Jev request
   failed).
5. Kept sources are cut into verbatim sentences, and Jev picks out the sentences that advance or
   contradict the question. A claim is a sentence, never a paraphrase, so citations always resolve.
6. The writing model (GPT-6 Luna by default) writes one short section per question that got new
   evidence today, from those claims and short excerpts of their sources, with one paragraph marked
   as inference. It checks its own draft once. Jev then scores the section on a rubric (readable,
   coherent, nothing the claims and excerpts do not support); a failing draft is rewritten once,
   then the section falls back to a list of its sources.
7. The note is written to the vault with an operations block: Jev question count, tokens, cost,
   per-net acceptance, and canary results (whether the papers a question must always keep were kept).

Your ticks are the labels. They seed the recommendation net (papers related to the ones you ticked),
feed the threshold proposals that `jrp fit` writes for you to apply, and become evaluation cases.
Every Jev call goes through Pydantic AI's native `typesafe:` model, so each judgment is a Pydantic
output type and the raw probability distributions are stored with the decision.

## What a note looks like

```
# <line> — <date>
### <question>                 one section per question that got new evidence today
What changed today             prose; [n] cites a claim; the last paragraph, marked [Inference], is inference
Evidence                       today's sources for this question
Counter-evidence               claims that count against the answer, if any
- [ ] Worth reading            one checkbox per question-day; a tick propagates to its claims
## Review                       borderline sources, at most 10, one checkbox each
## Bridges                      sources Jev judged to tie the question to something outside the line
> [!note]- Claims               folded list of every claim with its source and a checkbox
## Unjudged                     items whose Jev request failed, each tagged with the Jev function
## Operations                   questions asked, tokens, cost, per-net acceptance, canaries
```

Ticks are read back on the next run: `[x]` means yes (worth reading, correct), `[-]` means no, and
`[ ]` means no label. Obsidian's click toggles `[x]`; type `[-]` by hand. In a viewer other than
Obsidian the folded claim list shows as an ordinary quote block ([docs/scheduling.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/scheduling.md#reading-the-notes-outside-obsidian)).

## Source nets

An agent left to choose its own searches converges (the 37% in [Why judgment, not generation](#why-judgment-not-generation)). So code fixes which nets run, in
what order, and how many requests each may make. No model writes a query at run time: the keyword net
sends the queries written into the question file, and the recommendation and citation nets are seeded
by papers that Jev's screening kept. No model can add a net, skip one, or change the order.

| net | what it fetches | default budget (API requests per run) |
|---|---|---|
| firehose | new arXiv listings for fixed categories, plus Hugging Face daily papers; no query. When the arXiv listing is longer than the cap (300), the papers closest to the line's queries are kept | 2 |
| recommendation | Semantic Scholar recommendations seeded by ticked and kept papers, with random negatives | 1 |
| citation | OpenAlex forward citations of papers already kept | 3 |
| keyword | each question's authored queries, sent to arXiv (through OpenAlex's search), Hugging Face papers, GitHub and, with a key, Tavily web search | 10: the configured 12 minus a 20% share (2) set aside for exploration |
| exploration | neighbouring OpenAlex topics of the papers already kept; nothing until the store holds OpenAlex papers | 1, from the 2 set aside (the other goes unused) |

Every net works without source-API keys (Jev's TypeSafe key and the writing model's login or key are
always needed), with one exception inside the keyword net: the Tavily web-search source is skipped when `TAVILY_API_KEY` is
unset, and the note says so. Semantic Scholar, OpenAlex and GitHub have shared keyless quotas;
optional keys raise them. Budgets, the exploration share, arXiv categories and the OpenAlex daily
credit cap are set under `[nets]` in `config.toml`. The operations block reports acceptance per net
and the number of distinct OpenAlex topics among kept papers; a falling topic count is the
convergence alarm.

## The writing model

Only one step generates text: the per-question section. `JRP_PROSE_MODEL=<backend>:<model>` picks the
writer ([What you need](#what-you-need)); every backend goes through the same prompt, self-check and
Jev checks (step 6 of [How a morning run works](#how-a-morning-run-works)), and adding a backend means
adding it to `src/jev_research_pipeline/generation/client.py`. `jrp codex login` keeps the pipeline's own ChatGPT login in `~/.config/jrp/codex-auth.json`,
separate from the Codex CLI's (refresh tokens are single-use). How you use a subscription this way is
governed by your agreement with its provider.

## Status as of 2026-10-01

- **Daily since 2026-09-24** on my seven lines, in about 15 minutes a morning, writing
  Japanese (with `openai-codex:gpt-6-luna` until 2026-10-01). An evaluation of 11 runs before that is in
  [docs/pilot-log.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/pilot-log.md).
- **The prose moved to Claude Opus on 2026-10-02.** On my blind reading, Opus with the current
  prompt wrote the best sections. Jev's per-paragraph fidelity check kept sending them back: it
  judged background explained from a source's abstract as going beyond the claims, and on the
  prose bench it hardly told faithful drafts from unfaithful ones. It is now recorded, not a gate;
  fidelity rests on the prompt, the self-check and Jev's rubric. A replay of one line's morning
  wrote all three Opus sections at the first draft.
- **Thresholds.** Jev's routing thresholds started from TypeSafe's published examples and were tuned
  by hand; they have not been refit on ticks yet, so expect borderline calls in each note's Review
  section. `jrp fit` proposes a refit once at least 10 ticked claims include both `[x]` and `[-]`, and
  never applies it.
- **Alerts.** A degraded morning (a draft that failed or could not be checked, the writer's login
  failed, a source failed, too many unjudged pairs) says so in its notification; a section the Jev
  check rejected falls back without one. On macOS the launchd job also stops a run that
  hangs after an hour and runs `jrp doctor` before every run.

## Why judgment, not generation

I built jrp because my previous setup, [daily-research](https://github.com/shimo4228/daily-research),
let an Opus agent with web search run the whole loop through `claude -p`, Claude Code's
non-interactive mode. It reported $8 to $15 of usage a day for three or four topics, and the agent
kept returning to the same theme: 88 of its 238 past topics (37%) landed on one. The design bet is
that most of what an agent loop does with an LLM is judgment, and judgment can be asked of a model
that returns calibrated probabilities for a fixed set of answers. The full story is in the article
[Moving My Research Pipeline's Judgment Calls from an LLM to Jev, a Judgment-Only Model](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj)
([Japanese](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)). Three findings
from the evaluation shaped the current form:

- Without a question as the anchor, Jev's relevance judgments passed almost anything that shared a
  term with the line: a line about meditation and non-self filled up with claims about transformer
  attention. Anchoring every judgment on a (source, question) pair fixed this.
- A run before screening was staged asked Jev 20,573 questions for one line and produced a 283 KB
  note. Screening each source against the question first (a cheap on-topic check, then the full
  screen), and cutting claims only from kept sources, brought a line to roughly 900 to 1,900 questions
  during the evaluation (200 to 2,600 in daily use since). A size guard keeps everything in a note
  except the prose under 12 KB, by dropping Review lines.
- Prose is the hard part. The independent judge rated at most 2 of 3 notes publishable during the
  evaluation, and 1 of 3 on the last run; the usual failure was a paper's claim bent to fit the
  wording of the question. So the prose step was rebuilt around short source excerpts beside the
  verbatim claims, a self-check pass, and Jev's rubric on the finished section. These checks do
  not depend on which model writes.

## Development

```bash
uv sync
.claude/verify.sh     # format, lint, types, bandit, deptry, tests; offline, no keys
uv run pytest -q      # replays committed cassettes; live recording is opt-in (docs/configuration.md)
```

Traces are OpenTelemetry and off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set
([docs/observability.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/observability.md)). The prose bench that chose the prompts, and how to
run it, is in [AGENTS.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/AGENTS.md) (Japanese, for coding agents). The design record, every
decision and the evidence it rests on, is [docs/design/pipeline-design.md](https://github.com/shimo4228/jev-research-pipeline/blob/main/docs/design/pipeline-design.md).

## Related

- [TypeSafe Jev](https://docs.typesafe.ai) and the [Pydantic AI `typesafe:` model](https://pydantic.dev/docs/ai/models/typesafe/)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (the `claude-code:` writer)
- [Pydantic AI's OpenAI Codex provider](https://github.com/pydantic/pydantic-ai/blob/main/docs/models/openai-codex.md) (ChatGPT/Codex subscription)
- [Qwen on DashScope](https://www.alibabacloud.com/help/en/model-studio/models)

## More from the author

Each of my experiments with Jev is written up as an article, in English on Dev.to and in Japanese on
Zenn:

- [How Close to Opus Does Jev, a Model That Writes No Text, Get at Skill Selection in 0.3 Seconds?](https://dev.to/shimo4228/how-close-to-opus-does-jev-a-model-that-writes-no-text-get-at-skill-selection-in-03-seconds-1nfj)
  ([Japanese](https://zenn.dev/shimo4228/articles/jev-vs-opus-skill-selection)). Jev and Claude Opus
  pick skills for the same 150 situations. Jev agrees with Opus about half as often as Opus agrees
  with itself, at about 1/560th of the cost.
- [What Does It Take to Reproduce Jev's Decisions Locally?](https://dev.to/shimo4228/what-does-it-take-to-reproduce-jevs-decisions-locally-3i0n)
  ([Japanese](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)). Four local
  models replay the same 150 selections, and all four fail, each for a different reason.
- [I Added Jev's Skill Router to Claude Code and Turned Back Just Before Rewriting the Skill Listing](https://dev.to/shimo4228/i-added-jevs-skill-router-to-claude-code-and-turned-back-just-before-rewriting-the-skill-listing-34in)
  ([Japanese](https://zenn.dev/shimo4228/articles/jev-retrofit-limits)), with its code,
  [jev-skill-router](https://github.com/shimo4228/jev-skill-router). A Claude Code hook that asks Jev
  which installed skill fits each prompt. Running it showed it is unlikely to help a strong model.

The lines this pipeline watches are my own long-running projects. Among them:
[Agent Knowledge Cycle](https://github.com/shimo4228/agent-knowledge-cycle), a loop for keeping an
agent aligned with its operator as both change;
[Agent Attribution Practice](https://github.com/shimo4228/agent-attribution-practice), decision
records on who is accountable when an agent fails; and
[Authorship Strategy](https://github.com/shimo4228/authorship-strategy), on how an author stays
visible when readers meet ideas through LLMs. All of them, and new experiments as they appear, start
at [github.com/shimo4228](https://github.com/shimo4228). All articles: [Dev.to](https://dev.to/shimo4228)
(English) and [Zenn](https://zenn.dev/shimo4228) (Japanese).
