# Research pipeline: code / Jev / generation model explicit separation

grill-me interview 2026-09-22. Read this as the design packet; the interview log is
collapsed into decisions. External facts carry as-of dates (LLM field goes stale weekly).

## Context

The author wants a production-style AI workflow whose architecture is the research object:
deterministic code owns control flow, a decision model (TypeSafe Jev) owns bounded
judgment as narrow functions, a generation model (Qwen via DashScope API at the interview; GPT-5.6
Sol on the Codex subscription since 2026-09-24, "Prose model" below) writes text only
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

10. **Qwen via DashScope** (the prose moved to GPT-5.6 Sol on the Codex subscription on
    2026-09-24; DashScope stays a backend, "Prose model"), intl endpoint `https://dashscope-intl.aliyuncs.com/
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
- launchd: `launchd/com.shimo4228.jrp.{run,drift}.plist` (05:00 daily / Mon 05:30), not
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

### Discovery = several code-owned nets, Jev screens (author decision 2026-09-23)

Keyword search alone is exploitation and converges (daily-research's Opus explorer hit
37% single-theme in 30 days, ADR-0001 there). Evidence as-of 2026-09-23: API keyword
search alone <20% recall, + citation traversal >80% (arXiv 2605.29234, no ablation);
database search + snowballing +30% (Wohlin 2022); agentic LLM search independently
measured ~40% recall (Elicit, Cochrane 2025). Recommenders learn from thumbs (Scholar
Inbox: per-user classifier on up/down votes + random negatives against collapse).
No production system separates exploration and reports diversity — built here.

Nets, in code-fixed order, all keyless:
1. firehose — arXiv new listings (fixed categories) + HF daily → Jev relevance triage.
2. recommendations — Semantic Scholar `POST /recommendations/v1/papers` with positives =
   ⭕ + accepted claims' papers, negatives = ❌ + random negatives.
3. forward citations — OpenAlex `filter=cites:` on accepted papers (1 credit/call,
   1000/day keyless). The filter takes only a work id (`W…`); a paper known by DOI is
   resolved first with the free singleton `works/doi:<doi>` (measured 2026-09-25: a
   `cites:doi:…` filter is a 400).
4. keyword (existing) — demoted to fourth.
5. exploration budget — fixed share of the per-line budget seeded from neighbouring
   OpenAlex topics; new Jev Noul `bridges_line` (connects the line's question to a
   concept outside its vocabulary); report gets a 「橋渡し」 section.
6. meters — accepted-claim share per net; cluster count over OpenAlex topic ids of
   accepted papers (falling count = convergence alarm); per-net new-accept rate with a
   convergence stop (Undermind's f = 1 − e^(−n/τ)).
Never measure recall against human citation lists; vendor recall claims are unreliable.
Review-when: OpenAlex credit pricing or S2 keyless pool changes; an ablation separating
query generation from snowballing is published.

### Second live run (2026-09-23 JST) — findings

- Fixed and confirmed: prose renders (40.7s for 7 claims), local-date filenames, floor
  fallback engaged on every adapter, github 403 gone with a token.
- Query contamination: qwen3.8-flash NativeOutput intermittently leaks chat-template
  tokens (`<|start|>`, `<|end|>`, `,`, `]`) into query strings → arXiv 406. ToolOutput is
  rejected by DashScope (tool_choice 400); PromptedOutput was clean in one probe. Fix:
  strict Pydantic validation of query strings + output retries + deterministic adapter
  guard; keep NativeOutput and meter its failure rate before switching.
- Vocabulary loader misses prefixed types (`ans:Concept`, `schema:DefinedTerm`) → the
  ans line had one vocabulary term. Fix: match type suffix; include DefinedTerm.
- Homebrew now refuses untrusted taps: `brew trust ctrlspice/otel-desktop-viewer` first.

### Report redesign (author verdict 2026-09-23: prose unreadable, claim wall unusable)

Supersedes the reading-surface parts of decisions 5 and 12 (label encoding and file
location stay). Reasons: prose was a paraphrase of claims because Qwen got no line
context and was forbidden inference; 37 checkbox lines per note is a wall that lowers
the primary metric (fill rate).
1. **Prose input = line context**: ResearchLine description, recent ADR titles,
   DefinedTerm vocabulary, and the day's top claims (by Jev `actionable` / `bridges_line`).
   Task: "what today's findings advance or overturn for this line". Inference is allowed
   but must sit in its own paragraph(s) marked as the pipeline's inference; rubric
   `grounded` applies to the evidence paragraphs only.
2. **Label granularity = source**: the note lists 3–7 sources, one line each (title +
   one-sentence gist + checkbox + comment id `jrp:source:<id>`). ⭕❌ on a source
   propagates to its accepted claims for the fit layer. Claim-level Jev judgments are
   still stored.
3. **Claims fold away**: the per-claim list moves into a collapsed Obsidian callout
   (`> [!note]- Claims`), still carrying claim ids so claim-level ticks remain possible.
4. **Prose covers only the selected top claims**; the rest stay in the fold.

### Question-centric redesign (author verdict 2026-09-23; supersedes the judgment map's
anchoring, decision 5's label unit, decision 12's body, and the Report redesign above)

Diagnosis: the knowledge unit was a bag of verbatim sentences, so every report was a
list of sentences, and every Jev question lacked a referent ("relevant to the line's
vocabulary" passes any paper that shares a term; "checkable claim" passes "experiments
ran on a Mac Studio"; rubric grounded 0.99 / novel 1.00 were tautologies). Research
output is question → evidence → how the answer moved. The **Question** is the unit.

- **Question node** per line: text, status {open, answered, dropped}, opened_at, and
  the running evidence set (accepted claims). 3–5 open per line. Seeded from the
  ResearchLine description + ADR Review-when lines (code) phrased by Qwen (flash) and
  scored by Jev (Noul open_for_line, Score impact_on_stance); the author confirms.
  Questions change weekly, not daily. Author-editable file `questions/<slug>.md` in the
  repo; the daily note proposes new questions with checkboxes (tick = adopt → harvester
  appends to the file). "Changed vantage point" candidate = one per proposal round.
- **Every Jev judgment is anchored on (item, Question)**: source triage Noul
  bears_on(source, Q) (+ injection per source); claim detection Choice{advances,
  contradicts, unrelated}(unit, Q) — a claim is a unit that advances or contradicts some
  open Q; novelty Score{same as known / adds detail / changes answer}(claim, Q,
  evidence set); question movement per (Q, day) Score{none / new evidence same answer /
  answer changed}; source trust unchanged; query candidates are generated per Question
  (Qwen flash) and scored per Question (Jev).
- **Report = per open question that moved today**: `### Q` → 今日の変化 (evidence
  paragraphs + one marked inference paragraph) → 証拠 (source lines: title + gist +
  link). One checkbox per question-day (`jrp:qday:<id>`): ⭕ = this movement was worth
  reading, ❌ = not. Then 「問いの候補」 (checkbox = adopt), 「橋渡し」 (exploration
  nets), folded Claims, 未判定, 運用. Fill rate is counted over question-days.
