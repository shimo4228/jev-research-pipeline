# Configuration

`jrp init` writes a starting setup where jrp looks by default, leaving any file that already
exists alone: `~/.config/jrp/env` (0600; fill in `JRP_VAULT_DIR` and `TYPESAFE_API_KEY`),
`~/.config/jrp/config.toml` with one line, and `~/.config/jrp/questions/agent-memory.md` with one
open question and its query lines (`--lang ja|en|zh` sets `JRP_NOTE_LANG`, default `en`).
`jrp try --line <slug>` then runs that one line once into `~/.local/share/jrp/try/<time>/` and
prints the note's path: the real store, vault and rotation are not touched, and nothing is
notified.

Every setting is an environment variable. Put them in `~/.config/jrp/env`; `scripts/launchd-jrp.sh`
sources that file before each scheduled run, and for a manual run you source it yourself:

```bash
set -a; source ~/.config/jrp/env; set +a
uv run jrp run
```

`uv run jrp doctor` checks what a run needs without running one and prints one line per check
(`ok` or `FAIL`), exiting non-zero on a failure: `JRP_VAULT_DIR` and `JRP_STORE_DIR` are set,
`config.toml` loads and its lines resolve, the question files parse (a line without an open
question is named, not failed), `TYPESAFE_API_KEY` is set, and the `JRP_PROSE_MODEL` writer is
reachable — for `openai-codex:` the login file reads (it is never refreshed), for `dashscope:` and
`anthropic:` the key is set (not tried), for `claude-code:` the CLI is found and `claude auth status` reports it logged in. It
writes nothing, does not open the vault, and calls no API. The launchd wrapper runs it before
every scheduled run (see [launchd/README.md](../launchd/README.md)).

## Variables

