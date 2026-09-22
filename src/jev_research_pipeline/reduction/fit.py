"""Reduction ①: refit each Jev function's thresholds on the author's labels (decision 6).

Features = the raw answers in Judgments (Noul p_yes, Score expected position, Choice
probability); target = gold Label (correct → the function should accept). Silver labels
(decision 5): rubric_claim axes that passed the agreement floor label unlabeled claims,
at SILVER_WEIGHT. Search = a grid over [0.05, 0.95]; ties prefer the value nearest the
current threshold. Output is a proposal file — thresholds in code are never changed here.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Final, Literal

from jev_research_pipeline.jev import (
    claim_detection,
    novelty,
    relevance_triage,
    rubric_claim,
    source_support,
    source_trust,
)
from jev_research_pipeline.jev.core import choice, noul, score, threshold
from jev_research_pipeline.model import Judgment, RubricAxis, Threshold
from jev_research_pipeline.model.jsonld import Value

from .log import DecisionLog, Verdict

GRID: Final = tuple(round(0.05 * i, 2) for i in range(1, 20))
SILVER_WEIGHT: Final = 0.5
MIN_GOLD: Final = 10
MIN_GAIN: Final = 0.01


class FitSpec(Value):
    """One fittable threshold: which feature it cuts and in which direction accepts."""

    function: str
    threshold: str
    accept_if: Literal[">=", "<"]


def _nou(key: str) -> Callable[[Judgment], float]:
    return lambda j: noul(j, key)


def _pos(key: str) -> Callable[[Judgment], float]:
    return lambda j: score(j, key).expected_position


def _p_same_claim(j: Judgment) -> float:
    rel = score(j, "relation")
    return rel.probabilities[rel.levels.index("same_claim")]


def _p_supports(j: Judgment) -> float:
    c = choice(j, "support")
    return c.probabilities[c.options.index("supports")]


# (spec, feature, the module's current thresholds). query_selection and rubric_report have
# no claim-level link and report_ordering has no cut-off, so they are not fitted here.
SPECS: Final[tuple[tuple[FitSpec, Callable[[Judgment], float], tuple[Threshold, ...]], ...]] = (
    (
        FitSpec(function="relevance_triage", threshold="relevant", accept_if=">="),
        _nou("relevant"),
        relevance_triage.THRESHOLDS,
    ),
    (
        FitSpec(function="relevance_triage", threshold="contains_evidence", accept_if=">="),
        _nou("contains_evidence"),
        relevance_triage.THRESHOLDS,
    ),
    (
        FitSpec(function="relevance_triage", threshold="prompt_injection", accept_if="<"),
        _nou("prompt_injection"),
        relevance_triage.THRESHOLDS,
    ),
    (
        FitSpec(function="claim_detection", threshold="checkable_claim", accept_if=">="),
        _nou("checkable_claim"),
        claim_detection.THRESHOLDS,
    ),
    (
        FitSpec(function="claim_detection", threshold="relevant", accept_if=">="),
        _nou("relevant"),
        claim_detection.THRESHOLDS,
    ),
    (
        FitSpec(function="novelty", threshold="same_claim", accept_if="<"),
        _p_same_claim,
        novelty.THRESHOLDS,
    ),
    (
        FitSpec(function="source_support", threshold="supports", accept_if=">="),
        _p_supports,
        source_support.THRESHOLDS,
    ),
    (
        FitSpec(function="source_trust", threshold="min_trust", accept_if=">="),
        _pos("trust"),
        source_trust.THRESHOLDS,
    ),
    *(
        (
            FitSpec(function="rubric_claim", threshold=axis, accept_if=">="),
            _pos(axis),
            rubric_claim.THRESHOLDS,
        )
        for axis in rubric_claim.AXES
    ),
)


class Proposal(Value):
    function: str
    threshold: str
    current: float
    proposed: float
    n_gold: int
    n_silver: int
    accuracy_current: float
    accuracy_proposed: float


def _silver(log: DecisionLog, trusted: tuple[RubricAxis, ...]) -> dict[str, Verdict]:
    """Unlabeled claims whose rubric_claim judgment passes every trusted axis → correct."""
    if not trusted:
        return {}
    gold = log.gold()
    out: dict[str, Verdict] = {}
    for j in log.judgments:
        if j.function != "rubric_claim" or j.subjects[0] in gold:
            continue
        ok = all(
            score(j, a).expected_position >= threshold(rubric_claim.THRESHOLDS, a) for a in trusted
        )
        out[j.subjects[0]] = "correct" if ok else "incorrect"
    return out


def _accuracy(samples: list[tuple[float, bool, float]], t: float, accept_if: str) -> float:
    total = sum(w for _, _, w in samples)
    hit = sum(w for x, want, w in samples if ((x >= t) if accept_if == ">=" else (x < t)) == want)
    return hit / total if total else 0.0


def fit_thresholds(
    log: DecisionLog,
    *,
    trusted: tuple[RubricAxis, ...] = (),
    min_gold: int = MIN_GOLD,
    min_gain: float = MIN_GAIN,
) -> list[Proposal]:
    gold = log.gold()
    silver = _silver(log, trusted)
    proposals: list[Proposal] = []
    for spec, feature, current_thresholds in SPECS:
        samples: list[tuple[float, bool, float]] = []
        n_gold = n_silver = 0
        for j in log.judgments:
            if j.function != spec.function:
                continue
            for claim_id in log.claims_of(j.subjects[0]):
                if claim_id in gold:
                    samples.append((feature(j), gold[claim_id] == "correct", 1.0))
                    n_gold += 1
                elif claim_id in silver:
                    samples.append((feature(j), silver[claim_id] == "correct", SILVER_WEIGHT))
                    n_silver += 1
        if n_gold < min_gold:
            continue
        current = threshold(current_thresholds, spec.threshold)
        acc_now = _accuracy(samples, current, spec.accept_if)
        best = max(GRID, key=lambda t: (_accuracy(samples, t, spec.accept_if), -abs(t - current)))
        acc_best = _accuracy(samples, best, spec.accept_if)
        if acc_best - acc_now >= min_gain:
            proposals.append(
                Proposal(
                    function=spec.function,
                    threshold=spec.threshold,
                    current=current,
                    proposed=best,
                    n_gold=n_gold,
                    n_silver=n_silver,
                    accuracy_current=round(acc_now, 4),
                    accuracy_proposed=round(acc_best, 4),
                )
            )
    return proposals


def write_proposal(directory: Path, proposals: list[Proposal], *, day: date) -> Path:
    """A reviewable diff proposal; the author applies it by editing the THRESHOLDS."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"thresholds-{day.isoformat()}.json"
    body = {
        "applied": False,
        "date": day.isoformat(),
        "proposals": [p.model_dump() for p in proposals],
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