- **Labels propagate**: a question-day tick propagates to the claims and sources cited
  under it; fit uses those. rubric_report per question section, `grounded` on evidence
  paragraphs only.
- Discovery nets (section above) unchanged; they feed the per-question screens.
Review-when: fill rate after two weeks; if questions stagnate (no proposals adopted in
a month) revisit the proposal mechanism.

### Search-first synthesis (2026-09-23) — what the question-centric build adopts

Sources read: LangChain open_deep_research blog + eval post; Anthropic multi-agent
research post; STORM / Co-STORM; GPT Researcher; Cochrane LSR guidance 2019 + a Cochrane
living review 2024; SAFE (Boetje & van de Schoot 2024); stopping-method benchmark (Repke
2026); ASReview insights; jev-paper-screener, paper-radar-jev, jev-papers, jev-search,
jev-reranker, jevlogs; TypeSafe classifying_rag_passages cookbook; awesome-jev.
No OSS combines standing pipeline + per-question judgments + stored labels + separate
prose model; closest are jev-paper-screener (batch) and paper-radar-jev (one profile).

Adopted into the Question-centric design:
- **Question fields** (jev-paper-screener): title, brief, method_constraints,
  evidence_constraints, negative_topics (paper-radar-jev), canary papers (SAFE: known
  key papers that must rank high), status, opened_at, version, retire rule (Cochrane:
  no longer a priority / certainty reached / no new research), append-only per-question
  「What's New」 log.
