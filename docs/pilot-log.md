# Pilot log

Append-only. One block per live run under the pilot mandate (author decision 2026-09-23,
docs/design/pipeline-design.md "Pilot mandate"). Scratch runs write
`/tmp/jrp-scratch/{vault,store}`; only the final run writes the real vault and store.
Budget: 8 live runs, $3 cumulative, 3 h from 10:28 JST.

Conditions: (1) wall ≤ 5 min, cost ≤ $0.30 (2) note ≤ 12 KB, Review ≤ 10, 橋渡し ≤ 5,
未判定 < 5% of (source, question) pairs (3) prose for every question with a Keep, every [n]
resolves (4) off-topic papers Drop, jev canaries Keep (5) no adapter failure line except the
web_search skip (6) no stack trace (7) fresh-context Opus judge: ≥ 2 of 3 Publishable.

## Run 1 — 2026-09-23 10:43 JST (scratch)

Change: 1f44138 (staged screening, triage after prefilter, capped Review/橋渡し, HF date,
arXiv retry, proposal timeout, daily track jev, lines side by side).
Lines: akc, contemplative, aap + jev (daily).

| # | condition | measured | pass |
|---|---|---|---|
| 1 | wall ≤ 5 min, cost ≤ $0.30 | 278 s; $0.0386 + 0.0310 + 0.0300 + 0.0333 = $0.133 | ✅ |
| 2 | note ≤ 12 KB, Review ≤ 10, 橋渡し ≤ 5, 未判定 < 5% | 2.9–8.4 KB; Review 10 (12 capped); 橋渡し ≤ 5; 未判定 0.0–0.2% | ✅ |
| 3 | prose for every question with a Keep, [n] resolve | no Keep anywhere → no claims, no prose | ❌ (vacuous) |
| 4 | off-topic Drop; jev canaries Keep | canaries never fetched (4 "落下" lines) | ❌ |
| 5 | no adapter failure line but web_search | keyword/arxiv 406 on every line (retry did not help) | ❌ |
| 6 | no stack trace | none | ✅ |

Found: (a) Keep impossible — routing certainty was the min over every Noul incl. gates;
`evidence_compatible` sits at ~0.5 when a question has no constraint, so certainty ≈ 0.02;
Score certainty itself runs 0.48–0.73, never 0.9. (b) arXiv 406 is httpx2-specific on
queries arXiv's cache does not hold (urllib, curl, raw TLS: 200; cached queries: 200 to
anyone). (c) keyword budget cut first-come → no GitHub query ever sent. (d) the canary
check reported "落下" for canaries no net fetched. (e) HF daily got no room under the
firehose cap (arXiv RSS came first and filled it).

## Run 2 — 2026-09-23 10:56 JST (scratch)

Change: a283ea3 (Keep reachable: certainty on the placing Scores, min_certainty 0.5;
arXiv via urllib; keyword round-robin; HF before the arXiv listing; canary probe).
Lines: authorship, ans, desire + jev.

| # | condition | measured | pass |
|---|---|---|---|
| 1 | wall ≤ 5 min, cost ≤ $0.30 | 356 s; $0.0300 + 0.0422 + 0.0468 + 0.0369 = $0.156 | ❌ (wall) |
| 2 | note ≤ 12 KB, Review ≤ 10, 橋渡し ≤ 5, 未判定 < 5% | 3.5–8.6 KB; Review 0–3; 未判定 0.0–0.1% | ✅ |
| 3 | prose for every question with a Keep, [n] resolve | desire and jev: prose for the Keep question; authorship: 2 Keep, 0 claims | ⚠️ (authorship Keep without prose) |
| 4 | off-topic Drop; jev canaries Keep | canaries: 2 keep, 1 not found (fork, search skips forks), 1 drop (docs page = navigation text) | ❌ |
| 5 | no adapter failure line but web_search | none (406 and HF 400 gone) | ✅ |
| 6 | no stack trace | none | ✅ |

Found: Qwen thinks by default (flash 5.0 → 2.9 s, max 5.9 → 2.2 s with it off; the 122 s
jev prose was mostly thinking). The method/evidence gates at 0.5 dropped most of the jev
line's calibration papers at 0.30–0.46 ("cannot tell" from an abstract).

## Run 3 — 2026-09-23 11:12 JST (scratch, fresh store seeded with the real rotation cursor)

Change: 4fa7413 (Qwen thinking off; method/evidence gates 0.3; canaries via repos API and
<main>; stage timing). Lines: authorship, ans, desire + jev — the set the final real run
will take.

| # | condition | measured | pass |
|---|---|---|---|
| 1 | wall ≤ 5 min, cost ≤ $0.30 | 100 s; $0.0343 + 0.0348 + 0.0249 + 0.0533 = $0.147 | ✅ |
| 2 | note ≤ 12 KB, Review ≤ 10, 橋渡し ≤ 5, 未判定 < 5% | jev 24.6 KB (31 claims under one question); others 3.0–5.1 KB; Review ≤ 10 (jev 16 capped); 橋渡し 0; 未判定 0.0–0.2% | ❌ (jev size) |
| 3 | prose for every question with a Keep, [n] resolve | authorship 1/1, jev 1/1 questions with claims have prose | ✅ |
| 4 | off-topic Drop; jev canaries Keep | 3 of 4 keep (one via the nets); pydantic docs page → review (evidence_strength "anecdote" for a spec page the question asks for) | ❌ |
| 5 | no adapter failure line but web_search | none | ✅ |
| 6 | no stack trace | none | ✅ |

