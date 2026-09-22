# Research pipeline: code / Jev / Qwen explicit separation

grill-me interview 2026-09-22. Read this as the design packet; the interview log is
collapsed into decisions. External facts carry as-of dates (LLM field goes stale weekly).

## Context

The author wants a production-style AI workflow whose architecture is the research object:
deterministic code owns control flow, a decision model (TypeSafe Jev) owns bounded
judgment as narrow functions, a generation model (Qwen via DashScope API) writes text only
where text is truly needed. No ReAct / generic agent loop. Pydantic + Pydantic AI for
types, schemas, validation and minimal model integration. The workload is the existing
daily-research lines (the design of daily-research is explicitly NOT inherited). Deliverable
per run = a report the author reads in Obsidian. The long-run ambition, corrected mid-
interview: **move judgment currently done by LLMs (Claude today, Qwen tomorrow) into Jev**,
and turn the operating record (decision log, labels) into thresholds, regression tests and
proposed code rules. "Jev usage going down" is NOT the goal; generation tokens going down
while Jev question count goes up is.

## Decisions (all resolved in the interview)

### Unit of work, inputs, state

1. **One run = one research line → one report.** launchd ticks daily; code picks the next
   **3 lines in rotation** (cursor in the store). Each line-run has its own cost/call
   meters, retry, and report.
2. **Lines come from the existing daily-research config** (`~/MyAI_Lab/daily-research/
   config.toml`; read at build time). Each line's `graph.jsonld` (found under
   `~/MyAI_Lab/<line>/graph.jsonld`) is **read-only concept vocabulary** for that line.
3. **Pipeline state lives in a pipeline-owned store**, not in graph.jsonld
   (skills/jsonld-knowledge-graph/SKILL.md:36,102 — graph is concept-layer only,
   hand-written, volatile state excluded). Store = JSON-LD content graph with `@id`
   aligned to the line graph so triples merge; a derived BM25/embedding index over
   claims for candidate retrieval. Promotion into graph.jsonld (new Concept /
   ExternalReference) = pipeline proposes a diff, the author applies.
4. **Collection layer = typed source adapters fixed in code per line** (arXiv API, HF
   papers, GitHub search, web search API). The model never chooses where to search.
   Built 2026-09-22: arxiv / hf_papers / github / web_search (Tavily chosen by the build
   session as the only candidate whose terms do not forbid storing results — **author
   decision pending before the first live recording**; needs a Tavily key).
   X = deferred adapter; first candidate path is xAI's `x_search` server tool
   ($5/1k posts + $10/1k profiles, changed 2026-09-21), not a separate X API contract.

### Judgment / generation map (Jev-max, Qwen 2 sites)

Every Jev use = a bundle of narrow questions on one `state` in one request (13 questions
= 0.27s, ~12× cheaper than separate calls); items run in parallel client-side.
Thresholds start at vendor rounding values and are refit on the author's labels.

| Function | Layer | Shape |
|---|---|---|
| query candidates | Qwen (flash) | N candidate queries per adapter from line vocabulary, Pydantic list |
| query selection | Jev | Score per candidate (expected yield for this line); code keeps top-k |
| relevance triage | Jev | Nouls{relevant to line, contains evidence, prompt injection} per fetched **source** (whole text; built 2026-09-22 — units are cut only from sources that passed triage) |
| claim detection | Jev | code splits text into sentence/paragraph units → Noul{states a checkable claim} + Noul{relevant}; **claim = unit verbatim**, so quote-matching is trivially true |
| novelty | Jev | code pre-pass → candidate pairs → per pair Score{unrelated / related-or-extends / same claim} + Nouls{contradicts, same_source} (vendor entity_alignment recipe) |
| source support | Jev | code string-matches span first → Choice{supports, contradicts, says_nothing} (vendor citation_check recipe) |
| source trust | Jev | Score over concrete-situation levels |
| ordering in report | Jev | Score (importance) per accepted claim |
| report prose | Qwen (max) | one call over accepted claims; Japanese |
| report rubric eval | Jev | **per claim-in-context**: Score on each rubric axis (grounded in accepted source / relevant to line / novel vs store / actionable for the author) + **per report**: Score(readability), Score(coherence), Noul{contains unsupported statement}. Low → one rewrite → still low → template report. Rubric axes are concrete-situation levels, not abstract degrees (vendor guidance) |
| everything else | code | fetch, hashing/dedup, dates/ordering/counting, thresholds, store writes, template rendering, cost caps, retries |