- **Screening per (item, Q)**: hard gates as Nouls (on_topic, method_transferable,
  evidence_compatible, injection) → weighted Score dimensions → code routes to Keep /
  Review / Drop / Incomplete (no abstract). Review = borderline OR Jev confidence < 0.9
  (jev-papers: ≥0.9 → 98% agreement with an LLM judge, <0.9 → 63%). Contradictions go
  to a separate block (cookbook). Skip only when every condition holds; store everything
  (jevlogs).
- **Per-run question outcome** (Cochrane): {no new evidence, new but unlikely to move,
  likely to move} = question_movement Score levels; the author's ⭕❌ on a question-day is
  the "likely to change conclusions" editorial judgment.
- **Evals** (Anthropic, LangChain): start from ~20 real (item, Q) cases; grade the
  question-day end state; single-step golden cases replayed from cassettes; citation
  binding is deterministic — code validates every [n] Qwen writes and attaches links.
- **Meters**: Time-to-Discovery per ⭕ paper (ASReview), net share, topic cluster count;
  "n consecutive irrelevant" is NOT a convergence signal (Repke 2026); convergence
  claims need an author-audited random sample of rejects (CMH hypergeometric bound).
- **Threshold refit**: evaluate jevcal (awesome-jev) before writing our own fit; refit
  only when held-out CI stays within a pre-set band (Cochrane RCT classifier practice).
Not adopted: gold-report LLM judges (RACE), agent loops, keyed neural search, α-nDCG
(needs sub-aspects per question — revisit later).

### Jev through pydantic-ai (author-surfaced 2026-09-23; docs verified same day)

pydantic-ai 2.47 exposes Jev as a model: `Agent('typesafe:jev-1.13.0', output_type=M)`;
fields map to primitives (bool → Noul, Literal/Enum → Choice, docstring IntEnum → Score,
float ge/le → probability), all fields of one model go out in one request, nested
models expand as `outer.inner`, raw distributions in `provider_details['probabilities']`
/ `['scores']` / `['confidence']`, response carries the versioned model id.
Decision: every Jev function = one Pydantic output model called through this model; the
hand-rolled SDK boundary (`jev/_sdk.py`, bundle conversion in `jev/core.py`) is removed.
Same abstraction for both models; questions live on the types. Judgments still store the
raw distributions. Known trade-off: Noul true/false criteria collapse into one
`Field(description)`. Review-when: pydantic-ai's typesafe model loses distribution access
or Score support.

### Evaluation and self-improvement: deferred to operation (author decision 2026-09-23)

Pilot first. The label/fit design (decision 5-7, the reduction forms, fill rate as the
primary metric) is NOT extended further before a working pilot runs. Recorded candidate
for later: **used rate** — share of surfaced sources that appear within 30 days in any
line's graph.jsonld / ADR / vault note (an objective, zero-effort delayed label) — with
canary papers and cross-net agreement as weak supervision, ⭕❌ demoted to optional gold,
Review section kept. Decide after the pilot has run for a few weeks.

### jevcal (search-first 2026-09-23) — NOT-ADOPT

