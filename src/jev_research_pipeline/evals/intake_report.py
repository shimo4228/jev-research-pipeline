"""`jrp eval intake --candidate <toml>`: the comparison of one candidate against the baseline,
line by line, as printed lines and one JSON report (plan intake-eval, claim 4).

Order within a line, so the noise floor is measured before the numbers it qualifies:
1. freeze (with --freeze): today's snapshot, each request once (evals.freeze);
2. the noise floor: when the bench has no jitter rows yet, re-ask a seeded sample (evals.judge);
3. the history window: replay both arms, judge what either reached past the floor, score;
4. the query yields over the whole history, and the rotation estimate of the next runs;
5. the snapshot: per query today, and what the next run's sends would bring under each arm.

Writes only into the bench (judgments/, jitter.jsonl, snapshots/, reports/); the store's
partitions are read in memory (registry.read_lifted) and never rewritten.
"""

import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Final

import httpx2
from pydantic import AwareDatetime, JsonValue

from jev_research_pipeline.model import GraphNodeType, SourceItem
from jev_research_pipeline.pipeline.config import env_tracks
from jev_research_pipeline.pipeline.registry import read_lifted
from jev_research_pipeline.pipeline.runner import store_dir
from jev_research_pipeline.questions import NoQuestions
from jev_research_pipeline.store import GraphStore

from . import freeze
from .freeze import FREEZE_TIMEOUT_S
from .intake import (
    BASELINE,
    CUT,
    YIELD_SENDS,
    Arm,
    Candidate,
    Fetch,
    FrozenSet,
    LineSetup,
    Query,
    QueryYield,
    Reach,
    RotationDiff,
    Score,
    SelfCheck,
    Snapshot,
    SnapshotQuery,
    SourceRow,
    Verdict,
    arm,
    by_source,
    frozen_set,
    line_setup,
    load_candidate,
    new_on_day,
    query_line,
    query_yields,
    replay,
    rotation,
    score,
    screenable_reached,
    self_check,
    sends,
    turn_of,
)
from .judge import (
    API_KEY_ENV,
    JITTER_SOURCES,
    BudgetExceeded,
    Judge,
    Spend,
    judgments_partition,
    measure_jitter,
    read_jitter,
)
from .paths import eval_root
from .stats import Chao2, PairedDiff, expected_flips, paired_diff, wilson

DEFAULT_DAYS: Final = 14
ROTATION_RUNS: Final = 12
"""Runs the rotation estimate looks ahead: one full cycle of a line's ~11 query lines."""
SIGNIFICANT: Final = 0.05
BOUNDARY: Final = 0.1
"""An on-topic difference within this of the cut is a boundary one (judge-relative)."""


@dataclass
class LineResult:
    slug: str
    start: date
    end: date
    days: list[date]
    base: Score
    cand: Score
    diff: PairedDiff
    floor: float | None
    """Expected verdict flips over the sources of new papers only one arm reached (the only
    answers the difference rests on: a shared source is one stored answer for both); None =
    no jitter rows."""
    boundary: int
    """N_ot papers only one arm found whose best on_topic is within BOUNDARY of the cut."""
    check: SelfCheck
    base_rows: list[SourceRow]
    cand_rows: list[SourceRow]
    yields: list[QueryYield]
    rotation: RotationDiff
    snapshot: Snapshot | None = None
    notes: list[str] = field(default_factory=list[str])


def _window(frozen: FrozenSet, days: int, as_of: date | None) -> tuple[date, date]:
    end = as_of or max((f.day for f in frozen.fetches), default=date.today())
    return end - timedelta(days=days - 1), end


def _sources(frozen: FrozenSet, reaches: Sequence[Reach], a: Arm) -> dict[str, SourceItem]:
    return screenable_reached(reaches, frozen, a)


def _keyword_new(frozen: FrozenSet, queries: set[Query], until: date) -> list[SourceItem]:
    """The sources a yield's verdicts are read for: the results new to the line on each of a
    query's last YIELD_SENDS sends (the rotation reads no older send; exhaustion needs no
    verdict), so a long history costs no Jev request."""
    sent: dict[Query, list[Fetch]] = {}
    for f in frozen.fetches:
        if f.net == "keyword" and f.query in queries and f.day <= until:
            sent.setdefault(f.query, []).append(f)
    out: dict[str, SourceItem] = {}
    for fetches in sent.values():
        for f in fetches[-YIELD_SENDS:]:
            for sid in new_on_day(frozen, f).values():
                out[sid] = frozen.sources[sid]
    return list(out.values())