Vendor jaggedness kept out of Jev: counting, dates, numeric proximity, large irrelevant
state (filter state in code), adversarial text (treat as data).

### Labels, reduction, metrics

5. **Two label sources, combined.** (a) **Gold = the author's ⭕❌**: each claim carries
   a checkbox; ticks made while reading are harvested by the next run's first stage
   (code) from the vault file into the decision log. Encoding (one line per claim):
   `- [x]` = ⭕ correct, `- [-]` = ❌ incorrect, `- [ ]` = no gold. Anything else on the
   line is ignored by the harvester. (b) **Dense =
   Jev rubric scores** on the same claim (the rubric-eval row above), recorded for every
   claim every day. Combination rules:
   - Jev rubric is **validated against gold**: per rubric axis, agreement with ⭕❌ is a
     tracked number; an axis whose agreement stays below a floor is not trusted for fit.
   - Fit (reduction ①) uses gold as target and rubric scores + raw judgment
     probabilities as features (vendor autoresearch recipe: Score/Noul as ML features).
   - Rubric scores act as **silver labels** for unticked claims only for axes that
     passed the agreement floor, at lower weight than gold.
   - Rubric also drives the daily quality line in the operations section, so quality
     is a number even on days with zero ticks.
6. **Reduction forms in v1**: ① threshold/weight fit on labels (auto; jevcal-style —
   third-party result: single question 62.6% → 5 narrow questions with fitted weights
   95.0%), ② each ticked claim auto-becomes a pydantic-evals Case (auto), ③ rule
   promotion = **proposal only** (code detects a Jev question predictable from a
   code-computable feature over ≥N labels at ≥X% agreement, prints a candidate rule in
   the report's operations section; author applies), ④ local decision model = deferred
   until a label-count threshold. As built 2026-09-23: ③ counts **labeled decisions**
   (N=30, X=0.95, config); ① writes a threshold-diff proposal file, never applies;
   ② exports pydantic-evals YAML that pytest replays.
7. **Primary success metric = label fill rate** (ticked / claims per report): proof the
   reports keep being read. Secondary meters per run: generation tokens (↓ wanted), Jev
   question count (↑ wanted), Claude calls (must be 0), ticked-correct rate, cost, run
   reliability, rubric scores per axis, rubric-vs-gold agreement per axis.

### Failure policy, testing

8. Jev timeout/error → item to an "unjudged" section (no fail-open into the body).
   Qwen query candidates fail validation N times → that adapter runs this line-run on
   code-built fallback queries (line concept names / alternateName), flagged in the
   operations section. Qwen synthesis fails → template report always written. Cost cap →
   partial report. (Corrected 2026-09-22 by the build session: Qwen does not extract —
   units are cut by code and judged by Jev — so there is no "unextracted" state.) Idempotent: stage outputs keyed by content hash; re-run skips done stages.
   Every report ends with an operations section (numbers above).
9. **Regression = record/replay cassettes** for adapter fetches and Jev/Qwen responses
   (input hash → response). Built 2026-09-22 as one hand-rolled httpx2 transport
   (`cassette.py`) injected into adapters, typesafe-sdk and pydantic-ai alike; replay is
   the default, recording only with `JRP_CASSETTE_RECORD=1`; headers never stored.
   verify.sh runs offline, no API keys. Weekly drift job replays
   cassette inputs against live Jev and reports probability deltas (model-update
   detector). Pin `jev-1.13.0` (aliases drift; no deprecation policy published).

### Providers, placement, cutover

10. **Qwen via DashScope**, intl endpoint `https://dashscope-intl.aliyuncs.com/
    compatible-mode/v1` (keys are region-bound). Model ids as-of 2026-09-22: no `qwen4-*`
    exists; use `qwen3.8-flash` ($0.15/$0.47 per Mtok, 1M ctx) for queries and
    `qwen3.8-max` ($2/$6) for Japanese prose. Structured output via json_schema strict
    (supported on 3.7/3.8); with Pydantic AI use `NativeOutput` and also name fields in
    instructions. Avoid legacy `qwen-max` alias (32k ctx).
11. **Grok is not the default**: X Premium covers neither xAI API nor X API (both prepaid
    credits, primary sources as-of 2026-09-22). Generation provider is config, swappable
    to Pydantic AI `XaiModel` if the author buys credits.
12. **Reports go to the Obsidian vault as today**, same folder, mixed in (author decision
    2026-09-22): `<vault>/daily-research/YYYY-MM-DD_jrp_<line-slug>.md`, vault =
    `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault`, path from env
    `JRP_VAULT_DIR`. Frontmatter keeps the existing keys (date / category: jrp / kind /
    tags / topic) plus `line` and `jrp_report`. Body: H1 → prose → `## Claims` (one line
    per claim: `- [ ] <verbatim> — [source](url) <!-- jrp:claim:<id> -->`) → `## 未判定` →
    `## 運用`. The harvester reads only the line head (`[x]`/`[-]`/`[ ]`) and the comment
    id; the rest of the file is the author's to edit.
13. **New repo** `~/MyAI_Lab/jev-research-pipeline`, uv + Python ≥3.12,
    `verify-bootstrap` first (done 2026-09-22; gate record in `.claude/verify.md`). **Parallel run** with the existing
    daily-research; the author stops the old one when the new fill rate exceeds the old.

### As built (2026-09-23, steps 7–10)

- `jrp run | fit | export-cases | drift` CLI. Env from `~/.config/jrp/env` via
  `scripts/launchd-jrp.sh`; required: `JRP_VAULT_DIR`, `JRP_STORE_DIR`, `TYPESAFE_API_KEY`,
  `DASHSCOPE_API_KEY`, `JRP_COST_CAP_USD`, `JRP_JEV_USD_PER_QUESTION` (unset price = 0,
  shown as "単価未設定"). Optional: `TAVILY_API_KEY`, `GITHUB_TOKEN`, `JRP_SLACK_NOTIFY=1`,
  `JRP_DRIFT_LIVE=1`, `JRP_CASSETTE_RECORD=1`.
- Lines and vocabulary come from `~/MyAI_Lab/daily-research/config.toml` tracks + each
  repo's graph.jsonld (read-only); tracks without a graph (desire, edge) use the track
  name only.
- launchd: `launchd/com.shimo4228.jrp.{run,drift}.plist` (07:00 daily / Mon 07:30), not
  loaded by the build.
- Same-day re-run carries the author's ticks over; harvester withdraws Labels for `[ ]`.
- Rubric unjudged → template (no unverifiable prose). Cassettes now keep request bodies
  (for drift), never headers.

### Observability (author decision 2026-09-23)

OpenTelemetry, not a hand-rolled tracer and not Logfire cloud: pydantic-ai's built-in
instrumentation for the Qwen sites, explicit spans around each Jev function and each
stage, OTLP export configured only through the standard `OTEL_*` env vars (no endpoint
= no-op). The store + operations section stay the source of truth for the research
meters; OTel is the live-debugging channel. Backend = a local, Docker-free OTLP viewer
picked by search-first and documented in the README.

### First live run (2026-09-22 UTC / 09-23 JST) — findings

- End to end works: Jev + Qwen live, 3 notes written, cost $0.02 total.
- akc: 0 claims — every Qwen query scored 0.16–0.38 on expected yield, floor 0.5 rejected
  all → nothing fetched. Fix: when nothing clears the floor, fall back to top-k and flag.
- Prose never rendered: qwen3.8-max over 37 claims exceeds the 30s HTTP timeout
  (measured 92s incl. retries → ModelAPIError). Fix: long timeout for the prose call and
  surface the failure reason in the operations section.
- run_date used UTC; notes dated 09-22 at 06:31 JST. Fix: local date.
- github search 403 without token; arxiv 406 (Accept header). Fix adapters; document
  `GITHUB_TOKEN`.
- Note escaping over-broad (`\(`, `\$`, `&lt;`); restrict to Obsidian-active syntax.

### Non-goals (explicit)

ReAct / supervisor loops; local models; Grok in v1; X adapter in v1; writing into
graph.jsonld; automatic rule application; local decision model; Claude at runtime;
LLM-as-judge with another LLM as the truth source.

## Libraries (verified as-of 2026-09-22)

- `typesafe-sdk`: Pydantic-native; `system_one(state, questions, response_model=…)`;
  `AsyncTypeSafeClient`; `RetryPolicy`; default timeout 10s; `TYPESAFE_API_KEY`.
- `pydantic-ai` 2.47.0: `AlibabaProvider` (`DASHSCOPE_API_KEY`), `Agent(output_type=…)`
  with no tools = one typed request + `retries={'output': N}`; `pydantic_ai.direct.
  model_request` for no-validation single calls.
- `pydantic-evals`: `Dataset`/`Case` to YAML, pytest integration — the golden layer.
- Borrowed from open_deep_research (as-of 2026-09-22): brief → per-topic research →
  compress → single report call; `eval_groundedness` = extract claims → verify each.
  Not borrowed: supervisor/researcher loops.

## Build sequence (for implementation-chain, feat chain)

1. Repo bootstrap: uv project, `verify-bootstrap` → `.claude/verify.sh` (ruff, pyright
   strict, pytest, bandit, deptry). Golden/cassette dir layout.
2. Types first (done 2026-09-22, `src/jev_research_pipeline/model/`): Line,
   QueryCandidate, SourceItem, Unit, Claim, Judgment (per Jev function, raw
   probabilities), Decision, Label, Report; JSON-LD serialization with content-derived
   `@id` under STORE_NS, Line `@id` = the line graph's IRI byte-identical.
   Cassette/golden layout deferred to step 4 (mechanism chosen there).
3. Store + index: JSON-LD content graph on disk, BM25 (rank_bm25 or sqlite FTS5) derived
   index, rotation cursor, idempotent stage cache by content hash.
4. Adapters: one typed adapter per source with cassette recording; start with arXiv + HF
   papers (both have stable APIs), then GitHub, then web search API.
5. Jev functions: one module per function, each = (state builder, question bundle,
   threshold config, Pydantic answer model). Cassette-backed tests per function.
6. Qwen sites: query candidates (flash, NativeOutput list), report prose (max).
7. Report renderer: human prose + machine-readable checkbox block; operations section.
   Label harvester (reads vault file, diffs checkbox state).
8. Rubric eval module (per claim + per report) with rewrite/template ladder; agreement
   tracker rubric-vs-gold per axis.
9. Reduction ①②: fit script over decision log (gold target; rubric + raw probabilities
   as features; validated-axis silver at lower weight); label→Case exporter.
   ③ proposal detector (feature agreement scan) printing into operations section.
10. launchd plist (3-line rotation), weekly drift job, Slack one-line notify.
11. Parallel-run period; cutover by fill rate.

## Verification

- `.claude/verify.sh` green offline (cassette replay; no keys).
- One live smoke run per line with cost cap, confirming: report file appears in the vault
  subfolder with checkboxes; operations section shows Jev question count, generation
  tokens, Claude calls = 0, self-eval scores.
- Tick a few checkboxes by hand → next run's decision log shows labels → fit script
  changes at least one threshold → the ticked claims appear as pydantic-evals Cases and
  pass.
- Drift job produces a delta table against the cassette baseline.

## Routing (grill-me output)

ADR candidates in the new repo (hard to reverse + surprising + real trade-off):
- graph.jsonld read-only + separate JSON-LD pipeline store (vs extending the graph vocab).
- Judgment decomposition into narrow Jev questions with label-fitted thresholds; claim =
  verbatim unit (vs LLM paraphrase extraction).
- Report checkboxes as the sole gold-label source (vs LLM silver labels).
Glossary terms pinned: "line" (ResearchLine node + its adapters + its store partition),
"unit" (verbatim text span that can become a claim), "reduction" (label-driven move of
judgment from generation model → Jev → code).