Two packages share the name. `pip install jevcal` fetches aakgna/jevcal 0.2.0 (2026-09-21),
which logs decisions and measures calibration (ECE/Brier) and explicitly does no threshold
selection. The one that does per-question thresholds — abhixhek/jevcal, MIT, Python ≥3.10 —
is git-install only, five days old, has no `py.typed`, and its own README says not to expect
it to hold under ~100 labeled rows per question, which is exactly this pipeline's regime.
Verdict: keep the hand-rolled grid search; steal the two ideas that matter at our N —
split fit/verify and report the held-out number, and select on the Wilson lower bound of
accepted accuracy rather than the point estimate (proposed, not yet implemented).
Review-when: abhixhek/jevcal ships to PyPI with `py.typed` and a library API that takes
raw (scores, labels, group_id) without a provider key, or per-function label counts cross
~100. Alternatives if probability calibration (not thresholds) is ever wanted: netcal
1.4.0, mapie 1.5.0, sklearn.calibration.

### Discovery endpoints (search-first 2026-09-23, measured)

- arXiv firehose = `rss.arxiv.org/rss/<cat>+<cat>` (full abstracts, `arxiv:announce_type`
  new/cross/replace, description prefixed "arXiv:<id>vN Announce Type:", empty at weekends).
  When the listing overflows `firehose_max` (~541 new items on 2026-09-26 against a cap of
  300; the prefilter then rejects ~97% of arXiv items), what is kept is ranked by BM25
  (bm25s, no stemmer) of title + abstract against the line's English query text — the open
  questions' `arxiv:` / `hf:` / `github:` lines and the line vocabulary; `web:` lines,
  headings and briefs are Japanese and would match nothing. Ties and an empty query keep
  feed order; HF daily keeps its place ahead.
- **arXiv API no longer used (as-of 2026-09-26).** `export.arxiv.org` answers 406 to every
  Python client (httpx2 and urllib) since 2026-09-24 while curl gets 200, even for a query
  no cache held; other projects report the same 406 since 2026-09-13. The author decided
  against a client workaround (it would be bot-detection evasion). `arxiv:` keyword queries
  go to OpenAlex `works?search=<words>&filter=primary_location.source.id:S4306400194`
  (newest first, 20 per query, ~3 days behind the announcement, 10 credits each, same daily
  cap as the citation net); the SourceItem keeps kind `arxiv` and the firehose's URL form
  `https://arxiv.org/abs/<id>` from the `10.48550/arxiv.<id>` DOI, text = the reconstructed
  `abstract_inverted_index`. An arXiv canary is the free singleton
  `works/doi:10.48550/arXiv.<id>` (404 = not indexed yet, one operations line). Removed with
  it: the urllib host routing, the 406 resends, the per-line `arxiv_keyword_max` cap and the
  406 quiet branch. Review-when: export.arxiv.org answers 200 to httpx2 again, or arXiv names
  a sanctioned client path.
- HF daily papers = `huggingface.co/api/daily_papers?date=&limit=` — live, keyless,
  undocumented; only `date` and `limit` verified, so the field set needs a golden test.
- Semantic Scholar keyless is a globally shared pool: a single cold request answered 429
  (measured). Plan for a key or treat the net as best-effort with a hard give-up.
- OpenAlex: `mailto=` no longer buys a polite pool; keyless = 1,000 credits = $0.10/day,
  with a key 10,000 = $1/day (measured 2026-09-26; our default cap 400 keyless, 4,000 keyed),
  a filtered list is 1 credit, a `search=` is 10, singleton lookups are free, reset at
  midnight UTC. `per_page` max is 100. There is no arXiv id filter — an arXiv paper is
  addressed through its DataCite DOI (10.48550, ~2022 onward), and the preprint and the
  journal version are separate works. `docs.openalex.org` now 301s to `help.openalex.org`.

### Pilot mandate (author decision 2026-09-23) — build iterates until these pass