def _boundary(
    base: Score, cand: Score, frozen: FrozenSet, reaches: Sequence[Reach], v: Mapping[str, Verdict]
) -> int:
    only = set(base.found) ^ set(cand.found)
    best: dict[str, float] = {}
    for r in reaches:
        key = frozen.keys[r.source]
        if key in only and (x := v.get(r.source)) is not None and x.passes:
            best[key] = max(best.get(key, 0.0), x.best)
    return sum(1 for b in best.values() if b < CUT + BOUNDARY)


def latest_snapshot(bench: Path, slug: str, queries: Iterable[Query]) -> FrozenSet | None:
    """The line's newest snapshot in the bench (evals.freeze), as a frozen set."""
    root = bench / "snapshots"
    days = sorted(p.parent.name for p in root.glob(f"*/{slug}.jsonld")) if root.is_dir() else []
    if not days:
        return None
    nodes = read_lifted(freeze.snapshot_partition(bench, date.fromisoformat(days[-1]), slug).path)
    return frozen_set(slug, nodes, queries)


def snapshot_new(snap: FrozenSet, store: FrozenSet, a: Arm) -> list[SourceItem]:
    """The snapshot's keyword results the store never fetched for the line, past the floor:
    the sources its scoring judges."""
    return [
        snap.sources[sid]
        for f in snap.fetches
        if f.net == "keyword"
        for sid in f.outputs
        if snap.keys[sid] not in store.first and a.screenable(snap.sources[sid])
    ]


@dataclass(frozen=True)
class Arms:
    setup: LineSetup
    base: Arm
    cand: Arm
    turn: int
    """The rotation's turn of the line's next run (intake.turn_of)."""


def score_snapshot(
    snap: FrozenSet,
    store: FrozenSet,
    arms: Arms,
    verdicts: Mapping[str, Verdict],
    env: Mapping[str, str],
) -> Snapshot:
    """Per query today, and what the next run's keyword sends would bring under each arm —
    new against the whole store, since the snapshot is after every stored fetch."""
    day = min((f.day for f in snap.fetches), default=date.today())
    out = Snapshot(day=day)
    ot_of: dict[Query, set[str]] = {}
    for f in snap.fetches:
        if f.net != "keyword" or f.query is None:
            continue
        new = {snap.keys[sid] for sid in f.outputs} - set(store.first)
        ot = {
            snap.keys[sid]
            for sid in f.outputs
            if snap.keys[sid] in new
            and arms.base.screenable(snap.sources[sid])
            and (x := verdicts.get(sid)) is not None
            and x.passes
        }
        ot_of[f.query] = ot
        out.queries.append(SnapshotQuery(f.query, len(f.outputs), len(new), len(ot)))
    for which, a in (("base", arms.base), ("cand", arms.cand)):
        rates = sends(arms.setup, _sent(a), turn=arms.turn, runs=1, today=day, env=env)
        sent = [q for q, n in rates.items() if n]
        reached: set[str] = set()
        for q in sent:
            reached |= ot_of.get(q, set())
        if which == "base":
            out.base_next, out.base_sent = len(reached), len(sent)
        else:
            out.cand_next, out.cand_sent = len(reached), len(sent)
    return out


