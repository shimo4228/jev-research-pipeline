"""What `jrp eval gate` prints, and the one async step of scoring (an ask candidate asks Jev).
The modules it reads hold the rules; this holds the wording."""

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Final

import httpx2

from jev_research_pipeline.note_text import Lang

from .gate_score import Candidate, GateInputError, GateReport, score
from .gate_set import Frozen_, GateSet
from .jitter import HTTP_TIMEOUT_S, JitterResult, floor, reask
from .silver import LabelResult, labels

ASK_MAX_QUESTIONS: Final = 600
"""An ask candidate's default cap: about 85 sampled pairs at 7 questions each."""
KEY_ENV: Final = "ANTHROPIC_API_KEY"

STOPS: Final[Mapping[str, str]] = {
    "no-key": "未測定(ANTHROPIC_API_KEY なし)",
    "bad-budget": "JRP_EVAL_WEEKLY_USD が数でない",
    "budget": "今週の上限に達した",
    "rate-limit": "429(再試行しない)",
    "credit": "API クレジットが尽きた",
    "auth": "key が拒否された",
    "deadline": "時間切れ",
}


def _pct(k: int, n: int) -> str:
    return f"{k}/{n} ({k / n * 100:.1f}%)" if n else "0/0"


def freeze_lines(frozen: Frozen_) -> list[str]:
    m = frozen.manifest
    c = m.counts
    rebuild = {fn: [0, 0] for fn in ("prefilter", "screening")}
    per_line: list[str] = []
    for line, fns in m.rebuild.items():
        for fn, (k, n) in fns.items():
            rebuild[fn][0] += k
            rebuild[fn][1] += n
        k, n = fns.get("screening", (0, 0))
        per_line.append(f"{line} {k / n * 100:.0f}%" if n else f"{line} -")
    pk, pn = m.parity.get("screening", (0, 0))
    xk, xn = m.parity.get("x_sections", (0, 0))
    strata = " / ".join(f"{k} {v:,}" for k, v in m.strata["s"].items())
    return [
        f"eval set {m.name} → {frozen.root}",
        f"S: 対 {c['s_pairs']:,}(dev {c.get('s_dev', 0):,} / holdout {c.get('s_holdout', 0):,})。層: {strata}",
        f"X: line-day {c['x_days']}(dev {c.get('x_dev', 0)} / holdout {c.get('x_holdout', 0)})、"
        f"候補の claim {c['x_entries']:,}",
        "state の再構成: prefilter の問いの順 "
        f"{_pct(*rebuild['prefilter'])}、screening {_pct(*rebuild['screening'])}"
        f"({', '.join(per_line)})",
        f"基準の parity: screening Decision {_pct(pk, pn)}、掲載枠 {_pct(xk, xn)} 節",
        f"label の標本: S {sum(m.sizes['s'].values())} / X {sum(m.sizes['x'].values())}"
        f"(材料のある項目 {c['materials']})",
    ]


def label_lines(r: LabelResult) -> list[str]:
    budget = "—" if r.budget is None else f"${r.budget:.2f}"
    head = (
        f"silver label: {r.asked} 件を予定、{r.labelled} 件を付けた(既存 {r.already}、失敗 {r.failed})。"
        f"費用 ${r.usd:.2f}(今週 ${r.week_usd:.2f} / 上限 {budget})"
    )
    return [head] + ([f"止まった理由: {STOPS.get(r.stop, r.stop)}"] if r.stop else [])


def jitter_lines(r: JitterResult) -> list[str]:
    if r.reasked is None:
        return ["jitter: 未測定(TYPESAFE_API_KEY なし)"]
    got = r.reasked
    flips = sum(1 for row in r.rows if row["route_old"] != row["route_new"])
    price = f"${got.usd:.4f}" if got.price_known else "単価未設定(JRP_JEV_USD_PER_QUESTION)"
    lines = [
        f"jitter: {r.asked} 件を予定、{len(r.rows)} 件を同じ state で聞き直し、route が変わったのは {flips} 件。"
        f"Jev {got.questions} 問({price}、失敗 {got.failed})"
        + ("、上限で打ち切り" if got.stopped else ""),
    ]
    f = r.floor
    if f.judged and f.interval is not None:
        lines.append(
            f"雑音の床(これまでの {f.runs} 日分): {f.judged} 件中 {f.flips} 件 "
            f"[{f.interval[0] * 100:.0f}%, {f.interval[1] * 100:.0f}%]、"
            f"|Δ weighted| 平均 {f.mean_abs_dw:.3f} / 最大 {f.max_abs_dw:.3f}"
        )
    return lines


async def score_candidate(
    gs: GateSet,
    candidate: Candidate,
    env: Mapping[str, str],
    ledger: Path,
    *,
    now: datetime,
    lang: Lang,
    max_questions: int | None = None,
) -> GateReport:
    """Score `candidate` (evals.gate_score.score); an ask candidate first asks Jev over the
    sampled S pairs' first screening states, at most `max_questions`."""
    answers = labels(ledger, gs.manifest.name, lang)
    stop = (
        None if answers else ("no-key" if not env.get(KEY_ENV) else "未ラベル(jrp eval gate label)")
    )
    ask = candidate.screen_ask()
    reasked = None
    if ask is not None:
        sampled = {i for ids in gs.sample.get("s", {}).values() for i in ids}
        jids = [p.screening[0] for p in gs.pairs if p.id in sampled and p.screening]
        async with httpx2.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
            reasked = await reask(
                ask,
                gs.states(),
                jids,
                env,
                http=http,
                now=now,
                max_questions=max_questions or ASK_MAX_QUESTIONS,
            )
        if reasked is None:
            raise GateInputError("an ask candidate asks Jev again: TYPESAFE_API_KEY is not set")
    return score(
        gs,
        candidate,
        answers,
        floor(gs.root),
        label_stop=STOPS.get(stop or "", stop),
        reasked=reasked,
    )