Machine-checkable necessary conditions per 3-line run; the author's reading is the
sufficient condition. (1) 3 lines ≤ 5 min, cost ≤ $0.30; (2) note ≤ 12 KB, Review ≤ 10,
橋渡し ≤ 5, unjudged < 5% of pairs; (3) prose for every question with a Keep, all [n]
resolve; (4) obviously off-topic papers Drop, jev canaries Keep; (5) no adapter failure
lines except web_search skip; (6) no stack traces; (7) a fresh-context Opus judge (not the implementer) reads the
three final notes against a six-axis rubric and returns Publishable / Fix / Rewrite,
≥2 of 3 Publishable to pass (author decision: Opus may judge 「まとも」). Iterate in a
scratch vault/store;
write the real vault once at the end. Stop at 8 live runs / $3 / 3 h and report.
First pilot run measured: akc note 283 KB, 20,573 Jev questions, $0.415, bridges
accepted 2,509/2,570 pairs, unjudged routed to Review, HF date must be ≤ yesterday UTC,
arXiv 406 only from httpx2 (curl 200 with identical URL/headers).

### Throughput and store migration (as built 2026-09-23, judge-requested)

Judge measured 15-20 min for 3 lines: every (source, question) Jev call awaited the one
before it. Built, design unchanged (questions, nets, report format as above):
- **Within a stage everything independent is in flight at once**: Jev under
  `JRP_JEV_CONCURRENCY` (12), Qwen (query candidates, per-question prose ladder) under
  `JRP_PROSE_CONCURRENCY` (3); stages stay sequential. Cost cap read after a slot is
  taken; JevClient's RequestPacer holds 1,200 requests per sliding minute (published
  limit, as-of 2026-09-23). Results applied in input order — a test pins that concurrency
  1 and 12 write the same note and store bytes. StoredJev joins an identical in-flight
  request (same judgment @id), which a sequential run found in the store.
- **Screening is batched** (switched off the same day: the slot bleed check agreed on 11/20
  routes; batch size is 1 — see "Pilot iteration"): one request per (question, ≤8 sources, estimated state ≤24k
  tokens; limit 32k state + longest question, 64k per request). Nested slots `sN.<field>`
  with each question rewritten to name `sources.sN`; still one Judgment per (source,
  question), state hash = the single-request state; ask `question_screening@v1_batch`
  (a batch of one = the plain v1 request). A batch refused for its content (4xx other
  than 408/429, malformed answer) is bisected until the bad source stands alone.
  Unverified live: whether answers bleed between slots — compare batched vs single on a
  sample before trusting the Review band.
- **Fetch and triage overlap**: triage starts on each net's sources as they arrive while
  later nets sit out their ToU gap. Found and fixed on the way: the pacing gap was kept
  per Adapter object, and the run builds one per keyword query, so arXiv requests went
  out back to back; the gap is now process-wide per adapter kind.
- **Store schema**: every command first inspects the store. Additive (@context a strict
  subset, shared terms unchanged, every node valid) is rewritten in place; anything else
  stops with one line naming the file. `jrp migrate [--dry-run]` rewrites additive files
  and moves incompatible ones to `<store>/retired/<date>/`.