async def evaluate_line(
    env: Mapping[str, str],
    slug: str,
    candidate: Candidate,
    *,
    bench: Path,
    spend: Spend,
    http: httpx2.AsyncClient | None,
    now: AwareDatetime,
    days: int = DEFAULT_DAYS,
    as_of: date | None = None,
    jitter_n: int = JITTER_SOURCES,
    do_freeze: bool = False,
) -> LineResult:
    try:
        setup = line_setup(env, slug, now=now)
    except KeyError as e:
        raise UnknownLine(slug) from e
    nodes = read_lifted(GraphStore(store_dir(env)).line(slug).path)
    base_arm, cand_arm = arm(BASELINE, setup), arm(candidate, setup)
    texts = {*base_arm.queries, *cand_arm.queries, *cand_arm.dropped}
    frozen = frozen_set(slug, nodes, texts)
    start, end = _window(frozen, days, as_of)
    window = frozen.days(start, end)
    known_keys = frozenset(k for k, d in frozen.first.items() if d < start)
    api_key = env.get(API_KEY_ENV) or None
    known: dict[str, GraphNodeType] = {**nodes, **judgments_partition(bench, slug).load()}
    judge = Judge(setup, known, bench, spend, http=http, api_key=api_key)
    notes: list[str] = []

    if do_freeze:
        planned, skipped = freeze.requests(
            setup.nets, [*base_arm.queries, *cand_arm.queries], now=now, env=env
        )
        done = await freeze.freeze(
            planned,
            freeze.snapshot_partition(bench, now.date(), slug),
            setup.ctx.line,
            cassette=freeze.snapshot_dir(bench, now.date()) / "cassette.json",
            now=now,
            env=env,
        )
        notes += [
            f"凍結: 送信 {done.sent} 件、結果 {done.results} 件、OpenAlex credit {done.credits}"
        ]
        notes += skipped + done.lines
        if done.stopped:
            raise RateLimited("\n".join(notes))

    base_reach = replay(frozen, setup, base_arm, window, start=start)
    cand_reach = replay(frozen, setup, cand_arm, window, start=start)
    base_src = _sources(frozen, base_reach, base_arm)
    cand_src = _sources(frozen, cand_reach, cand_arm)

    jitter = read_jitter(bench)
    if not jitter and jitter_n:
        jitter = await measure_jitter(
            judge, list(base_src.values()), n=jitter_n, seed=f"{slug}:{now.date()}", now=now
        )
    deltas = [row.delta for row in jitter]

    yield_queries = {*base_arm.queries, *cand_arm.queries, *cand_arm.dropped}
    asked = {**base_src, **cand_src}
    asked |= {s.id: s for s in _keyword_new(frozen, yield_queries, end) if base_arm.screenable(s)}
    verdicts = await judge.verdicts(list(asked.values()), now=now)

    base = score(frozen, base_arm, base_reach, verdicts, known=known_keys, days=window)
    cand = score(frozen, cand_arm, cand_reach, verdicts, known=known_keys, days=window)
    diff = paired_diff([cand.per_day.get(d, 0) - base.per_day.get(d, 0) for d in window])
    # only a new paper can move N_ot: a source of a known one never counts, so it adds no noise
    only = {sid for sid in set(base_src) ^ set(cand_src) if frozen.keys[sid] not in known_keys}
    floor = (
        expected_flips((v.margin for sid in only if (v := verdicts.get(sid))), deltas)
        if deltas
        else None
    )
    yields = query_yields(frozen, verdicts, sorted(yield_queries), until=end)
    turn = turn_of(nodes, setup.ctx.line.id, now.date() + timedelta(days=1))
    base_sends, cand_sends = (
        sends(setup, _sent(a), turn=turn, runs=ROTATION_RUNS, today=now.date(), env=env)
        for a in (base_arm, cand_arm)
    )
    rot = rotation({y.query: y for y in yields}, base_sends, cand_sends, runs=ROTATION_RUNS)
    result = LineResult(
        slug=slug,
        start=start,
        end=end,
        days=window,
        base=base,
        cand=cand,
        diff=diff,
        floor=floor,
        boundary=_boundary(base, cand, frozen, [*base_reach, *cand_reach], verdicts),
        check=self_check(frozen, base_reach, base_arm, window),
        base_rows=by_source(base.found),
        cand_rows=by_source(cand.found),
        yields=yields,
        rotation=rot,
        notes=notes,
    )
    snap = latest_snapshot(bench, slug, texts)
    if snap is not None:
        snap_verdicts = await judge.verdicts(snapshot_new(snap, frozen, base_arm), now=now)
        arms = Arms(setup, base_arm, cand_arm, turn)
        result.snapshot = score_snapshot(snap, frozen, arms, snap_verdicts, env)
    return result


def _sent(a: Arm) -> tuple[Query, ...]:
    """The queries an arm sends: none with the keyword net off."""
    return () if "keyword" in a.off else a.queries


class UnknownLine(LookupError):
    """A line slug config.toml does not have."""


class RateLimited(RuntimeError):
    """The freeze stopped on rate limits (rule debugging.md): report, do not retry."""


# ----------------------------------------------------------------------------- printing


def _signed(x: float) -> str:
    return f"{x:+.0f}" if abs(x - round(x)) < 1e-9 else f"{x:+.1f}"


def _share(k: int, n: int) -> str:
    if not n:
        return "-"
    lo, hi = wilson(k, n)
    return f"{k / n:.2f} [{lo:.2f}-{hi:.2f}] ({k}/{n})"


