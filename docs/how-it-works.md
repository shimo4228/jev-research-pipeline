# How jrp works

The README says what jrp is and how to try it. This page is the inside: what a morning run does,
what a note contains, where sources come from, how the prose is written and checked, and why it
is built this way. Every decision and the evidence behind it is in
[design/pipeline-design.md](design/pipeline-design.md).

Words used below: a **line** is one topic you follow, with two to four open **questions**. A
**claim** is one verbatim sentence jrp quotes from a source. A **question-day** is one question on
one day. The **store** is jrp's own record of past sources and judgments, one JSON-LD file per line.

## A morning run

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
6. The writing model writes one short section per question that got new evidence today, from those
   claims and short excerpts of their sources, with one paragraph marked as inference. It checks its
   own draft once. Jev then scores the section on a rubric (readable, coherent, nothing the claims and
   excerpts do not support); a failing draft is rewritten once, then the section falls back to a list
   of its sources.
7. The note is written to the vault with an operations block: Jev question count, tokens, cost,
   per-net acceptance, and canary results (whether the papers a question must always keep were kept).

Your ticks are the labels. They seed the recommendation net (papers related to the ones you ticked),
feed the threshold proposals that `jrp fit` writes for you to apply, and become evaluation cases.
Every Jev call goes through Pydantic AI's native `typesafe:` model, so each judgment is a Pydantic
output type and the raw probability distributions are stored with the decision.

## What a note contains

```
# <line> — <date>
## <question>                  one section per question that got new evidence today
### What changed today         prose; [n] cites a claim; the last paragraph, marked [Inference], is inference
### Evidence                   today's sources for this question
### Counter-evidence           claims that count against the answer, if any
- [ ] Worth reading            one checkbox per question-day; a tick propagates to its claims
---                            below: closed callouts, one per non-empty list
> [!info]- Review — N …        borderline sources, at most 10, one checkbox each
> [!info]- Bridges — N         sources Jev judged to tie the question to something outside the line
> [!info]- Claims — N          every claim with its source and a checkbox
> [!info]- Unjudged — N        items whose Jev request failed, each tagged with the Jev function
> [!info]- Operations          questions asked, tokens, cost, per-net acceptance, canaries
```