- **Packet discrepancy**: Jev is priced per input token ($0.042/Mtok, output free —
  docs.typesafe.ai models, as-of 2026-09-23), but the cost meter multiplies
  `JRP_JEV_USD_PER_QUESTION` by the question count. Batching changes tokens per question
  (shared state sent once), so a per-question price calibrated on single requests now
  over-counts. Not changed here (meter design is the author's); Review-when: the first
  live batched run's usage.input_tokens is in hand.

### Pilot iteration — thresholds changed (2026-09-23, evidence in docs/pilot-log.md)

- question_screening min_certainty 0.9 → 0.5, read on the three placing Scores only (run 1: no Keep possible).
- question_screening: a score ≥ keep + review_band (0.7) is Keep whatever the certainty; certainty only decides near the cut (run 7: canary at 0.87 sent to Review).
- question_screening method_transferable / evidence_compatible gates 0.5 → 0.3 (run 2: "cannot tell" dropped).
- question_screening bridges_line 0.6 → 0.8, reworded to "would change the answer"; note shows ≤ 3 per question, ≤ 5 per line.
- question_prefilter (new) on_topic 0.5 per (source, question) before the full bundle and before triage.
- Review ≤ 10 per note (nearest the cut first); a Jev failure goes to 未判定, not Review.
- firehose ≤ 300 sources per line-run (`[nets] firehose_max`); HF daily before the arXiv listing.
- keyword net budget 6 → 12 (run 4: two lines with nothing on topic).
- claims per question section ≤ 8, ≤ 2 per source (run 3: 24.6 KB note); evidence gist 160 → 120 chars.
- claims per note ≤ 9, spread over the questions with claims (≤ 5 / 4 / 3 / 2 each); a note over 12,000 B drops proposals, then Review from the far end, one 運用 line (run 10: 16.4 KB).
- batch size 8 → 1 (slot bleed: 11/20 route agreement, bar 90%).
- Qwen enable_thinking off everywhere (measured 2–3× faster; the 122 s prose was thinking).
- question proposals timeout 30 s → 120 s.
- rubric_report claim_fidelity (new axis, one Noul per evidence paragraph): p ≥ 0.6 that a paragraph exceeds the claims it cites → one rewrite with a fidelity feedback → template (final-run judge, 2026-09-23).
- Jev transient failure (timeout, connection, 408/429/5xx): one retry after 2 s, counted in 運用.
- condition 1 relaxed: a tick (3 rotated lines + daily) ≤ 10 min (author, 2026-09-23 15:00).
- prose (qwen3.8-max) thinks again (`JRP_PROSE_THINKING=always`), timeout 300 → 900 s (≈ 1.8x the slowest draft seen, 496 s under contention; a draft past ~7 min breaks the 10-min tick anyway): blind A/B on 7 question-days, thinking won 6/7 and had no fidelity flag (docs/pilot-log.md). The structured-output site stays without thinking.
- FLASH site model qwen3.8-flash → deepseek-v4.1-flash (qwen3.8-flash free quota spent), output mode NativeOutput strict → PromptedOutput (deepseek answers 400 "response_format type is unavailable" to json_schema, though its docs list it; measured 2026-09-23). Prose (qwen3.8-max) is free text and was never schema-bound.
- keyword/arxiv 429: an informational line, not a failure line (arXiv search waits for the next day). Superseded 2026-09-26: `arxiv:` search is OpenAlex now, and a 429 there is a failure line plus a quiet line for the whole OpenAlex pool, like any other source.
- daily tracks (`daily = true`, e.g. jev) run on every tick beside the 3 rotated lines; the lines of a tick run side by side under one shared Jev rate window.
- arXiv export went through urllib (httpx2 alone got 406) until 2026-09-26, when the arXiv API was dropped altogether ("Discovery endpoints"); canaries are probed by URL every run (GitHub README / arXiv paper via OpenAlex / page), one operations line each.

### Authored queries (author decision 2026-09-23)

Supersedes the "query candidates" / "query selection" rows of the judgment map for every
question that carries query lines; those rows remain the fallback for a question without them.
Evidence from the real notes of 2026-09-23: query selection ended in floor fallback on nearly
every line and adapter (no candidate cleared the floor, so it only took the top-k), and the
Qwen query site was the source of the template-token contamination, the free-quota switch to
deepseek-v4.1-flash and its json_schema 400 — while the keyword net still carried most accepts
(the recommendation and citation nets need kept papers first).
- Queries are written **with the question**, at authoring time: `- arxiv:` / `- github:` /
  `- hf:` / `- web:` lines in `questions/<slug>.md`, English, one per line. Written by the
  author or by Claude in the author's session — authoring, not a run-time call, so "Claude
  calls = 0" and the non-goal "Claude at runtime" hold. Procedure: AGENTS.md.
- Checked before a run depends on them: `jrp queries check --line <slug>` sends each once and
  prints hit count and newest titles; nothing is stored, no model is called.
- At run time they bypass Qwen and Jev query_selection. Each adapter's list is rotated by the
  line's run count (earlier Reports), because the keyword budget (and, until 2026-09-26,
  arXiv's one-search-a-line cap) cuts from the front; not by the day ordinal, which repeats the same start when a rotated
  line's interval shares a factor with the list's length (code review).
- Questions themselves stay author-maintained, updated when the author notices (same day's
  decision; external sweep: every living-review / PIR / KIT practice keeps a human owner).
- Topic convergence is not solved by date windows (they only stop repeats of the same item,
  which store dedup and newest-first sorting already do); it surfaces as empty days, the signal
  to rewrite the question and its queries.
**Generation reduced to the prose (author decision 2026-09-23, same day).** Every line got
authored queries (trial-fetched), and the two other generation sites were removed rather
than kept as fallbacks: `qwen/queries.py` + `jev/query_selection.py` (a question without
query lines now sends no keyword query and the note says so) and the question proposals —
`qwen/proposals.py`, `jev/question_seeding.py`, the note's 「問いの候補」 section, the
harvester's `jrp:question:` adoption and `append_question` (questions are the author's; the
note no longer writes the file). The FLASH model (deepseek-v4.1-flash) has no site left and
is gone from the client and the price table. `query_selection` / `question_seeding` stay in
`JevFunction` as RETIRED_FUNCTIONS so stored Judgments still validate. This supersedes the
judgment map's "query candidates" / "query selection" rows, the "Qwen 2 sites" framing
(one site now: report prose), and the Question-centric section's proposal checkbox.
Review-when: a line's authored queries return 0 hits on three runs in a row, or the author
wants proposals back (the removed code is in git: commit before this one).