def _chao(c: Chao2 | None) -> str:
    if c is None:
        return "単位が足りない (10 未満)"
    point, lo, hi = c.missed
    return f"少なくとも {point:.0f} [{lo:.0f}-{hi:.0f}] (観測 {c.s_obs}、Q1 {c.q1}、Q2 {c.q2}、単位 {c.units})"


def _delay(score: Score) -> str:
    if not score.delay:
        return "-"
    late = sum(1 for d in score.delay.values() if d > 0)
    return f"中央値 {median(score.delay.values()):.1f} 日 (遅れて判定 {late} 件)"


def _verdict_line(r: LineResult) -> str:
    """A difference only when the t interval and the sign-flip p agree and it clears the
    noise floor: with many tied days (a full listing leaves no room) the two can disagree."""
    d = r.diff
    if d.low is None or d.high is None:
        return "判定: 日が 1 つしかなく区間が出ない"
    if r.floor is None:
        return "判定: 雑音の床が未測定 (TYPESAFE_API_KEY が無く、jitter の行も無い)"
    excludes = d.low > 0 or d.high < 0
    significant = d.p is not None and d.p < SIGNIFICANT
    if excludes and significant and abs(d.total) > r.floor:
        return "判定: 差あり (t 区間が 0 を含まず、符号反転の p < 0.05、雑音の床の外)"
    if excludes or significant:
        return "判定: 境目 (t 区間と符号反転の p が食い違う。窓を延ばすか日を足して測り直す)"
    return "判定: この窓では判別できない (区間が 0 を含む)"


def _sends_line(freed: float) -> str:
    if abs(freed) < 0.05:
        return "- keyword の送信: 1 run あたりの数は変わらない"
    if freed > 0:
        return f"- keyword の送信: 1 run あたり {freed:.1f} 件少ない"
    return f"- keyword の送信: 1 run あたり {-freed:.1f} 件多い"


def render_line(r: LineResult, candidate: str) -> list[str]:
    b, c, d = r.base, r.cand, r.diff
    interval = (
        f" [{_signed(d.low)}, {_signed(d.high)}]"
        if d.low is not None and d.high is not None
        else ""
    )
    p = f" p={d.p:.3f}" if d.p is not None else ""
    floor = f"±{r.floor:.1f}" if r.floor is not None else "未測定"
    per_run = (c.screened - b.screened) / max(len(r.days), 1)
    lines = [
        f"## {r.slug} (窓 {r.start}〜{r.end}、run {len(r.days)} 日、self-check {r.check.matched}/{r.check.days} 日一致)",
        "",
        f"| | baseline | {candidate} | 差 |",
        "|---|---|---|---|",
        f"| N_ot (新規で問いに合う論文) | {b.n_ot} | {c.n_ot} | {_signed(d.total)}{interval}{p} |",
        f"| 雑音の床 (片方だけが届いた source の再判定で動く見込み) | | | {floor} |",
        f"| 差のうち境界の論文 (on_topic {CUT:.1f}〜{CUT + BOUNDARY:.1f}) | | | {r.boundary} |",
        f"| store に対する新規率 (論文) | {_share(b.keys_new, b.keys)} | {_share(c.keys_new, c.keys)} | |",
        f"| prefilter の新しい判定 (窓で初めて判定に届く source) | {b.screened} | {c.screened} | {_signed(c.screened - b.screened)} ({_signed(per_run)}/run) |",
        f"| 未判定 (N_ot は下限) | {b.unjudged} | {c.unjudged} | |",
        f"| 初取得から判定まで | {_delay(b)} | {_delay(c)} | |",
        f"| 取りこぼし Chao2 (query net 全部) | {_chao(b.chao_all)} | {_chao(c.chao_all)} | |",
        f"| 取りこぼし Chao2 (seed の net を除く) | {_chao(b.chao_unseeded)} | {_chao(c.chao_unseeded)} | |",
        "",
        _verdict_line(r),
    ]
    if r.check.off:
        lines.append(
            "self-check の外れ: "
            + "、".join(f"{day} (再生だけ {x}・本番だけ {y})" for day, x, y in r.check.off)
        )
    lines += ["", "### 取得元ごとの N_ot (baseline → 候補、一意)", ""]
    cand_rows = {row.via: row for row in r.cand_rows}
    for row in r.base_rows:
        other = cand_rows.pop(row.via, SourceRow(row.via, 0, 0))
        lines.append(
            f"- {row.via}: {row.found} (一意 {row.unique}) → {other.found} (一意 {other.unique})"
        )
    for row in cand_rows.values():
        lines.append(f"- {row.via}: 0 → {row.found} (一意 {row.unique})")
    lines += ["", "### keyword クエリの履歴 (送信ごとの新規論文、直近 5 送信)", ""]
    for y in r.yields:
        if not y.sends:
            lines.append(f"- {query_line(y.query)}: 送信なし")
            continue
        mark = " **枯渇**" if y.exhausted else ""
        lines.append(
            f"- {query_line(y.query)}: 送信 {y.sends}、新規 {list(y.new[-5:])}、"
            f"うち問いに合う {list(y.ot[-5:])}{mark}"
        )
    rot = r.rotation
    lines += [
        "",
        f"### 次の {ROTATION_RUNS} run の見込み (送信あたりの歩留まり x 頻度。モデル)",
        "",
        f"- 1 run あたり新規で問いに合う論文: baseline {rot.base.per_run:.2f} → 候補 {rot.cand.per_run:.2f}"
        f" (差 {rot.delta:+.2f} [{rot.low:+.2f}, {rot.high:+.2f}])",
        _sends_line(rot.freed),
    ]
    if rot.cand.missing:
        lines.append(
            "- 履歴の無いクエリ (見込みに入らない): "
            + "、".join(query_line(q) for q in rot.cand.missing)
        )
    if r.snapshot is not None:
        s = r.snapshot
        lines += ["", f"### 今日の凍結 ({s.day}、各クエリ 1 回)", ""]
        lines += [
            f"- {query_line(q.query)}: 結果 {q.results}、store に無い {q.new}、うち問いに合う {q.ot}"
            for q in s.queries
        ]
        lines.append(
            f"- 次の run の送信で届く新規の問いに合う論文: baseline {s.base_next} ({s.base_sent} 送信) → "
            f"候補 {s.cand_next} ({s.cand_sent} 送信)"
        )
    if r.notes:
        lines += ["", *r.notes]
    return [*lines, ""]


