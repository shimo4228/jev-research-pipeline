"""`jrp eval gate --candidate <toml>`: one candidate against the baseline (today's run) on the
frozen set, dev and holdout apart (research report 2026-10-20-sx-eval-loop).

A candidate file:

    name = "keep-055"
    [thresholds.question_screening]   # any function of gate_policy.DEFAULTS, any of its names
    keep = 0.55
    [slots]
    order = "new_paper_first"         # or "score" (the run's)
    [ask.question_screening]          # optional: Jev is asked again (costs, capped)
    instructions = "..."

Thresholds and the slot order are recomputed from the stored Judgments: free. A reworded
screen asks Jev again over the rebuilt states of the labelled S sample, at most
`max_questions`, and those pairs alone are scored (the rest of the population has no answer
under the new wording).

S, per split: the pairs each policy keeps (exact, every pair), the pairs that change (kept by
one policy only), the pairs the candidate needs an unasked answer for, the author's ⭕ pairs
each keeps (a floor: a ⭕ only exists where the baseline delivered, so it can punish a
candidate that drops one and never reward one that adds, research report §A), and, from the
silver labels, precision of keep, recall, and their change, with the stratified Beta
interval (evals.sampling). X, per split: the claims each policy shows, the papers new to the
line among them (not shown by any earlier note of the line: the nearest offline stand-in for
O1, which counts first citations in prose), the papers new to their question, the change per
line-day with its paired bootstrap interval, the author's ⭕ claims shown, and the silver
precision of what is shown. The baseline's replay parity (gate_set) says how far the replay
can be trusted.

The verdict reads the holdout only. Regression: a change whose interval lies wholly below 0,
or fewer ⭕ kept or shown than the baseline. Hillclimbing (choosing among candidates on
these numbers) needs at least HILLCLIMB_MIN changed and labelled items in the holdout (80%
power at a 65% win rate, research report §C); below that the eval is a regression gate only
(harness rule evals.md), and a pick among candidates is the author's.
"""

import json
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jev_research_pipeline.jev import question_screening
from jev_research_pipeline.jev.core import Ask

from .gate_policy import (
    BASELINE,
    Judged_,
    Policy,
    SlotOrder,
    SOutcome,
    SPair,
    Split,
    XDay,
    s_outcome,
    validate,
    x_shown,
)
from .gate_set import GateSet
from .jitter import Floor, Reasked
from .sampling import Cell, Interval, estimate
from .silver import Answer, is_positive
from .stats import paired_bootstrap

HILLCLIMB_MIN: Final = 85
SPLITS: Final[tuple[Split, ...]] = ("dev", "holdout")
RESULTS_DIR: Final = "results"
SCORES_FILE: Final = "scores.jsonl"


class GateInputError(ValueError):
    """A candidate file or an argument the gate eval cannot use: said in one line."""


