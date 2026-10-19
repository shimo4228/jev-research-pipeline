# Store goldens

Store files written by an older build, kept byte for byte: the migration tests read
them as the store an upgraded pipeline meets on disk.

- `old-context-additive.jsonld` — `pipeline.jsonld` from the store retired on 2026-09-23
  (`store.pre-pilot-20260923/`). Its @context lacks the 17 terms the Question model
  added (cb5fc0d) and has none removed or changed; its node reads under today's model.
- `old-context-incompatible.jsonld` — the same @context with one `claim_detection`
  Judgment from that store. Its subjects are `(unit,)`; today's model requires
  `(unit, question)`, so no context rewrite can make it valid.
- `report-label-fa67ed5.jsonld` — a line partition that the fa67ed5 build's
  `Partition.write_all` wrote from `tests/builders.py` data (no store data, no third-party
  text): two Reports whose Operations carry `claude_calls` 0 and `gold_agreement` 1.0 and
  null, and three Labels, two of them `question_day`. It pins that the Reports and Labels
  already in a store validate under today's model and survive a rewrite.

Replace a golden only when a task declares a store format change; a red golden
otherwise is an incident, not a test to update.