def day_deltas(r: LineResult) -> list[int]:
    return [r.cand.per_day.get(d, 0) - r.base.per_day.get(d, 0) for d in r.days]


def pooled_lines(results: Sequence[LineResult]) -> list[str]:
    """Every line's run days as the pairs of one difference (a line-day is the unit)."""
    d = paired_diff([x for r in results for x in day_deltas(r)])
    base = sum(r.base.n_ot for r in results)
    cand = sum(r.cand.n_ot for r in results)
    screened = sum(r.cand.screened - r.base.screened for r in results)
    floor = sum(r.floor or 0.0 for r in results)
    boundary = sum(r.boundary for r in results)
    interval = (
        f" [{_signed(d.low)}, {_signed(d.high)}]"
        if d.low is not None and d.high is not None
        else ""
    )
    p = f" p={d.p:.3f}" if d.p is not None else ""
    return [
        f"## 全ライン ({len(results)} ライン、line-day {d.days})",
        "",
        f"- N_ot: {base} → {cand} ({_signed(d.total)}{interval}{p})、雑音の床 ±{floor:.1f}、"
        f"差のうち境界の論文 {boundary}",
        f"- prefilter の新しい判定: {_signed(screened)}",
        "",
    ]


def render(results: Sequence[LineResult], candidate: Candidate, spend: Spend) -> list[str]:
    head = [
        f"# jrp eval intake — {candidate.name} と baseline",
        "",
        "N_ot は prefilter (今日の open な問い、on_topic ≥ 0.5)を判定役にした数で、著者の読みではない。",
        "差は同じ凍結した取得の上の対の差で、日ごとの差の t 区間と符号反転の p を添える。",
        "",
    ]
    body = [line for r in results for line in render_line(r, candidate.name)]
    if len(results) > 1:
        body += pooled_lines(results)
    tail = [
        "## 費用",
        "",
        f"Jev: {spend.requests} 件を送信 (失敗 {spend.failed})、見積もり ${spend.estimate:.4f}、"
        f"input tokens {spend.input_tokens:,} = ${spend.usd:.4f} (上限 ${spend.cap:.2f})",
    ]
    return [*head, *body, *tail]