### Prose bench (author decisions 2026-09-23)

The prose was the one generation site left and read weak (343-1,108 chars per question-day,
mostly claim paraphrases). The loop that fixed it runs at dev time only
(`pipeline/prose_bench.py`, `jrp prose export|bench|read|gate`; the method is skill
author-calibrated-eval, the steps AGENTS.md):
- **Frozen cases** under `<JRP_STORE_DIR>/prose_bench/` (never the repo: verbatim
  third-party text): every question-day with prose, with claims, their sources' title and
  excerpt, and the run's own prose; about one case in three held out, chosen from the case id.
- **Roles.** Readability is judged by the author reading drafts blind; a fresh-context Opus
  judge (`.claude/agents/prose-judge.md`, Read/Write only, ~25k tokens a call vs ~85k for a
  general subagent) checks fidelity only, one draft at a time, with binary checks and a
  pass / fail verdict (`docs/prose-rubric.md`, the skill llm-as-judge shape); code checks
  form. This supersedes the non-goal "LLM-as-judge with another LLM as the truth source"
  for the dev-time fidelity gate only; runs call no Claude.
- **Why the judge does not judge readability.** On one case the author found qwen3.7-max's
  628-char draft "very clear" and Opus's 1,267-char draft "informative but hard to read";
  the Opus judge, under a rubric saying information volume is no reason to win, chose Opus
  in both orders, on readability and overall. The same judge caught a comparator swap the
  author read past. An earlier pairwise, per-axis quality rubric mostly measured compliance
  with rules this session wrote and wins over a weak baseline.
- **What the author's reading changed.** Blind read of v0 / v3 / Opus-on-v3: all "make the
  eyes slide" and "skip the premise", Opus too — the cause was the framing (a claim per
  sentence, [n] everywhere, no room for background), not the model. The prompt was rebuilt
  as explaining today's study to a reader who has not read it (v4-v7): a plain lead;
  per study, problem -> what they did -> what they found; terms glossed on first use; 1-2
  numbers per study with the comparator; 700-1,000 chars; citations at paragraph end; no
  "this study does not address the question" disclaimer; hedges and design intent never
  written as results. Readability tracked the number of facts and names, not sentence
  length (Opus: 34 sentences averaging 37 chars read worse than qwen: 11 averaging 57).