| variable | required | purpose |
|---|---|---|
| `JRP_VAULT_DIR` | yes | vault root; notes go to `<vault>/daily-research/`. Unset: nothing is written |
| `JRP_STORE_DIR` | no | pipeline store, one JSON-LD file per line (default `~/.local/share/jrp/store`) |
| `TYPESAFE_API_KEY` | yes | Jev ([docs.typesafe.ai](https://docs.typesafe.ai)) |
| `JRP_PROSE_MODEL` | no | the model that writes the prose, `<backend>:<model>` (default `openai-codex:gpt-6-luna`; or e.g. `claude-code:claude-opus-5-5`, `anthropic:claude-opus-5-5`, `dashscope:qwen3.7-max`). See [The writing model](how-it-works.md#the-writing-model) |
| `JRP_CODEX_AUTH` | no | where `jrp codex login` keeps the pipeline's own ChatGPT/Codex login (default `~/.config/jrp/codex-auth.json`); read by the `openai-codex` backend |
| `DASHSCOPE_API_KEY` | for `dashscope:` | Qwen through the DashScope international endpoint (Alibaba Cloud Model Studio); only needed when `JRP_PROSE_MODEL` names a `dashscope:` model |
| `ANTHROPIC_API_KEY` | for `anthropic:` | the Claude API, billed per token to the key's Console organization (a Claude Max plan's monthly API credits pay it once that organization is linked to the plan); needed when `JRP_PROSE_MODEL` names an `anthropic:` model. `jrp wbr` uses it too, for the weekly review's monitoring judge (Claude Opus 5.5, up to `JRP_MONITOR_WEEKLY_USD` a week, see [The weekly review](#the-weekly-review)); unset, the review calls nothing and says "not measured (no key)". The `claude-code:` backend never passes it to the CLI |
| `JRP_MONITOR_WEEKLY_USD` | no | the weekly review's monitoring judge's cap per ISO week, in USD at API prices (default 5.0). Before each call it reserves the most that call can cost and starts it only while the week's calls, reserved and settled, stay within the cap, so calls in flight, calls cut off by the deadline and a second review running at the same time all count toward it. A value that is not a number of 0 or more turns the judge off for that review |
| `JRP_EVAL_WEEKLY_USD` | no | the gate eval's silver labeller's cap per ISO week, in USD at API prices (default 10.0): `jrp eval gate label` calls Claude Opus 5.5 with `ANTHROPIC_API_KEY`, reserving each call's upper bound in `<store>/evals/silver.jsonl` first, as the monitoring judge does; unset key, it calls nothing and the silver rows of `jrp eval gate` read 未測定. Development only: no run calls it |
| `JRP_DAILY_RESEARCH_CONFIG` | no | the `config.toml` with your lines and `[nets]` (default `~/.config/jrp/config.toml`) |
| `JRP_COST_CAP_USD` | recommended | per-line cost cap; past it the run writes a partial note and moves on. Subscription prose (`openai-codex:`, `claude-code:`) counts 0 toward it; `anthropic:` counts at API prices (about $0.10 to $0.85 a line on Opus 5.5, mean $0.44, measured 2026-10-03..10-19; set the cap well above the high end, e.g. 2.00) |
| `JRP_JEV_USD_PER_QUESTION` | recommended | the Jev price assumed per question, for the note's cost line ("Jev estimated cost" on a subscription writer; "Estimated cost", Jev plus the writer's tokens, on a per-token one); unset, Jev is not counted and the line says the price is not set |
| `JRP_QUESTIONS_DIR` | no | question files (default `~/.config/jrp/questions`) |
| `JRP_NOTE_LANG` | no | the note's language: `ja` (default), `en` or `zh` — headings, the operations section and the prose (its prompt and its checks). Anything else stops the run at the start |
| `JRP_GITHUB_OWNER` | no | derive a line's @id from `github.com/<owner>/<repo name>` (`github.com/<owner>` for a line with no repo) when its `graph.jsonld` names no ResearchLine. Unset, such a line is `<store namespace>line/<slug>`. Set it only to keep the ids a store was built on |
| `JRP_PROSE_TIMEOUT_S` | no | prose call timeout (default 900 s; prose is written with thinking on) |
| `JRP_PROSE_THINKING` | no | `always` (default) / `rewrite` (second draft only) / `off`; DashScope's thinking flag, or the reasoning effort of an `openai-codex:` model (`off` = none, otherwise the model's default, medium for `gpt-6-luna`) |
| `JRP_JEV_CONCURRENCY` | no | concurrent Jev requests (default 12; a separate limiter holds 1,200 per minute) |
| `JRP_PROSE_CONCURRENCY` | no | concurrent prose-model calls (default 3) |
| `JRP_SLACK_WEBHOOK_URL` | no | a Slack Incoming Webhook that gets each run's result; see [scheduling.md](scheduling.md#notifications) |
| `JRP_NOTIFY_MACOS` | no | `1` shows each run's result in macOS Notification Center |
| `JRP_BIN` | no | the `jrp` the launchd wrapper starts (written by `jrp schedule install`); unset, the wrapper runs this checkout with uv |
| `JRP_SLACK_NOTIFY` | no | `1` sends each `jrp run`'s result to Slack as one message: `jrp run` with the claims per line; `jrp run DEGRADED` with one reason line per line when a line finished but not as a healthy run does (a failed prose draft, the writer's login refused, a section the rubric could not check, Jev failures on 5% or more of the (source, question) pairs, a failed fetch other than a skip for an unset key or a rate limit on a source asked without its optional key, the cost cap, a note with no claim and no Review, prose that cited no claim on the line's last two runs); `jrp run FAILED` when the run raised |
| `JRP_RUN_TIMEOUT_S` | no | limit of a scheduled `jrp run` in `scripts/launchd-jrp.sh`, in seconds the Mac is awake (default 3600 s; time asleep is not counted). Past it the run is killed with its process group, the notes it already wrote are still copied to the vault, and the wrapper notifies `jrp run TIMED OUT` |
| `JRP_WBR_TIMEOUT_S` | no | limit of Monday's `jrp wbr` in `scripts/launchd-jrp.sh`, in seconds awake (default 600 s). Past it the review is killed with its process group and the wrapper notifies `jrp wbr TIMED OUT`; a value that is not a number of seconds notifies `jrp wbr FAILED` and skips only the review. Either way the morning's notes are already in the vault and the job exits with the run's status |
| `JRP_WBR_DUE` | no (tests) | `1` or `0` decides whether the launchd wrapper runs the weekly review after this run; unset, it runs when `date +%u` is 1 (Monday) |
| `JRP_DRIFT_LIVE` | no | `1` lets `jrp drift` call Jev live. It applies to a drift run by hand; the weekly launchd drift job is stopped ([launchd/README.md](../launchd/README.md)) |
| `GITHUB_TOKEN` | no | raises GitHub search from 10 to 30 requests per minute (a fine-grained token with no permissions is enough) |
| `SEMANTIC_SCHOLAR_API_KEY` | no | recommendation net; without it the shared keyless quota may return 429 for the day (expected, so it is an operations line and not a `DEGRADED` reason; with the key set, a 429 is a reason) |
| `OPENALEX_API_KEY` | no | raises OpenAlex's daily budget from 1,000 credits ($0.10) to 10,000 ($1), and the default `openalex_daily_credits` cap from 400 to 4,000. The citation and exploration nets and the `arxiv:` keyword search all spend it |
| `HF_TOKEN` | no | raises the Hugging Face daily papers rate limit; without it a 429 from the shared keyless limit is expected (an operations line, not a `DEGRADED` reason; with the token set, a 429 is a reason). HF papers search in the keyword net sends no token |
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
target_repo = "~/projects/agent-knowledge-cycle"   # optional; only graph.jsonld is read

[tracks.memo]
name = "Agent memory"              # a line needs only a name
# id = "https://example.org/memo"  # optional: the line's @id as given