def _score_row(s: Score) -> dict[str, JsonValue]:
    return {
        "n_ot": s.n_ot,
        "reached": s.reached,
        "screened": s.screened,
        "unjudged": s.unjudged,
        "keys": s.keys,
        "keys_new": s.keys_new,
        "per_day": {d.isoformat(): n for d, n in sorted(s.per_day.items())},
        "chao2_missed": list(s.chao_all.missed) if s.chao_all else None,
        "chao2_unseeded_missed": list(s.chao_unseeded.missed) if s.chao_unseeded else None,
    }


def report_row(
    results: Sequence[LineResult], candidate: Candidate, spend: Spend, *, now: AwareDatetime
) -> dict[str, JsonValue]:
    return {
        "candidate": candidate.model_dump(mode="json"),
        "generated_at": now.isoformat(),
        "lines": [
            {
                "slug": r.slug,
                "window": [r.start.isoformat(), r.end.isoformat()],
                "baseline": _score_row(r.base),
                "candidate": _score_row(r.cand),
                "diff": {
                    "total": r.diff.total,
                    "low": r.diff.low,
                    "high": r.diff.high,
                    "p": r.diff.p,
                },
                "noise_floor": r.floor,
                "boundary": r.boundary,
                "self_check": {"days": r.check.days, "matched": r.check.matched},
                "rotation": {
                    "base_per_run": r.rotation.base.per_run,
                    "cand_per_run": r.rotation.cand.per_run,
                    "delta": r.rotation.delta,
                    "low": r.rotation.low,
                    "high": r.rotation.high,
                    "freed_per_run": r.rotation.freed,
                },
                "snapshot": None
                if r.snapshot is None
                else {
                    "day": r.snapshot.day.isoformat(),
                    "base_next": r.snapshot.base_next,
                    "cand_next": r.snapshot.cand_next,
                },
            }
            for r in results
        ],
        "jev": {
            "requests": spend.requests,
            "estimate_usd": spend.estimate,
            "input_tokens": spend.input_tokens,
        },
    }


def write_report(
    bench: Path,
    row: Mapping[str, JsonValue],
    lines: Sequence[str],
    *,
    name: str,
    now: AwareDatetime,
) -> Path:
    safe = re.sub(r"[^0-9A-Za-z_-]+", "-", name).strip("-") or "candidate"
    out = bench / "reports" / f"{now.date().isoformat()}-{safe}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(
        json.dumps(row, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out.with_suffix(".md")


# ------------------------------------------------------------------------------ the command


@dataclass(frozen=True)
class IntakeArgs:
    candidate: Path
    lines: tuple[str, ...]
    """Line slugs; none = every line the candidate names a query edit for, else every line."""
    days: int = DEFAULT_DAYS
    as_of: date | None = None
    bench: Path | None = None
    max_usd: float = 0.5
    freeze: bool = False
    jitter: int = JITTER_SOURCES


async def intake_command(env: Mapping[str, str], args: IntakeArgs) -> int:
    """0 when every line was compared; 2 for a candidate that does not load, a line that is
    not configured or has no open question, the Jev cap, or a freeze stopped by rate limits."""
    try:
        candidate = load_candidate(args.candidate)
    except (OSError, ValueError) as e:
        sys.stderr.write(f"jrp eval intake: {args.candidate}: {e}\n")
        return 2
    tracks = [t.slug for t in env_tracks(env)]
    slugs = list(args.lines) or [s for s in tracks if s in candidate.queries] or tracks
    bench = args.bench or eval_root(env) / "intake"
    spend = Spend(cap=args.max_usd)
    now = datetime.now().astimezone()
    results: list[LineResult] = []
    async with httpx2.AsyncClient(timeout=FREEZE_TIMEOUT_S) as http:
        for slug in slugs:
            try:
                results.append(
                    await evaluate_line(
                        env,
                        slug,
                        candidate,
                        bench=bench,
                        spend=spend,
                        http=http,
                        now=now,
                        days=args.days,
                        as_of=args.as_of,
                        jitter_n=args.jitter,
                        do_freeze=args.freeze,
                    )
                )
            except UnknownLine:
                sys.stderr.write(f"jrp eval intake: {slug}: config.toml に無いライン\n")
                return 2
            except (NoQuestions, BudgetExceeded, RateLimited) as e:
                sys.stderr.write(f"jrp eval intake: {slug}: {e}\n")
                return 2
    lines = render(results, candidate, spend)
    path = write_report(
        bench, report_row(results, candidate, spend, now=now), lines, name=candidate.name, now=now
    )
    sys.stdout.write("\n".join(lines) + f"\n\n→ {path}\n")
    return 0