### Slot bleed check (judge requirement) — on this run's jev store, 20 pairs

`scripts/slot_bleed.py /tmp/jrp-scratch/store jev 20` at 4fa7413: batched vs single
**route agreement 11/20 (55%)**, max |Δp| 0.25 (on_topic). The disagreements lean one way:
5 pairs keep in the batch and drop alone, e.g. "Machine Learning based Analysis for
Radiomics Features Robustness" kept for a Jev calibration question. Below the 90% bar →
**batching switched off** (core.BATCH_MAX_ITEMS = 1: one subject per request everywhere).

## Run 4 — 2026-09-23 11:18 JST (scratch, fresh store seeded with the real cursor)

Change: 71f8e68 (one subject per Jev request; ≤ 8 claims per question, ≤ 2 per source;
[n] keyed in the fold; evidence_strength read against the question's evidence kind).
Lines: authorship, ans, desire + jev.

| # | condition | measured | pass |
|---|---|---|---|
| 1 | wall ≤ 5 min, cost ≤ $0.30 | 116 s; $0.0227 + 0.0342 + 0.0294 + 0.0377 = $0.124 | ✅ |
| 2 | note ≤ 12 KB, Review ≤ 10, 橋渡し ≤ 5, 未判定 < 5% | jev 12,394 B (12 KB = 12,288); others 3.2–4.1 KB; Review ≤ 8; 未判定 ≤ 0.3% | ❌ (jev by 106 B) |
| 3 | prose for every question with a Keep, [n] resolve | desire 1/1, jev 1/1 | ✅ |
| 4 | off-topic Drop; jev canaries Keep | 3 keep; jev-papers → review (borderline; judged on a 109-character description) | ❌ |
| 5 | no adapter failure line but web_search | none | ✅ |
| 6 | no stack trace | none | ✅ |

Single requests are stricter than the batch was: authorship and ans pass nothing past the
prefilter (best on_topic 0.49 / 0.46) — the firehose holds nothing for them today, and the
keyword net had 5 requests for 3 questions x 3 adapters.

## Run 5 — 2026-09-23 11:25 JST (scratch, fresh store seeded with the real cursor)

Change: ca98119 (keyword budget 12; evidence gist 120; GitHub canaries read by README).
Lines: authorship, ans, desire + jev.

| # | condition | measured | pass |
|---|---|---|---|
| 1 | wall ≤ 5 min, cost ≤ $0.30 | 149 s; $0.0459 + 0.0342 + 0.0275 + 0.0435 = $0.151 | ✅ |
| 2 | note ≤ 12 KB, Review ≤ 10, 橋渡し ≤ 5, 未判定 < 5% | jev 14.6 KB (section 5.2, Review 3.3, fold 3.5); others 3.1–7.1 KB; Review ≤ 9; 未判定 ≤ 0.4% | ❌ (jev size) |
| 3 | prose for every question with a Keep, [n] resolve | authorship 2/2, desire 1/1, jev 1/1 | ✅ |
| 4 | off-topic Drop; jev canaries Keep | 3 keep (jev-papers now keep on its README); pydantic docs → review at 0.58 vs cut 0.60 (evidence_strength "anecdote": the level text only knew measurements) | ❌ |
| 5 | no adapter failure line but web_search | keyword/arxiv 429 on desire, and the net-level quiet then silenced GitHub/HF keyword for every line | ❌ |
| 6 | no stack trace | none | ✅ |

## Run 6 — 2026-09-23 11:30 JST (scratch, fresh store seeded with the real cursor)

Change: c693000 (arXiv one connection; per-source rate-limit quiet; primary sources as
evidence; 5 claims per question). Lines: authorship, ans, desire + jev.

| # | condition | measured | pass |
|---|---|---|---|
| 1 | wall ≤ 5 min, cost ≤ $0.30 | 210 s; $0.0233 + 0.0347 + 0.0305 + 0.0436 = $0.132 | ✅ |
| 2 | note ≤ 12 KB, Review ≤ 10, 橋渡し ≤ 5, 未判定 < 5% | jev 12,199 B; others 2.9–3.9 KB; Review ≤ 7; 橋渡し 0; ≤ 0.3% | ✅ |
| 3 | prose for every question with a Keep, [n] resolve | desire: both drafts rejected by rubric_report (unsupported_statement 0.77 / 0.66 ≥ 0.5) → template | ❌ (found by the judge; I had read "生成 11.5s" as a pass) |
| 4 | off-topic Drop; jev canaries Keep | all 4 canaries keep | ✅ |
| 5 | no adapter failure line but web_search | keyword/arxiv 429 and ConnectError on every line (paced, one connection) | ❌ |
| 6 | no stack trace | none | ✅ |

### Condition 7 — fresh-context Opus judge on authorship / ans / desire (run 6)

Given only the three notes and questions/<slug>.md. **Publishable 0/3.**
- authorship — Fix: honest empty day, but proposal 1 defines 三軸反転 with other axes than
  the question file; the reason for the empty day (arXiv cut off) is only in 運用.
- ans — Fix: empty day; proposal 4 carries a Hangul slip ("オン톨ロジー") and drifts to ML;
  未判定 lists queries while 運用 says "未判定 0".
- desire — Rewrite: the only section is the template ("本文生成なし"), no inference; the one
  evidence line is cut mid-sentence.

Fixes: rubric_report also sees the evidence set the prose was given, and rejects only at
unsupported ≥ 0.7; an empty-day note says how far the sources got; proposals see the
existing questions (definitions follow them) and drop foreign-script slips; the pair
failure line is named as such; gists end at a word with "…"; arXiv keyword ≤ 4 a day.

## Run 7 — 2026-09-23 11:44 JST (scratch, fresh store seeded with the real cursor)

Change: 74d3602 (rubric sees the evidence set, unsupported 0.7; empty-day line; proposals
see existing questions, foreign-script filter; arXiv keyword ≤ 4/day).
Lines: authorship, ans, desire + jev.

| # | condition | measured | pass |
|---|---|---|---|
| 1 | wall ≤ 5 min, cost ≤ $0.30 | 136 s; $0.0239 + 0.0353 + 0.0210 + 0.0370 = $0.117 | ✅ |
| 2 | note ≤ 12 KB, Review ≤ 10, 橋渡し ≤ 5, 未判定 < 5% | 3.6–10.8 KB; Review ≤ 5; 橋渡し 0; ≤ 0.3% | ✅ |
| 3 | prose for every question with a Keep, [n] resolve | jev 1/1 (prose, no template); the three rotation lines had no Keep | ✅ |
| 4 | off-topic Drop; jev canaries Keep | jev-phishing-bench → review: weighted 0.87 but novelty split adds_detail/changes_answer, certainty 0.49 < 0.50 | ❌ |
| 5 | no adapter failure line but web_search | none (arXiv keyword cap line is informational) | ✅ |
| 6 | no stack trace | none | ✅ |

### Condition 7 (dry, on run 7's notes) — fresh-context Opus judge: **Publishable 2/3**
- authorship — Fix: the empty-day line says 4 pairs were screened, but not where they went.
- ans — Publishable (minor: a simplified-Chinese 广播 in a proposal; an unjudged row without reason).
- desire — Publishable (minor: a prompt phrase leaked into a proposal; duplicated fallback lines).

Fixes for the final run: a score ≥ keep + band (0.7) is Keep regardless of certainty; the
empty-day line gives the routes of the screened pairs; duplicate operations lines are merged.

## Run 8 — 2026-09-23 12:00 JST (FINAL, real vault and store; live-run cap reached)

Change: 5879fef (clear-call keep ≥ 0.7; empty-day routes; merged operations lines; code
review fixes: canary probe through StoredJev, arXiv keyword 1 per line, capped claims
stored, per-line failure isolation). Lines: authorship, ans, desire + jev.
Real notes and store were backed up to /tmp/jrp-scratch/old/real-*-backup-1150 first
(no author ticks in the overwritten notes).

| # | condition | measured | pass |
|---|---|---|---|
| 1 | wall ≤ 5 min, cost ≤ $0.30 | 155 s; $0.0349 + 0.0352 + 0.0315 + 0.0422 = $0.144 | ✅ |
| 2 | note ≤ 12 KB, Review ≤ 10, 橋渡し ≤ 5, 未判定 < 5% | 3.5–11.3 KB; Review ≤ 5; 橋渡し 0; ≤ 0.1% | ✅ |
| 3 | prose for every question with a Keep, [n] resolve | authorship, desire, jev: prose (no template); [n] in range (code-checked) | ✅ |
| 4 | off-topic Drop; jev canaries Keep | no weather-PDE / medical-RL kind of paper in Keep or Review (read by hand); canaries 3 keep, jev-phishing-bench **unjudged** (its one Jev request failed) | ❌ |
| 5 | no adapter failure line but web_search | keyword/arxiv 429 / ConnectError on authorship, ans, desire (arXiv throttling after a day of pilot traffic, one request per line) | ❌ |
| 6 | no stack trace | none | ✅ |

### Condition 7 — fresh-context Opus judge on the final notes: **Publishable 1/3** ❌
- authorship — Fix: readable; paragraph 1 draws an inference ("移行は現場ではまだ起きていない")
  inside the evidence paragraph; the granularity PeerPrism defines is missing; the Review
  reason is a score, not why the source bears on the question.
- ans — Publishable: an honest empty day with the reason (0 pairs, arXiv cut off).
- desire — Rewrite: citations match their claims, but the prose reads single studies as
  "places" (venues) the question asks for, and the inference builds on that misreading.

Cumulative: 8 live runs, ≈ $1.12 (run costs $1.104 + probes), 10:28 → 12:08 JST.
Stopped at the live-run cap with conditions 4, 5 and 7 open.