[tracks.jev]
name = "TypeSafe Jev"
daily = true                       # runs on every tick beside the rotated lines

[tracks.ans]
name = "Attention, Not Self"
arxiv_categories = ["q-bio.NC"]    # optional: this line's arXiv listing, instead of [nets]
# firehose = false                 # optional: no firehose request at all for this line
# web_time_range = "week"          # optional: this line's web: searches, recent results only

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

The firehose is the same for every line unless a line says otherwise in its own table:
`firehose = false` sends it no firehose request (neither HF daily papers nor the arXiv
listing), and `arxiv_categories` replaces `[nets] arxiv_categories` for its arXiv listing
(HF daily papers still come). Use them for a line whose literature is not in the global
categories: over its history the `ans` line (meditation, Buddhist psychology) passed the
prefilter with 0 of 1,070 arXiv listing items and 0 of 96 HF daily papers, each of them
screened against every open question.

`web_time_range` (`"day"`, `"week"`, `"month"` or `"year"`) makes a line's `web:` searches ask
Tavily for results of that window only, with each result's published date; other values stop
the run with the line named. Lines without it send their searches unchanged. A line that reads
feeds and sitemaps (`feed:` / `sitemap:` query lines) needs no setting: their window is the last
3 days, fixed in code.

A track's slug names its notes (`<date>_jrp_<slug>.md`), so `wbr` is reserved for the weekly
review's note: a config with `[tracks.wbr]` does not load, `jrp doctor` fails its config check
and `jrp run` stops.

Every line that is not `daily = true` takes its turn in the rotation; a line with `daily = true`
runs on every tick beside it. A line may point at a repository with a `[[tracks.<slug>.repos]]`
entry: if that directory holds a `graph.jsonld` (a JSON-LD file; the `name` and `alternateName` of
its `Concept` and `DefinedTerm` nodes become the line's vocabulary for screening and the prose) the
vocabulary is read from it. Otherwise the line's `name` is the only vocabulary.

## Store schema changes

Every command inspects the store first. Additive changes are rewritten in place and noted in the
operations block. Incompatible changes stop before reading or writing anything, naming the file:
`jrp migrate --dry-run` shows the plan and `jrp migrate` applies it, moving incompatible files to
`<store>/retired/<date>/` rather than deleting them. `jrp wbr` only reads the store: it reads an
additive file as if migrated, in memory, and leaves the file as it is; an incompatible file stops
it with the same one line and exit 2.

## The weekly review

`uv run jrp wbr [--week YYYY-Www] [--out DIR]` reads the store, `config.toml` and the question
files and writes two things: the note `<DIR>/<the Monday after the week>_jrp_wbr.md` (default
`DIR` = `<JRP_VAULT_DIR>/daily-research`, beside the daily notes) and one line appended to
`<JRP_STORE_DIR>/metrics/weekly.jsonl`. `--week` defaults to the last complete ISO week (on a
Monday, the week that just ended). It uses the same `JRP_STORE_DIR`, `JRP_QUESTIONS_DIR`,
`JRP_DAILY_RESEARCH_CONFIG` and `JRP_NOTE_LANG` as a run. Without `ANTHROPIC_API_KEY` it calls
no API, so it can be made again any number of times; each time appends another line to
`weekly.jsonl`. With the key set, the monitoring judge (Claude Opus 5.5 on the Claude API) reads a
sample of the week: up to 8 sections with prose, judged pass / fail against the fidelity checks of
`docs/prose-rubric.md` (`.en.md` / `.zh.md` for a note in English or Chinese; read from the
checkout, so an installed copy without `docs/` shows "not measured"), and up to 12 of the week's
O1 papers, each asked whether its claim moves the question forward. The sample is drawn from the
week's label, so the same week draws the same sections and papers. Each call is priced at the
Claude API's rates in `<JRP_STORE_DIR>/metrics/judge.jsonl`: a row reserving the most the call
can cost before it is sent, then a row with its price once it ends (a call cut off, or one that
got no answer, keeps the reserved amount). Two reviews at once take turns on
`metrics/judge.jsonl.lock` beside it. The judge stops at `JRP_MONITOR_WEEKLY_USD`, at a 429, at
spent credits or a refused key (none of them retried), and after 300 s, and the rest of the
sample shows as not measured with the reason. Its answers are
shown in the note only: no gate, threshold or run reads them. Making a week again with the key
set calls and pays again. What each number means is in
[how-it-works.md](how-it-works.md#the-weekly-review). On macOS the launchd wrapper
runs it every Monday after the morning's notes reach the vault, limited by `JRP_WBR_TIMEOUT_S`
([launchd/README.md](../launchd/README.md)); on Linux it is a second cron or systemd entry
([scheduling.md](scheduling.md#linux-cron-or-systemd)).