- **Result.** v7 + self-check pass (check6) on qwen3.7-max: the author read the 3 hard dev
  cases and 3 holdout cases as "very readable", "the inference is really useful"; the
  judge passed 5 of 6 cases in both orders (one holdout case generalized a table-QA result
  to all models in the inference paragraph; the run's own v0 prose failed that case too).
Review-when: the author's reading of a new batch disagrees with the fidelity gate's
direction, or production notes read as "eyes slide" again.

### Prose model (author decision 2026-09-24)

The prose, the one generation site left, moves from `qwen3.7-max` on DashScope to
`gpt-5.6-sol` on the author's ChatGPT/Codex subscription, and the model becomes config
(decision 11's "generation provider is config", made real):
- **`JRP_PROSE_MODEL=<backend>:<model>`**, default `openai-codex:gpt-5.6-sol`; backends
  `openai-codex` (pydantic-ai 2.47 `OpenAICodexProvider` + `OpenAICodexModel`, the Codex
  backend's streamed, `store=false` Responses dialect) and `dashscope` (`AlibabaProvider`, as
  before). A bare model name or an unknown backend stops the run before the store is touched;
  no silent fallback to a model the author did not name. `generation/client.py` (was `qwen/`).
- **Login of the pipeline's own** (`jrp codex login` → `~/.config/jrp/codex-auth.json`, mode
  600, `JRP_CODEX_AUTH`), not the Codex CLI's `~/.codex/auth.json`: refresh tokens are
  single-use and pydantic-ai reads the CLI file read-only, so a refresh inside a run would
  leave the CLI (and the next run) with a spent token. The file is an
  `OpenAICodexCredentialSource`: every refresh is written back. One provider per process
  (`Writer`), shared by the lines that run side by side, so a refresh is single-flight.
- **Prompt cache key pinned** (`jrp-prose`): `OpenAICodexModel` otherwise sets it to each
  call's fresh conversation id, which defeats the cache across sections and makes every
  request body unique (no cassette replay).
- **Thinking policy** maps per backend: DashScope `enable_thinking`; GPT-5.6's reasoning
  effort (`off` → `none`, otherwise the model's default, medium).
- **Cost**: a subscription is a flat plan, so its tokens are counted in the operations
  section but priced 0; the cost line says so and the cap then covers Jev alone. A
  per-token model with no entry in `PRICES` counts 0 and is flagged ("生成単価未設定").
- **Not yet done**: the prompt (v7 + check6, "Prose bench") was tuned and read on
  qwen3.7-max. It has not been re-read on gpt-5.6-sol; the bench's `--model` takes the same
  spec, so the comparison runs on the same frozen cases.
Review-when: the author's reading of GPT-5.6 Sol notes is worse than the qwen3.7-max
baseline, the plan's usage limits cut a morning run short, or OpenAI's terms for
subscription auth outside the Codex clients change.

### Non-goals (explicit)

ReAct / supervisor loops; local models; Grok in v1; X adapter in v1; writing into
graph.jsonld; automatic rule application; local decision model; Claude at runtime;
LLM-as-judge with another LLM as the truth source.

## Libraries (verified as-of 2026-09-22)

- `typesafe-sdk`: Pydantic-native; `system_one(state, questions, response_model=…)`;
  `AsyncTypeSafeClient`; `RetryPolicy`; default timeout 10s; `TYPESAFE_API_KEY`.
- `pydantic-ai` 2.47.0: `OpenAICodexProvider` / `OpenAICodexModel` (ChatGPT/Codex
  subscription OAuth, `openai-codex:` models; added 2026-09-24), `AlibabaProvider`
  (`DASHSCOPE_API_KEY`), `Agent(output_type=…)`
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
