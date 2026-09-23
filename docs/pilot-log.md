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