class AskOverride(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    instructions: str


class SlotsSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    order: SlotOrder = "score"


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    thresholds: dict[str, dict[str, float]] = Field(default_factory=dict[str, dict[str, float]])
    slots: SlotsSpec = SlotsSpec()
    ask: dict[str, AskOverride] = Field(default_factory=dict[str, AskOverride])

    def policy(self) -> Policy:
        try:
            validate(self.thresholds)
        except ValueError as e:
            raise GateInputError(str(e)) from e
        unknown = set(self.ask) - {"question_screening"}
        if unknown:
            raise GateInputError(
                f"an ask candidate is wired for question_screening only: {unknown}"
            )
        return Policy(overrides=self.thresholds, slots=self.slots.order)

    def screen_ask(self) -> Ask[question_screening.Answers] | None:
        over = self.ask.get("question_screening")
        if over is None:
            return None
        base = question_screening.ASK
        return Ask(
            function=base.function,
            version=f"{base.version}-{self.name}",
            output=base.output,
            instructions=over.instructions,
        )

    def changes(self) -> list[str]:
        """One line per change from the baseline."""
        out = [f"{fn}.{n} = {v}" for fn, vals in self.thresholds.items() for n, v in vals.items()]
        if self.slots.order != "score":
            out.append(f"slots.order = {self.slots.order}")
        out += [f"ask.{fn}: instructions を変える" for fn in self.ask]
        return out or ["なし(基準そのもの)"]


def load_candidate(path: Path) -> Candidate:
    """Raise GateInputError on a file that does not parse or names what the run does not have."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        candidate = Candidate.model_validate(raw)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as e:
        raise GateInputError(f"{path}: {e}") from e
    candidate.policy()
    return candidate


# ------------------------------------------------------------------------------------- S


@dataclass(frozen=True)
class SScore:
    pairs: int
    kept_b: int
    kept_c: int
    gained: int
    lost: int
    unasked: int
    gold_b: int
    gold_c: int
    gold: int
    labelled: int
    changed_labelled: int
    precision_b: Interval | None = None
    precision_c: Interval | None = None
    d_precision: Interval | None = None
    recall_b: Interval | None = None
    recall_c: Interval | None = None
    d_recall: Interval | None = None


def _cells(
    rows: Sequence[tuple[str, bool, bool, bool | None]],
) -> dict[str, Cell]:
    """(stratum, kept by baseline, kept by candidate, label or None) → cells keyed
    `stratum|b|c`."""
    counts: Counter[tuple[str, bool, bool]] = Counter()
    lab: Counter[tuple[str, bool, bool]] = Counter()
    pos: Counter[tuple[str, bool, bool]] = Counter()
    for stratum, b, c, y in rows:
        counts[(stratum, b, c)] += 1
        if y is not None:
            lab[(stratum, b, c)] += 1
            pos[(stratum, b, c)] += int(y)
    return {
        f"{s}|{int(b)}|{int(c)}": Cell(s, counts[k], lab[k], pos[k])
        for k in counts
        for s, b, c in [k]
    }


def _side(key: str, which: int) -> bool:
    return key.split("|")[1 + which] == "1"


def _label_estimates(
    cells: Mapping[str, Cell], kept_b: int, kept_c: int
) -> dict[str, Interval | None]:
    if not any(c.labelled for c in cells.values()):
        return {}
    every = {k: 1.0 for k in cells}
    tp_b = {k: 1.0 for k in cells if _side(k, 0)}
    tp_c = {k: 1.0 for k in cells if _side(k, 1)}
    out: dict[str, Interval | None] = {
        "precision_b": estimate(cells, tp_b, float(kept_b)) if kept_b else None,
        "precision_c": estimate(cells, tp_c, float(kept_c)) if kept_c else None,
        "recall_b": estimate(cells, tp_b, every),
        "recall_c": estimate(cells, tp_c, every),
        "d_recall": estimate(
            cells, {k: float(_side(k, 1)) - float(_side(k, 0)) for k in cells}, every
        ),
    }
    if kept_b and kept_c:
        out["d_precision"] = estimate(
            cells,
            {k: float(_side(k, 1)) / kept_c - float(_side(k, 0)) / kept_b for k in cells},
            1.0,
        )
    return out


def score_s(
    pairs: Sequence[SPair],
    outcomes: Mapping[str, tuple[SOutcome, SOutcome]],
    answers: Mapping[str, Answer],
) -> SScore:
    """One split's S numbers from each pair's (baseline, candidate) outcome."""
    rows: list[tuple[str, bool, bool, bool | None]] = []
    kept_b = kept_c = gained = lost = unasked = gold_b = gold_c = gold = changed = 0
    for p in pairs:
        if p.id not in outcomes:
            continue
        ob, oc = outcomes[p.id]
        b, c = ob == "keep", oc == "keep"
        y = is_positive(answers[p.id]) if p.id in answers else None
        rows.append((p.stratum, b, c, y))
        kept_b += b
        kept_c += c
        gained += c and not b
        lost += b and not c
        unasked += oc == "unasked"
        changed += (b != c) and y is not None
        if p.gold:
            gold += 1
            gold_b += b
            gold_c += c
    cells = _cells(rows)
    found = _label_estimates(cells, kept_b, kept_c)
    return SScore(
        pairs=len(rows),
        kept_b=kept_b,
        kept_c=kept_c,
        gained=gained,
        lost=lost,
        unasked=unasked,
        gold_b=gold_b,
        gold_c=gold_c,
        gold=gold,
        labelled=sum(1 for r in rows if r[3] is not None),
        changed_labelled=changed,
        **found,
    )


# ------------------------------------------------------------------------------------- X


@dataclass(frozen=True)
class XScore:
    days: int
    shown_b: int
    shown_c: int
    new_b: int
    new_c: int
    newq_b: int
    newq_c: int
    d_new: tuple[float, float, float] | None
    better: int
    worse: int
    gold_b: int
    gold_c: int
    gold: int
    labelled: int
    changed_labelled: int
    precision_b: Interval | None = None
    precision_c: Interval | None = None
    d_precision: Interval | None = None


def _new(day: XDay, shown: Sequence[Any]) -> tuple[int, int]:
    """(papers new to the line, (question, paper) new to the question) among `shown`."""
    line = {e.key for e in shown if e.key not in day.seen_line}
    question = {(e.question, e.key) for e in shown if e.key not in day.seen.get(e.question, ())}
    return len(line), len(question)


def score_x(
    days: Sequence[XDay], read: Judged_, policy: Policy, answers: Mapping[str, Answer]
) -> XScore:
    rows: list[tuple[str, bool, bool, bool | None]] = []
    diffs: list[float] = []
    totals = Counter[str]()
    for day in days:
        sb = x_shown(read, day, BASELINE)
        sc = x_shown(read, day, policy)
        nb, qb = _new(day, sb)
        nc, qc = _new(day, sc)
        totals.update(
            {
                "shown_b": len(sb),
                "shown_c": len(sc),
                "new_b": nb,
                "new_c": nc,
                "newq_b": qb,
                "newq_c": qc,
            }
        )
        diffs.append(float(nc - nb))
        ib, ic = {e.item for e in sb}, {e.item for e in sc}
        for e in day.entries:
            b, c = e.item in ib, e.item in ic
            y = is_positive(answers[e.item]) if e.item in answers else None
            rows.append((e.stratum, b, c, y))
            totals["changed"] += (b != c) and y is not None
            if e.gold:
                totals.update({"gold": 1, "gold_b": int(b), "gold_c": int(c)})
    cells = _cells(rows)
    labelled = sum(1 for r in rows if r[3] is not None)
    shown_b, shown_c = totals["shown_b"], totals["shown_c"]
    tp_b = {k: 1.0 for k in cells if _side(k, 0)}
    tp_c = {k: 1.0 for k in cells if _side(k, 1)}
    return XScore(
        days=len(days),
        shown_b=shown_b,
        shown_c=shown_c,
        new_b=totals["new_b"],
        new_c=totals["new_c"],
        newq_b=totals["newq_b"],
        newq_c=totals["newq_c"],
        d_new=paired_bootstrap(diffs) if diffs else None,
        better=sum(1 for d in diffs if d > 0),
        worse=sum(1 for d in diffs if d < 0),
        gold_b=totals["gold_b"],
        gold_c=totals["gold_c"],
        gold=totals["gold"],
        labelled=labelled,
        changed_labelled=totals["changed"],
        precision_b=estimate(cells, tp_b, float(shown_b)) if shown_b and labelled else None,
        precision_c=estimate(cells, tp_c, float(shown_c)) if shown_c and labelled else None,
        d_precision=estimate(
            cells,
            {k: float(_side(k, 1)) / shown_c - float(_side(k, 0)) / shown_b for k in cells},
            1.0,
        )
        if shown_b and shown_c and labelled
        else None,
    )


# ------------------------------------------------------------------------------- verdict


@dataclass(frozen=True)
class Verdict:
    regressions: tuple[str, ...]
    unmeasured: tuple[str, ...]
    hillclimb: bool
    changed_labelled: int

    @property
    def gate(self) -> str:
        if self.regressions:
            return "FAIL"
        return "PASS" if not self.unmeasured else "PASS(一部未測定)"


def _below(iv: Interval | None) -> bool:
    return iv is not None and iv.high < 0


def verdict_s(h: SScore) -> Verdict:
    regressions = [
        n for n, iv in (("precision", h.d_precision), ("recall", h.d_recall)) if _below(iv)
    ]
    if h.gold_c < h.gold_b:
        regressions.append("著者の ⭕")
    unmeasured = [
        n for n, iv in (("precision", h.d_precision), ("recall", h.d_recall)) if iv is None
    ]
    return Verdict(
        tuple(regressions),
        tuple(unmeasured),
        h.changed_labelled >= HILLCLIMB_MIN,
        h.changed_labelled,
    )


def verdict_x(h: XScore) -> Verdict:
    regressions: list[str] = []
    if h.d_new is not None and h.d_new[2] < 0:
        regressions.append("初出の論文")
    if _below(h.d_precision):
        regressions.append("precision")
    if h.gold_c < h.gold_b:
        regressions.append("著者の ⭕")
    unmeasured = ["precision"] if h.d_precision is None else []
    return Verdict(
        tuple(regressions),
        tuple(unmeasured),
        h.changed_labelled >= HILLCLIMB_MIN,
        h.changed_labelled,
    )


# ------------------------------------------------------------------------------- the run


@dataclass(frozen=True)
class GateReport:
    candidate: Candidate
    set_name: str
    frozen_at: datetime
    s: Mapping[Split, SScore]
    x: Mapping[Split, XScore]
    labels: int
    sample: int
    label_stop: str | None
    floor: Floor
    reasked: Reasked | None = None
    s_scope: str = "population"
    parity: Mapping[str, tuple[int, int]] = field(default_factory=dict[str, tuple[int, int]])

    @property
    def verdict(self) -> Mapping[str, Verdict]:
        return {"s": verdict_s(self.s["holdout"]), "x": verdict_x(self.x["holdout"])}


def s_outcomes(
    gs: GateSet, read: Judged_, policy: Policy, reasked: Reasked | None = None
) -> dict[str, tuple[SOutcome, SOutcome]]:
    """Pair id → (baseline, candidate) outcome. With fresh answers (an ask candidate), only the
    pairs whose first screening Judgment was asked again, and the candidate's screen route is
    read from the fresh answer."""
    out: dict[str, tuple[SOutcome, SOutcome]] = {}
    for p in gs.pairs:
        if reasked is None:
            out[p.id] = (s_outcome(read, p, BASELINE), s_outcome(read, p, policy))
            continue
        fresh = reasked.answers.get(p.screening[0]) if p.screening else None
        if fresh is None:
            continue
        # the baseline on the same single Judgment the candidate was asked over
        base = s_outcome(read, p.model_copy(update={"screening": p.screening[:1]}), BASELINE)
        before = s_outcome(read, p.model_copy(update={"screening": ()}), policy)
        if before != "unasked":
            out[p.id] = (base, before)
            continue
        route = question_screening.judged_route(fresh, policy.of("question_screening"))
        out[p.id] = (base, route if route in ("keep", "review") else "drop")
    return out


def score(
    gs: GateSet,
    candidate: Candidate,
    answers: Mapping[str, Answer],
    floor_: Floor,
    *,
    label_stop: str | None = None,
    reasked: Reasked | None = None,
) -> GateReport:
    policy = candidate.policy()
    read = Judged_(gs.judgments)
    outcomes = s_outcomes(gs, read, policy, reasked)
    s_scores: dict[Split, SScore] = {
        sp: score_s([p for p in gs.pairs if p.split == sp], outcomes, answers) for sp in SPLITS
    }
    x_scores: dict[Split, XScore] = {
        sp: score_x([d for d in gs.days if d.split == sp], read, policy, answers) for sp in SPLITS
    }
    return GateReport(
        candidate=candidate,
        set_name=gs.manifest.name,
        frozen_at=gs.manifest.created_at,
        s=s_scores,
        x=x_scores,
        labels=sum(1 for i in gs.materials if i in answers),
        sample=len(gs.materials),
        label_stop=label_stop,
        floor=floor_,
        reasked=reasked,
        s_scope="asked" if reasked is not None else "population",
        parity=dict(gs.manifest.parity),
    )


# ------------------------------------------------------------------------------- render


def _iv(iv: Interval | None, *, pct: bool = True) -> str:
    if iv is None:
        return "未測定"

    def f(v: float) -> str:
        return f"{v * 100:.0f}%" if pct else f"{v:+.2f}"

    return f"{f(iv.value)} [{f(iv.low)}, {f(iv.high)}]"


def _d(iv: Interval | None) -> str:
    if iv is None:
        return "未測定"
    return f"{iv.value * 100:+.1f} pt [{iv.low * 100:+.1f}, {iv.high * 100:+.1f}]"


def _row(label: str, cells: Sequence[str]) -> str:
    return f"| {label} | " + " | ".join(cells) + " |"


def _s_table(r: GateReport) -> list[str]:
    s = [r.s[sp] for sp in SPLITS]
    return [
        "| | dev | holdout |",
        "|---|---|---|",
        _row(
            "対" + ("(再質問した標本)" if r.s_scope == "asked" else ""),
            [f"{x.pairs:,}" for x in s],
        ),
        _row("keep(基準 → 候補)", [f"{x.kept_b:,} → {x.kept_c:,}" for x in s]),
        _row("変わる対(候補で増 / 減)", [f"+{x.gained} / -{x.lost}" for x in s]),
        _row("要 ask(凍結に答えが無い)", [str(x.unasked) for x in s]),
        _row(
            "著者の ⭕ を keep(基準 / 候補 / 全)",
            [f"{x.gold_b} / {x.gold_c} / {x.gold}" for x in s],
        ),
        _row("silver label(全 / 変わる対)", [f"{x.labelled} / {x.changed_labelled}" for x in s]),
        _row("precision of keep(基準)", [_iv(x.precision_b) for x in s]),
        _row("precision of keep(候補)", [_iv(x.precision_c) for x in s]),
        _row("Δ precision", [_d(x.d_precision) for x in s]),
        _row("recall(基準)", [_iv(x.recall_b) for x in s]),
        _row("recall(候補)", [_iv(x.recall_c) for x in s]),
        _row("Δ recall", [_d(x.d_recall) for x in s]),
    ]


def _per_day(d: tuple[float, float, float] | None) -> str:
    return "—" if d is None else f"{d[0]:+.2f} [{d[1]:+.2f}, {d[2]:+.2f}]"


def _x_table(r: GateReport) -> list[str]:
    x = [r.x[sp] for sp in SPLITS]
    return [
        "| | dev | holdout |",
        "|---|---|---|",
        _row("line-day", [str(v.days) for v in x]),
        _row("掲載 claim(基準 → 候補)", [f"{v.shown_b} → {v.shown_c}" for v in x]),
        _row("ラインで初出の論文(基準 → 候補)", [f"{v.new_b} → {v.new_c}" for v in x]),
        _row("Δ 初出の論文 / line-day", [_per_day(v.d_new) for v in x]),
        _row("line-day の増 / 減", [f"{v.better} / {v.worse}" for v in x]),
        _row("問いで初出の論文(基準 → 候補)", [f"{v.newq_b} → {v.newq_c}" for v in x]),
        _row(
            "著者の ⭕ を掲載(基準 / 候補 / 全)",
            [f"{v.gold_b} / {v.gold_c} / {v.gold}" for v in x],
        ),
        _row(
            "silver label(全 / 変わる claim)", [f"{v.labelled} / {v.changed_labelled}" for v in x]
        ),
        _row("precision of 掲載(基準)", [_iv(v.precision_b) for v in x]),
        _row("precision of 掲載(候補)", [_iv(v.precision_c) for v in x]),
        _row("Δ precision", [_d(v.d_precision) for v in x]),
    ]


def _verdict_line(v: Verdict) -> str:
    gate = f"回帰 gate {v.gate}"
    if v.regressions:
        gate += f"(holdout で悪化: {', '.join(v.regressions)})"
    elif v.unmeasured:
        gate += f"(未測定: {', '.join(v.unmeasured)})"
    climb = (
        "hillclimb 可"
        if v.hillclimb
        else f"hillclimb 不可(holdout の label 付きで変わる項目 {v.changed_labelled} < {HILLCLIMB_MIN}): 回帰 gate として読む"
    )
    return f"判定(holdout): {gate}。{climb}。"


def _cost_lines(r: GateReport) -> list[str]:
    jev = "Jev 再質問 0 問"
    if r.reasked is not None:
        price = f"${r.reasked.usd:.4f}" if r.reasked.price_known else "単価未設定"
        stop = "(上限で打ち切り)" if r.reasked.stopped else ""
        jev = f"Jev 再質問 {r.reasked.questions} 問({price}、失敗 {r.reasked.failed}){stop}"
    stop = f"、止まった理由: {r.label_stop}" if r.label_stop else ""
    silver = f"silver label {r.sample} 件中 {r.labels} 件{stop}"
    if not r.labels:
        silver += "(silver の行は未測定)"
    floor = r.floor
    noise = (
        "未測定(`jrp eval gate jitter`)"
        if not floor.judged
        else f"同じ state の聞き直しで {floor.judged} 件中 {floor.flips} 件の route が変わる "
        f"[{floor.interval[0] * 100:.0f}%, {floor.interval[1] * 100:.0f}%]、"  # pyright: ignore[reportOptionalSubscript]
        f"|Δ weighted| 平均 {floor.mean_abs_dw:.3f}"
    )
    return [f"費用: 再計算 $0 · {jev} · {silver}", f"雑音の床: {noise}"]


def render(r: GateReport) -> str:
    sx, xs = r.verdict["s"], r.verdict["x"]
    k, n = r.parity.get("screening", (0, 0))
    xk, xn = r.parity.get("x_sections", (0, 0))
    lines = [
        f"# gate eval: {r.candidate.name} と基準(set {r.set_name}、凍結 {r.frozen_at:%Y-%m-%d})",
        "",
        "変更: " + " / ".join(r.candidate.changes()),
        *_cost_lines(r),
        "",
        "## S 選別",
        "",
        *_s_table(r),
        "",
        _verdict_line(sx),
        f"基準の再計算: 保存済みの screening Decision {n} 件中 {k} 件を再現。",
        "",
        "## X 根拠化と掲載枠",
        "",
        *_x_table(r),
        "",
        _verdict_line(xs),
        f"基準の再生: QuestionLog {xn} 節中 {xk} 節で掲載 claim の集合が一致。",
        "",
        "区間は 95%。S と X の precision・recall は層別の Beta 事後分布(evals.sampling)、"
        "Δ 初出の論文は line-day の paired bootstrap。silver label は Claude Opus 5.5 で、"
        "著者の確認(`jrp eval gate check`)を通るまでは目安として読む。",
    ]
    return "\n".join(lines) + "\n"


def as_row(r: GateReport) -> dict[str, Any]:
    def plain(x: object) -> object:
        return asdict(x) if hasattr(x, "__dataclass_fields__") else x  # pyright: ignore[reportArgumentType]

    return {
        "candidate": r.candidate.model_dump(),
        "set": r.set_name,
        "s": {sp: plain(v) for sp, v in r.s.items()},
        "x": {sp: plain(v) for sp, v in r.x.items()},
        "labels": r.labels,
        "sample": r.sample,
        "label_stop": r.label_stop,
        "floor": plain(r.floor),
        "reasked": None
        if r.reasked is None
        else {
            "questions": r.reasked.questions,
            "failed": r.reasked.failed,
            "stopped": r.reasked.stopped,
            "usd": r.reasked.usd,
        },
        "verdict": {k: {**plain(v), "gate": v.gate} for k, v in r.verdict.items()},  # pyright: ignore[reportGeneralTypeIssues]
    }


def write(r: GateReport, root: Path, *, now: datetime) -> Path:
    """<set>/results/<candidate>.md and .json, and one appended row of <set>/scores.jsonl."""
    out = root / RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    md = out / f"{r.candidate.name}.md"
    md.write_text(render(r), encoding="utf-8")
    row = {"at": now.isoformat(), **as_row(r)}
    (out / f"{r.candidate.name}.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8"
    )
    with (root / SCORES_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return md
