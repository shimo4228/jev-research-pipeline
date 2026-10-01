---
name: jrp-question
description: Set up or revise the questions of one jrp research line — the open questions, what each one rules out, and the search queries that feed it — and trial the queries before the next run. Use when someone says "help me write questions for my research line", "このラインの問いを立てたい", "帮我为这个研究方向写几个问题", after `jrp init`, when a question was reworded, or when a line's notes have shown no moving question for two weeks. NOT for running the pipeline (`jrp run` / `jrp try`), for improving the note's prose (the prose bench in AGENTS.md), or for the store's evidence (a run grows it).
user-invocable: true
origin: shimo4228
---

# Questions for a jrp line

A jrp line is read through its questions: every source is screened against them, every
claim is kept for one of them, and the note has one section per question that moved. The
questions and their query lines set the ceiling of what a line can find. They belong to
the person who reads the notes; a run never writes them. Write in the language the person
uses with you; query lines are mostly English (below).

The file is `<JRP_QUESTIONS_DIR>/<line slug>.md` (default `~/.config/jrp/questions/`; the
line slug is the `[tracks.<slug>]` of config.toml). Its format is in the docstring of
`src/jev_research_pipeline/questions.py`; the block below is the shape to write.

## 1. The theme

Ask, one question at a time, until you can say in two sentences: what the person wants to
know about this field, why it matters to their own work, and what they would do
differently with an answer. Read the line's existing question file if there is one, and
`graph.jsonld` of the line's repo if config.toml names one (its concept names are the
line's vocabulary).

## 2. Two to four questions

Each question is one that today's research could move but has not settled — a question
whose answer someone could change next week with a measured result. Prefer "which / how
much / under what conditions" over "is X good". For each:

- the heading (`## …`): the question itself, in the person's language
- `brief:` what an answer would contain and what it would change for them, one line
- `method:` the kinds of study that would bear on it (one line each)
- `evidence:` what counts as an answer (measured, reproducible, a working repo …)
- `not:` the neighbouring topics that look relevant but are not — the screen drops them,
  and a missing `not:` is the most common cause of a noisy note
- `slug:`, `version: 1`, `status: open`, `opened: <today>`, `retire:` (when to close it)

Read the questions back to the person and let them cut or merge. Two sharp questions find
more than four broad ones.

## 3. This week's vocabulary

The terms of this field change week to week: search before writing any query, never from
memory. Search recent arXiv (or OpenAlex), Hugging Face papers and GitHub for each
question and note the words that real titles and READMEs use. Use the terms of sources a
past run kept for this question too, if the store has any.

## 4. Query lines

One query per line, one or two per adapter, aimed at what would move this question — not
at the line's vocabulary in general. Words of a `not:` topic stay out.

- `- arxiv:` two to four words. Sent as is to OpenAlex full-text search restricted to the
  arXiv source: words are ANDed over title, abstract and full text (each word narrows),
  stemmed, stopwords dropped; the last 90 days, 20 results by relevance; OpenAlex indexes
  about 3 days after arXiv announces. Each costs 10 of the day's OpenAlex credits. No
  quotes, no boolean operators.
- `- github:` short keywords; GitHub qualifiers such as `topic:x` work.
- `- hf:` a natural English phrase (Hugging Face papers search).
- `- web:` Tavily web search (needs `TAVILY_API_KEY`; free tier 1,000 searches a month).
  A question whose primary sources are in another language (blogs, Japanese or Chinese
  posts) may have a query in that language here.

A question with no query line sends no keyword search at all (the other nets still run).

## 5. Trial

```bash
set -a; source ~/.config/jrp/env; set +a
jrp queries check --line <slug>
```

One live request per query; nothing is stored. Read the top hits of each:

- 0 hits → fewer words, or other words
- the top hits are from another field → add a word of this field, or replace one
- a 429 failure → that service's rate limit; wait, and do not rerun in a loop

## 6. Canaries

Ask for, or find, one to three papers or repos that clearly answer part of a question.
Add them as `- canary: <url>`: every run that finishes within its cost cap screens them
(fetching any the nets did not bring, unless that source is rate-limited that day), and the
note says when the screen drops one — a canary is how the person learns the screen has
drifted.

## 7. Save and see it

Write the file and show the person the whole block once. If the env file is new, run
`jrp doctor` first: `jrp try` spends Jev, the prose model and search credits, and needs the
vault and the key. Then:

```bash
jrp try --line <slug>
```

runs the line once into a scratch folder and prints the note's path.

## The block

Illustrative only — the fields and their order are what to copy:

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
- canary: https://arxiv.org/abs/2609.01234
- arxiv: agent memory benchmark
- github: agent memory
- hf: long-term memory for LLM agents
```

Rewording a question's heading or `brief` is a new question: raise `version` (the evidence
gathered so far stays with the old version).
