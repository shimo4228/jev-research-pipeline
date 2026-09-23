# jev-research-pipeline

[日本語](README.ja.md) (older; not yet synced with this version)

**Code owns the loop, Jev judges, Qwen writes: a daily research monitor for standing questions.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![Status: pilot](https://img.shields.io/badge/status-pilot-orange.svg)](docs/pilot-log.md)

jev-research-pipeline is a single-user, daily research-monitoring pipeline. You keep a few open
questions per research line (a line is one long-running research topic with its own vocabulary).
Deterministic Python owns the control flow. TypeSafe Jev, a judgment model that answers typed
questions with probabilities and never writes text, screens every fetched source against each open
question. Qwen, an LLM served on Alibaba Cloud's DashScope, writes only the day's prose. The output
is one markdown note per line in an Obsidian vault, organised by question, and you close the loop by
ticking checkboxes in that note. Notes are written in Japanese today: the prose instruction and the
section headings are Japanese strings in the source, and there is no language switch yet. Scheduling
uses macOS launchd; a manual run works anywhere Python 3.12 runs.

I built it because LLM-driven deep-research loops converge on the same topics and cost real money
every morning. In my previous setup an Opus agent with web search explored three or four lines a day
for $4 to $15, and over one month 37% of its topics landed on a single theme. Moving judgment into
cheap typed questions makes the loop machine-checkable, and a run over four lines now costs about
$0.15 to $0.30.

## How a run works

You read each note and tick its checkboxes. Those ticks are the labels: they feed the threshold
proposals that `jrp fit` writes for you to apply, seed the recommendation net, and become evaluation
cases. Everything else is the pipeline.

1. Harvest ticks from yesterday's notes (a checkbox per question, per source, per claim).
2. Pick the next three research lines in rotation, plus any line marked daily.
3. For each open question, fetch candidates from five fixed discovery channels, the source nets
   (see [Source nets](#source-nets)).
4. Jev screens each (source, question) pair: hard gates as yes/no questions, then weighted scores.
   Code applies the thresholds and routes the pair to Keep, Review (borderline), Drop, or Incomplete
   (the source had no abstract to judge).
5. Kept sources are cut into verbatim sentences; Jev marks which sentences advance or contradict the
   question. A claim is a sentence, never a paraphrase, so citations always resolve.
6. Qwen writes one short section per question that got new evidence today, with evidence paragraphs
   and one paragraph marked as inference. Jev then scores the section on a rubric; a failing draft is
   rewritten once, then falls back to a template.
7. The note is written to the vault with an operations block: Jev question count, tokens, cost,
   per-net acceptance, canary results.

Every Jev call goes through Pydantic AI's native `typesafe:` model, so each judgment is a Pydantic
output type and the raw probability distributions are stored with the decision.

## Status as of 2026-09-23

This is a pilot, not a finished product.

- 11 runs on my own eight research lines (2 wrote the real vault). The last run passed 5 of its 7
  goal conditions: every note under 12 KB with a short Review list; prose for every question that had
  evidence; off-topic papers dropped and every canary kept (a canary is a paper or repo a question
  must always keep; see [Questions are the unit](#questions-are-the-unit)); no failed fetch from any
  source API; no stack traces.
- It failed the other two. Wall time for four lines was 601 s against a 600 s cap (cost, the other
  half of that condition, was $0.297 against a $0.30 cap). An independent judge (a separate Opus model
  reading only the finished notes against a seven-axis rubric) rated 1 of 3 notes publishable: the
  prose still bends a paper's claim to fit the wording of the question. The full record, run by run,
  is in [docs/pilot-log.md](docs/pilot-log.md).
- Jev's routing thresholds are still the starting values from TypeSafe's cookbooks, not yet refit on
  ticks. The Review section of a note lists the borderline sources for exactly that reason.

## Quick start

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- A TypeSafe API key ([docs.typesafe.ai](https://docs.typesafe.ai)) and a DashScope API key
  (Alibaba Cloud Model Studio).
- One file, `~/.config/jrp/env`, holding every environment variable (paths and keys); research lines
  and net budgets live in `config.toml`, questions in the repo's `questions/` directory.
  `scripts/launchd-jrp.sh` sources the env file before a scheduled run; for a manual run:
  `set -a; source ~/.config/jrp/env; set +a`.

A minimal `~/.config/jrp/env`:

```bash
export JRP_VAULT_DIR="/path/to/your/obsidian/vault"     # notes go to <vault>/daily-research/
export JRP_STORE_DIR="/path/to/store"                   # pipeline state, one JSON-LD file per line
export TYPESAFE_API_KEY="..."
export DASHSCOPE_API_KEY="..."
export JRP_COST_CAP_USD="0.50"                          # per line per run
export JRP_DAILY_RESEARCH_CONFIG="/path/to/config.toml" # your research lines
```

`config.toml` names the lines. Each line is a `[tracks.<slug>]` table ("track" and "line" mean the
same thing). A line enters the daily rotation only if it has a `[[tracks.<slug>.repos]]` entry; if
that directory holds a `graph.jsonld` (a JSON-LD file whose `Concept` and `DefinedTerm` node names
become the line's vocabulary for query writing and screening) the vocabulary is read from it, and
otherwise the line's name is the only vocabulary. A line with `daily = true` runs on every tick beside
the rotation and needs no repo.

```toml
[general]
lines_per_day = 3

[tracks.akc]
name = "Agent Knowledge Cycle"
[[tracks.akc.repos]]
target_repo = "~/projects/agent-knowledge-cycle"   # required for rotation; only graph.jsonld is read

[tracks.jev]
name = "TypeSafe Jev"
daily = true                                       # every tick, beside the rotated lines
```

Write at least one open question per line (next section), then:

```bash
uv sync
uv run jrp run                # harvest ticks, run the next lines, write notes
```

A line with no open question is skipped and reported as such. Maintenance commands, once ticks
exist: `jrp fit` proposes refit thresholds (it writes a proposal file, never applies it),
`jrp export-cases` turns ticked claims into pydantic-evals cases, `jrp queries check --line <slug>`
trial-fetches a line's authored queries, `jrp prose export|bench|pairs|tally` is the dev-time loop for
the prose (frozen inputs, blind pairs for a judge; [AGENTS.md](AGENTS.md)), `jrp drift` replays recorded Jev
inputs live and reports probability drift, and `jrp migrate --dry-run` shows how an older store would
be upgraded. Every variable and the full `config.toml` are in
[docs/configuration.md](docs/configuration.md).

## Questions are the unit

One file per line at `questions/<slug>.md` in the repository (or wherever `JRP_QUESTIONS_DIR`
points). The pipeline is exactly as good as the questions.

```markdown
<!-- jrp:questions:akc -->

## What tells you a scaffold (a rule, a skill, a procedure) is ready to be retired?
- slug: scaffold-retirement-signal
- version: 1
- status: open
- opened: 2026-09-23
- retire: close once products retire scaffolds natively and three practitioners report relying on that
- brief: usage counts, ablations and held-out transfer are all used in practice; which one misses what?
- method: product instrumentation
- method: practitioner reports
- evidence: reports that say what was counted and what was not
- not: prompt engineering tips
- canary: https://github.com/scienthoon/jev-ood-calibration
- arxiv: scaffold retirement agent
- github: agent skill lifecycle
- hf: when to remove agent instructions
```

The parser reads every field; two of them are for you rather than for Jev. `slug` and `version`
identify the question: change the wording, bump the version, or old judgments count as judgments of
the new wording. `status` gates the run (`open` / `answered` / `dropped`) and `opened` is the date you
opened it. `brief`, `method` and `evidence` go into the state Jev sees for every (source, question)
pair. `not:` lines feed the hard gates with adjacent topics that would otherwise pass every day.
`retire:` is prose for you, the rule you set in advance for closing the question.

`canary:` lines name papers or repos this question must always keep. If no net brings one on a given
day it is fetched by its URL and screened anyway, and a dropped canary shows up in the note's
operations block as a sign that screening drifted.

`arxiv:`, `github:`, `hf:` and `web:` lines are the keyword net's search queries for this question,
one per line, in English. They are written together with the question and tried before a run relies
on them: `uv run jrp queries check --line <slug>` sends each query once and prints the hit count and
the newest titles, storing nothing. arXiv matches every word (`all:w1 AND all:w2`), so keep its
queries to two to four words. A question without query lines sends no keyword query (the note's
operations block says so); the other nets still run for it. The authoring procedure is in
[AGENTS.md](AGENTS.md).

No run writes to this file. Questions and their queries change when you change them.

## What a note looks like

Headings and prose are Japanese; the layout is:

```
### <question>                 one section per question that got new evidence today
今日の変化                      prose; [n] cites a claim; the paragraph marked 【推論】 is inference
証拠                            today's sources for this question
- [ ] worth reading             one checkbox per question-day; a tick propagates to its claims
## Review                       borderline pairs (confidence below 0.9); your tick feeds the next threshold proposal
## 橋渡し                         bridged sources: found by the exploration net outside the vocabulary
> [!note]- Claims               folded list of every claim with its source and a checkbox
## 運用                          the operations block
```

Ticks are read back on the next run: `[x]` means yes (worth reading, correct), `[-]` means no, and
`[ ]` means no label. Obsidian's click toggles `[x]`; type `[-]` by hand.

## Source nets

Keyword search alone converges (the 37% figure above). So code fixes which nets run, in what order,
and how many requests each may make. No model writes a query: the keyword net sends the queries written into
the question file, and the recommendation and citation nets are seeded by papers that Jev's
screening kept. No model can add a net, skip one, or change the order.

| net | what it fetches | default budget (API requests per run) |
|---|---|---|
| firehose | new arXiv listings for fixed categories, plus Hugging Face daily papers; no query | 2 |
| recommendation | Semantic Scholar recommendations seeded by ticked and kept papers, with random negatives | 1 |
| citation | OpenAlex forward citations of papers already kept | 3 |
| keyword | each question's authored queries, sent to arXiv, Hugging Face papers, GitHub and, with a key, Tavily web search | 12 |
| exploration | neighbouring OpenAlex topics: one request of its own, and 20% of the keyword queries are aimed at those topics instead of the line's own | 1 |

Every net works without source-API keys (the TypeSafe and DashScope keys are always needed), with one
exception inside the keyword net: the Tavily web-search source is skipped when `TAVILY_API_KEY` is
unset, and the note says so. Semantic Scholar, OpenAlex and GitHub
have shared keyless quotas; optional keys raise them. Budgets, arXiv categories and the OpenAlex daily
credit cap are set under `[nets]` in `config.toml`. The operations block reports acceptance per net
and the number of distinct OpenAlex topics among kept papers; a falling topic count is the convergence
alarm.

## Why judgment, not generation

The design bet is that most of what an agent loop does with an LLM is judgment, and judgment can be
asked as typed questions of a model that returns calibrated probabilities. Three measurements from
the pilot shaped the current form:

- Without a question as the anchor, Jev's relevance judgments passed almost anything sharing a term
  with the line: one line about meditation and non-self collected 162 claims about transformer
  attention. Anchoring every judgment on (source, question) fixed this.
- The first run, which treated every sentence as a claim without a question, asked Jev 20,573
  questions for one line and produced a 283 KB note. Staged screening per question brought the same
  line to a few thousand questions and a note under 12 KB.
- Prose written from a bag of verbatim claims reads like a bag of claims. Writing per question, with
  inference confined to one marked paragraph, moved the independent judge from 0 of 3 publishable
  notes (run 6) to 1 of 3 (runs 8 and 11); the verdicts and their evidence are in
  [docs/pilot-log.md](docs/pilot-log.md).

The design record, including every decision and the external evidence it rests on, is
[docs/design/pipeline-design.md](docs/design/pipeline-design.md).

## Observability, scheduling, development

Traces are OpenTelemetry. With `OTEL_EXPORTER_OTLP_ENDPOINT` unset the SDK is never initialised and
every span is a no-op. A Docker-free local viewer and the span names are in
[docs/observability.md](docs/observability.md).

Two launchd plists (daily run, weekly drift) live in [launchd/](launchd/README.md); edit the absolute
paths for your machine before loading them.

```bash
.claude/verify.sh     # format, lint, types, bandit, deptry, tests; offline, no keys
uv run pytest -q      # replays committed cassettes; live recording is opt-in (docs/configuration.md)
```

## Related

- [TypeSafe Jev](https://docs.typesafe.ai) and the [Pydantic AI `typesafe:` model](https://pydantic.dev/docs/ai/models/typesafe/)
- [Qwen on DashScope](https://www.alibabacloud.com/help/en/model-studio/models)
