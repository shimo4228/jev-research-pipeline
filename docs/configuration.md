# Configuration

Every setting is an environment variable. Put them in `~/.config/jrp/env`; `scripts/launchd-jrp.sh`
sources that file before each scheduled run, and for a manual run you source it yourself:

```bash
set -a; source ~/.config/jrp/env; set +a
uv run jrp run
```

## Variables

| variable | required | purpose |
|---|---|---|
| `JRP_VAULT_DIR` | yes | vault root; notes go to `<vault>/daily-research/`. Unset: nothing is written |
| `JRP_STORE_DIR` | recommended | pipeline store, one JSON-LD file per line (default `./var/store`) |
| `TYPESAFE_API_KEY` | yes | Jev ([docs.typesafe.ai](https://docs.typesafe.ai)) |
| `JRP_PROSE_MODEL` | no | the model that writes the prose, `<backend>:<model>` (default `openai-codex:gpt-5.6-sol`; or e.g. `dashscope:qwen3.7-max`). See [The writing model](../README.md#the-writing-model) |
| `JRP_CODEX_AUTH` | no | where `jrp codex login` keeps the pipeline's own ChatGPT/Codex login (default `~/.config/jrp/codex-auth.json`); read by the `openai-codex` backend |
| `DASHSCOPE_API_KEY` | for `dashscope:` | Qwen through the DashScope international endpoint (Alibaba Cloud Model Studio); only needed when `JRP_PROSE_MODEL` names a `dashscope:` model |
| `JRP_DAILY_RESEARCH_CONFIG` | yes | the `config.toml` with your lines and `[nets]` |
| `JRP_COST_CAP_USD` | recommended | per-line cost cap; past it the run writes a partial note and moves on. Subscription prose (`openai-codex:`) counts 0 toward it |
| `JRP_JEV_USD_PER_QUESTION` | recommended | Jev unit price for the note's cost line; unset, Jev is not counted |
| `JRP_QUESTIONS_DIR` | no | question files (default `./questions`) |
| `JRP_PROSE_TIMEOUT_S` | no | prose call timeout (default 900 s; prose is written with thinking on) |
| `JRP_PROSE_THINKING` | no | `always` (default) / `rewrite` (second draft only) / `off`; DashScope's thinking flag, or the reasoning effort of an `openai-codex:` model (`off` = none, otherwise the model's default) |
| `JRP_JEV_CONCURRENCY` | no | concurrent Jev requests (default 12; a separate limiter holds 1,200 per minute) |
| `JRP_PROSE_CONCURRENCY` | no | concurrent prose-model calls (default 3) |
| `JRP_SLACK_NOTIFY` | no | `1` sends a one-line result to Slack |
| `JRP_DRIFT_LIVE` | no | `1` lets `jrp drift` call Jev live |
| `GITHUB_TOKEN` | no | raises GitHub search from 10 to 30 requests per minute (a fine-grained token with no permissions is enough) |
| `SEMANTIC_SCHOLAR_API_KEY` | no | recommendation net; without it the shared keyless quota may return 429 for the day |
| `OPENALEX_API_KEY` | no | raises OpenAlex's daily budget from 1,000 credits ($0.10) to 10,000 ($1), and the default `openalex_daily_credits` cap from 400 to 4,000. The citation and exploration nets and the `arxiv:` keyword search all spend it |
| `HF_TOKEN` | no | raises the Hugging Face daily papers rate limit |
| `TAVILY_API_KEY` | no | web-search source inside the keyword net; unset, that source is skipped and the note says so |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | enables OpenTelemetry export; see [observability.md](observability.md) |
| `JRP_CASSETTE_RECORD` | no (tests) | `1` records live HTTP responses into `tests/cassettes/live/` (gitignored); needs keys |
| `JRP_CASSETTE_SYNTHETIC` | no (tests) | `1` regenerates the committed synthetic cassettes from `tests/fakes.py` |

## `config.toml`

```toml
[general]
lines_per_day = 3                  # lines picked per run, in fixed rotation

[tracks.akc]                       # one table per line; "track" and "line" mean the same thing
name = "Agent Knowledge Cycle"
[[tracks.akc.repos]]
target_repo = "~/projects/agent-knowledge-cycle"   # required for rotation; only graph.jsonld is read

[tracks.jev]
name = "TypeSafe Jev"
daily = true                       # runs on every tick beside the rotated lines

[nets]                             # all keys optional
firehose = 2                       # API requests per run, per net
recommendation = 1
citation = 3
keyword = 12
exploration = 1
exploration_share = 0.2            # share of the keyword budget spent on neighbouring topics
arxiv_categories = ["cs.AI", "cs.CL", "cs.LG", "cs.HC"]
openalex_daily_credits = 400       # our own daily cap; default 400 keyless, 4000 with OPENALEX_API_KEY
firehose_max = 300                 # sources taken from the firehose per line per run
```

`openalex_daily_credits` counts every OpenAlex request across the day's lines: a citation or
exploration list costs 1 credit, an `arxiv:` keyword search 10 (it is an OpenAlex `search=`
restricted to the arXiv source; arXiv's own API refuses Python clients since 2026-09-24). Leave
it out to get the default for whether `OPENALEX_API_KEY` is set.

When the arXiv listing holds more than `firehose_max` new papers, the ones kept are ranked by
BM25 against the line's English query text — the open questions' `arxiv:` / `hf:` / `github:`
lines plus the line vocabulary — and the note says `firehose: 関連度順に上位 N 件 (M 件を省略)`.
Hugging Face daily papers keep their place ahead of it. With no query text the cut is in feed
order. `arxiv_keyword_max` is no longer read; a config that still has it loads unchanged.

A line enters the daily rotation only when it has a `[[tracks.<slug>.repos]]` entry. If that directory
holds a `graph.jsonld` (a JSON-LD file; the `name` and `alternateName` of its `Concept` and
`DefinedTerm` nodes become the line's vocabulary for screening and the prose) the vocabulary is
read from it; otherwise the line's `name` is the only vocabulary. A line with `daily = true` runs on
every tick and needs no repo.

## Store schema changes

Every command inspects the store first. Additive changes are rewritten in place and noted in the
operations block. Incompatible changes stop before reading or writing anything, naming the file:
`jrp migrate --dry-run` shows the plan and `jrp migrate` applies it, moving incompatible files to
`<store>/retired/<date>/` rather than deleting them.