Ticks are read back on the next run: `[x]` means yes (worth reading, correct), `[-]` means no, and
`[ ]` means no label. Obsidian's click toggles `[x]`; type `[-]` by hand. In a viewer other than
Obsidian the folded lists show as ordinary quote blocks ([scheduling.md](scheduling.md#reading-the-notes-outside-obsidian)).
The headings follow the note's language.

## The question file

One file per line at `~/.config/jrp/questions/<slug>.md` (or wherever `JRP_QUESTIONS_DIR` points).
`jrp questions new --line <slug>` opens a Claude Code session that walks you through writing one; the
procedure is the skill [`jrp-question`](../.claude/skills/jrp-question/SKILL.md). An example block:

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

## Source nets

An agent left to choose its own searches converges (the 37% in [Why judgment, not
generation](#why-judgment-not-generation)). So code fixes which nets run, in what order, and how many
requests each may make. No model writes a query at run time: the keyword net sends the queries
written into the question file, and the recommendation and citation nets are seeded by papers that
Jev's screening kept. No model can add a net, skip one, or change the order.

| net | what it fetches | default budget (API requests per run) |
|---|---|---|
| firehose | new arXiv listings for fixed categories, plus Hugging Face daily papers; no query. When the arXiv listing is longer than the cap (300), the papers closest to the line's queries are kept | 2 |
| recommendation | Semantic Scholar recommendations seeded by ticked and kept papers, with random negatives | 1 |
| citation | OpenAlex forward citations of papers already kept | 3 |
| keyword | each question's authored queries, sent to arXiv (through OpenAlex's search), Hugging Face papers, GitHub and, with a key, Tavily web search | 10: the configured 12 minus a 20% share (2) set aside for exploration |
| exploration | neighbouring OpenAlex topics of the papers already kept; nothing until the store holds OpenAlex papers | 1, from the 2 set aside (the other goes unused) |

Every net works without source-API keys (Jev's TypeSafe key and the writing model's login or key are
always needed), with one exception inside the keyword net: the Tavily web-search source is skipped
when `TAVILY_API_KEY` is unset, and the note says so. Semantic Scholar, OpenAlex and GitHub have
shared keyless quotas; optional keys raise them. Budgets, the exploration share, arXiv categories and
the OpenAlex daily credit cap are set under `[nets]` in `config.toml`. The operations block reports
acceptance per net and the number of distinct OpenAlex topics among kept papers; a falling topic count
is the convergence alarm.

## The writing model

Only one step generates text: the per-question section. `JRP_PROSE_MODEL=<backend>:<model>` picks the
writer (`openai-codex:`, `claude-code:` or `dashscope:`); every backend goes through the same prompt,
self-check and Jev checks (step 6 of [A morning run](#a-morning-run)), and adding a backend means
adding it to `src/jev_research_pipeline/generation/client.py`. `jrp codex login` keeps the pipeline's
own ChatGPT login in `~/.config/jrp/codex-auth.json`, separate from the Codex CLI's (refresh tokens
are single-use). How you use a subscription this way is governed by your agreement with its provider.

A section costs the writer one draft and one self-check, about 8,000 to 12,000 input and 1,500 to
4,000 output tokens on `openai-codex:gpt-6-luna`, and about 11,000 input and 5,000 output tokens on
`claude-code:claude-opus-5-5`; a rejected draft is written once more.

The prose moved to Claude Opus on 2026-10-02. On my blind reading, Opus with the current prompt wrote
the best sections. Jev's per-paragraph fidelity check kept sending them back: it judged background
explained from a source's abstract as going beyond the claims, and on the prose bench it hardly told
faithful drafts from unfaithful ones. It is now recorded, not a gate; fidelity rests on the prompt,
the self-check and Jev's rubric. A replay of one line's morning wrote all three Opus sections at the
first draft.

## Languages

`JRP_NOTE_LANG` (`en`, `zh` or `ja`) sets the note's language: the headings, the operations section
and the prose, whose prompt and checks were written for each language rather than translated. The
machine-read parts of a note are the same in every language, so ticks work alike.

I read Japanese only. The Japanese prompt was chosen by my own blind reading. The English and Chinese
prompts were accepted on the prose bench's measurements alone (the bench redrafts the sections of
past days with each candidate prompt and has them judged): over the same 32 past question-days,
drafts written by Claude Opus passed a fidelity judge (another Opus, checking each draft against its
sources) 28 of 32 times in English and 32 of 32 in Chinese (Japanese: 28 of 32), and a simulated
reader that saw only the draft took away at least as much of each study as from the Japanese one.
The default writer, GPT-6 Luna, has not been measured in English or Chinese. The record is in
[design/pipeline-design.md](design/pipeline-design.md) ("Prose in English", "Prose in Chinese").

## Cost in detail

Measured from the notes' own operations sections, 2026-09-24 to 2026-10-01.

| | per line-run (3 open questions) | per morning (4 lines) |
|---|---|---|
| Jev questions | 200 to 2,600 | 2,470 to 8,191 |
| Jev cost at $0.00002 a question | $0.004 to $0.05 | $0.05 to $0.16 |
| prose sections written | 0 to 3 (one per question that moved) | 5 to 8 |

The $0.00002 is the Jev price set in my env for the cost line; TypeSafe bills $42 per billion input
tokens (typesafe.ai, 2026-10-07). On a subscription writer the writer's tokens count against the
plan's usage, not in dollars; on DashScope multiply by the model's token price. Searching costs
nothing without keys; OpenAlex's free daily budget is shared by all lines.

The comparison in the README sets two measured weeks side by side. My previous setup's
`metrics.jsonl` records $7.97 to $14.84 a morning from 2026-09-15 to 09-22 (three or four reports,
107 to 242 model turns). jrp's notes from 2026-10-03 to 10-07 record 70,000 to 98,000 input and
38,000 to 49,000 output tokens a morning for the Opus writer, which is $1.07 to $1.36 at Opus 5.5's
$4 / $20 per million tokens; with $0.03 to $0.17 of Jev, a morning comes to $1.11 to $1.53. Most of the difference is input: an agent
re-reads its growing context on every turn, and jrp has no turns. The writer goes through the Claude
Code CLI, whose own system prompt may not be in the recorded counts.

## Status

- **Daily since 2026-09-24** on my seven lines, in about 15 minutes a morning, writing Japanese. An
  evaluation of 11 runs before that is in [pilot-log.md](pilot-log.md).
- **Thresholds.** Jev's routing thresholds started from TypeSafe's published examples and were tuned
  by hand; they have not been refit on ticks yet, so expect borderline calls in each note's Review
  section. `jrp fit` proposes a refit once at least 10 ticked claims include both `[x]` and `[-]`, and
  never applies it.
- **Alerts.** A degraded morning (a draft that failed or could not be checked, the writer's login
  failed, a source failed, too many unjudged pairs) says so in its notification; a section the Jev
  check rejected falls back without one. On macOS the launchd job also stops a run that hangs after an
  hour and runs `jrp doctor` before every run.

## Why judgment, not generation

My previous setup, [daily-research](https://github.com/shimo4228/daily-research), let an Opus agent
with web search run the whole loop through `claude -p`, Claude Code's non-interactive mode. It kept
returning to the same theme: in its first three months (2026-02-24 to 05-27), 88 of the 238
topics it chose (37%) landed on one. The design bet is that
most of what an agent loop does with an LLM is judgment, and judgment can be asked of a model that
returns calibrated probabilities for a fixed set of answers. The full story is in the article
[Moving My Research Pipeline's Judgment Calls from an LLM to Jev, a Judgment-Only Model](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj)
([Japanese](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)). Three findings
from the evaluation shaped the current form:

- Without a question as the anchor, Jev's relevance judgments passed almost anything that shared a
  term with the line: a line about meditation and non-self filled up with claims about transformer
  attention. Anchoring every judgment on a (source, question) pair fixed this.
- A run before screening was staged asked Jev 20,573 questions for one line and produced a 283 KB
  note. Screening each source against the question first (a cheap on-topic check, then the full
  screen), and cutting claims only from kept sources, brought a line to roughly 900 to 1,900
  questions during the evaluation (200 to 2,600 in daily use since). A size guard keeps everything in
  a note except the prose under 12 KB, by dropping Review lines.
- Prose is the hard part. The independent judge rated at most 2 of 3 notes publishable during the
  evaluation, and 1 of 3 on the last run; the usual failure was a paper's claim bent to fit the
  wording of the question. So the prose step was rebuilt around short source excerpts beside the
  verbatim claims, a self-check pass, and Jev's rubric on the finished section. These checks do not
  depend on which model writes.

## Development

```bash
uv sync
.claude/verify.sh     # format, lint, types, bandit, deptry, tests; offline, no keys
uv run pytest -q      # replays committed cassettes; live recording is opt-in (configuration.md)
```

Traces are OpenTelemetry and off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set
([observability.md](observability.md)). The prose bench that chose the prompts, and how to run it, is
in [AGENTS.md](../AGENTS.md) (Japanese, for coding agents).
