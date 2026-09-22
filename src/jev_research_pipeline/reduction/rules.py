"""Reduction ③: rule-promotion candidates — proposal only, never applied (decision 6).

A Jev function is a candidate for a code rule when its decision outcome is predicted by a
code-computable feature of the judged subject's source — adapter (categorical), age in
days since published_at, text length — on at least `min_n` decisions at ≥ `min_agreement`,
AND the complement (the other decisions) does not already reach that rate for the same
outcome: a split that only restates a high base rate carries no information.
Each candidate is one line for the report's operations section; the author decides.
"""

from collections.abc import Callable
from datetime import date
from typing import Final

from jev_research_pipeline.model import Decision, SourceItem
from jev_research_pipeline.model.jsonld import Value

from .log import DecisionLog


class RuleConfig(Value):
    min_n: int = 30
    min_agreement: float = 0.95


NUMERIC_CUTS: Final = {
    "age_days": (7, 30, 90, 180, 365),
    "text_len": (100, 300, 1000, 3000),
}


def _numeric(name: str, today: date) -> Callable[[SourceItem], float | None]:
    if name == "age_days":
        return lambda s: (today - s.published_at).days if s.published_at else None
    return lambda s: float(len(s.text))


def _best_outcome(outcomes: list[str]) -> tuple[str, float]:
    top = max(set(outcomes), key=lambda o: (outcomes.count(o), o))
    return top, outcomes.count(top) / len(outcomes)


def _judged(log: DecisionLog) -> dict[str, list[tuple[Decision, SourceItem]]]:
    """Judged decisions per function, paired with the source of their first subject."""
    out: dict[str, list[tuple[Decision, SourceItem]]] = {}
    for d in log.decisions:
        src = log.source_of(d.subjects[0])
        if d.outcome != "unjudged" and src is not None:
            out.setdefault(d.function, []).append((d, src))
    return out


def _candidate(
    function: str, condition: str, outcomes: list[str], rest: list[str], config: RuleConfig
) -> str | None:
    if len(outcomes) < config.min_n or not rest:
        return None
    o, rate = _best_outcome(outcomes)
    if rate < config.min_agreement or rest.count(o) / len(rest) >= config.min_agreement:
        return None
    return f"rule 候補: {function} は {condition} のとき {o} (n={len(outcomes)}, 一致率 {rate:.2f})"


def _conditions(
    rows: list[tuple[Decision, SourceItem]], today: date
) -> list[tuple[str, list[str], list[str]]]:
    """(condition text, outcomes it selects, outcomes of the complement) per feature split."""
    splits: list[tuple[str, list[str], list[str]]] = [
        (
            f"adapter={a}",
            [d.outcome for d, s in rows if s.adapter == a],
            [d.outcome for d, s in rows if s.adapter != a],
        )
        for a in sorted({s.adapter for _, s in rows})
    ]
    for name, cuts in NUMERIC_CUTS.items():
        value = _numeric(name, today)
        values = [(d.outcome, v) for d, s in rows if (v := value(s)) is not None]
        for cut in cuts:
            hi = [o for o, v in values if v >= cut]
            lo = [o for o, v in values if v < cut]
            splits += [(f"{name}>={cut}", hi, lo), (f"{name}<{cut}", lo, hi)]
    return splits


def rule_candidates(log: DecisionLog, config: RuleConfig, *, today: date) -> list[str]:
    lines: list[str] = []
    for function, rows in sorted(_judged(log).items()):
        for condition, outcomes, rest in _conditions(rows, today):
            line = _candidate(function, condition, outcomes, rest, config)
            if line is not None:
                lines.append(line)
    return lines
