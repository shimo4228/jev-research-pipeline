kind: internal
# used rate 調査 report の file:line 再確認（addendum）

as-of 2026-10-19、HEAD eec9758 の main を Read / Grep で確認。対象 report は `docs/plans/research/2026-10-19-used-rate-label.md`。結果: 10 項目すべて**行番号ごと現行 main と一致**（moved なし）。

## 再確認表

| # | claim | 結果 | 引用 |
|---|---|---|---|
| 1 | `reduction/fit.py:185-191` 2 クラス未満で閾値を skip | holds | `classes = sorted(set(gold_claims.values()))` / `if len(classes) < 2:` / `skipped.append(f"{name}: gold {n_gold} 件がすべて {only} — 両方の判定が揃うまで提案しない")` / `continue` |
| 2 | `reduction/log.py:103-111` `gold()` は provenance 不問 | holds | `if kind_of(lb.subject) == "claim": latest[lb.subject] = lb`（provenance を見ない。docstring は「Labels on a question-day or a source are not claim gold」） |
| 3a | `report/vault.py:198-217` `_cleared` が空欄 box の Label id を返す | holds | `"""Label @ids to withdraw: every subject the author left, or made, blank."""` … `return [Label.id_for(i, report_id) for i in subjects]` |
| 3b | `pipeline/runner.py:122` で削除 | holds | `withdrawn += part.remove(result.cleared)`（直前コメント 119-121: `cleared` は note の空欄 box を毎 run 全部列挙） |
| 4a | `model/nodes.py:787-843` Label の identity | holds | `Identity = (subject, report)` / `def id_for(subject, report): return content_id("label", subject, report)`。`SUBJECT_KINDS = {"question_log","source","claim"}`（807）、`verdict: Literal["correct","incorrect"]`（803） |
| 4b | `nodes.py:925-939` `GraphNodeType` | holds | `Line \| Question \| QuestionLog \| QueryCandidate \| SourceItem \| Unit \| Claim \| Judgment \| Decision \| Report \| Label \| RotationCursor \| StageRecord`（discriminated union は 940） |
| 5a | `run.py:1072-1084` 載った source = `QuestionLog.sources` | holds | `sources = list({i.source.id: i.source for i in items}.values())` … `sources=tuple(s.id for s in sources)` |
| 5b | `run.py:1211-1222` operations 行に FILL_RATE | holds | `t.FILL_RATE(lang, rate=f"{fill:.2f}") if fill is not None else t.FILL_RATE_NONE(lang)`（1221） |
| 5c | `run.py:1562-1583` `fill_rate_previous` | holds | 分子は `isinstance(n, Label) and n.report == last.id and n.provenance == "question_day"`（1581）。verdict は見ない |
| 5d | `run.py:580-608` S2 の正例・負例 | holds | `by_verdict[label.verdict].add(source.url)`（588）。`if not negatives:` で `nets.seeded_negatives(pool, seed=self.ctx.line.id)`（595-607）。pool は `n.fetched_at.date() < self.now.date()` |
| 6a | `runner.py:144` `run_pipeline` | holds | `async def run_pipeline(` |
| 6b | `runner.py:176-182` line ごとの harvest | holds | `for slug in (only or (*rotation.order, *daily))` で `harvest_line(store, vault, slug, now, lang)` |
| 7a | `config.py:55-71` `load_tracks` | holds | `repo = Path(str(repos[0]["target_repo"])).expanduser() if repos else None` |
| 7b | `config.py:106-111` `_read_graph` | holds | `path = repo / "graph.jsonld"` / `if not path.is_file(): return []` / `.get("@graph", [])` |
| 8 | `nets.py:183-199` `arxiv_id_of` / `paper_id` | holds。旧 id 問題も現存 | `return tail.split("v")[0] if tail else None`（189）。`paper_id` は `ARXIV:` か `"DOI:" + url.split("doi.org/", 1)[1]` |
| 9a | `Question.canary_papers` | holds | `nodes.py:679` `canary_papers: tuple[IRI, ...] = ()`。他の使用箇所: `questions.py:161`、`run.py:808, 1268, 1513`、`jsonld.py:84, 96, 157` |
| 9b | vault の jrp 印 | holds | `vault.py:36` `_MARK_LINE_RE` は `<!-- jrp:([a-z]+):(\S+) -->`。`vault.py:37` `_REPORT_ID_RE` は `^jrp_report:`。`vault.py:68` `{run_date}_jrp_{slug}.md`。`vault.py:254` `glob(f"*_jrp_{slug}.md")`。`markdown.py:168` `jrp_report: {json.dumps(report.id)}`。`markdown.py:4-5` frontmatter に `category: jrp` |
| 10a | `pipeline-design.md:324-331` | holds | 「Recorded candidate for later: **used rate** — share of surfaced sources that appear within 30 days in any line's graph.jsonld / ADR / vault note … ⭕❌ demoted to optional gold … Decide after the pilot has run for a few weeks.」 |
| 10b | `daily-tool-hardening.md:70-71` | holds | 「used rate（design「Evaluation and self-improvement」の延期候補）は、記入率 0 を受けて設計提案までにとどめる（実装しない）」 |

## store の Label 件数（2026-10-19）

- `"verdict": "incorrect"` は `store/lines/*.jsonld` 全体で **0 件**（Grep の空白許容 regex、0 match）。
- `"verdict": "correct"` は **163 件**（edge 14 / authorship 37 / desire 19 / aap 15 / akc 8 / jev 70）。report 記載の Label 163 件と一致し、全件が correct。

## 補足（moved ではないが再確認で分かったこと）

- 9a で、`canary_papers` は `jsonld.py` の context にも入っている（`_iri_list("canaryPapers")`）。report は `nodes.py:679` と `run.py:1268` だけを挙げていた。
- 5d の pool 側の `nets.paper_id(n.url)` も 8 の `split("v")` を通る。

## Still unknown

- 本 addendum は file:line の再読のみ。report 内の store 件数（SourceItem 58,905、QuestionLog 160）と vault・graph・ADR の集計は再計測していない。
