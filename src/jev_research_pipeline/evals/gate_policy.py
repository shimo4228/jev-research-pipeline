"""What a policy does to a frozen item: the route of an S pair and the claims an X day shows,
recomputed from the stored Judgments with the module rules (research report
2026-10-20-sx-eval-loop).

A policy is the run's thresholds with some replaced, plus the slot order. Recomputing needs
no Jev: only a Judgment the run never asked is missing, and an item that needs one is
"unasked" (counted, never guessed). The baseline policy (no replacement, slots by score) is
what the run does today; the set's parities check that it reproduces the stored Decisions
and the notes.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from jev_research_pipeline.jev import (
    claim_detection,
    judged_of,
    novelty,
    question_prefilter,
    question_screening,
    relevance_triage,
    source_trust,
)
from jev_research_pipeline.jev.core import Judged
from jev_research_pipeline.model import Judgment, Threshold
from jev_research_pipeline.pipeline.run import capped

type Fn = Literal[
    "question_prefilter",
    "relevance_triage",
    "source_trust",
    "question_screening",
    "claim_detection",
    "novelty",
]
type SlotOrder = Literal["score", "new_paper_first"]
type Split = Literal["dev", "holdout"]
type SOutcome = Literal["keep", "review", "drop", "prefilter", "safe", "unasked"]
"""keep / review / drop = the screen's route; prefilter = the prefilter did not pass it for
this question; safe = triage or trust rejected its source; unasked = the policy needs an
answer the run never asked."""

DEFAULTS: Final[Mapping[Fn, tuple[Threshold, ...]]] = MappingProxyType(
    {
        "question_prefilter": question_prefilter.THRESHOLDS,
        "relevance_triage": relevance_triage.THRESHOLDS,
        "source_trust": source_trust.THRESHOLDS,
        "question_screening": question_screening.THRESHOLDS,
        "claim_detection": claim_detection.THRESHOLDS,
        "novelty": novelty.THRESHOLDS,
    }
)
"""The run's thresholds, read from the modules: a policy replaces values, never names."""

WINDOW_DAYS: Final = 7
"""A pair counts as kept when a screening Judgment within this many days of its first one
routes keep: the length of the weekly review's p_sel window (pipeline.wbr counts from the
paper's first fetch)."""

_RANK: Final[Mapping[str, int]] = MappingProxyType({"keep": 3, "review": 2, "drop": 1})


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SPair(Frozen):
    """One (source, question) pair the prefilter judged: the S population."""

    id: str
    line: str
    source: str
    question: str
    day: date
    """The day of the prefilter Judgment that judged the pair."""
    split: Split
    prefilter: str
    """That prefilter Judgment's @id."""
    index: int
    """The pair's question is `q{index}_on_topic` in it."""
    triage: str | None = None
    trust: str | None = None
    """The source's first relevance_triage / source_trust Judgment, if the run asked one."""
    screening: tuple[str, ...] = ()
    """Current-version screening Judgments of the pair, first one first, within WINDOW_DAYS."""
    stratum: str
    gold: bool | None = None
    """True: an author's ⭕ reached the pair; False: an ❌; None: neither."""


class XEntry(Frozen):
    """One claim novelty judged on its line-day, before the slot cap."""

    claim: str
    question: str
    source: str
    key: str
    """The paper key of its source (pipeline.wbr.paper_key)."""
    detection: str
    novelty: str
    gold: bool | None = None
    stratum: str = ""
    """The item's X stratum, from the first day it is in a pool (evals.gate_set)."""

    @property
    def item(self) -> str:
        return f"{self.claim}|{self.question}"


class XDay(Frozen):
    """One line-day: its claim pool, what its note showed, and what earlier notes showed."""

    id: str
    line: str
    day: date
    split: Split
    entries: tuple[XEntry, ...]
    shown: Mapping[str, tuple[str, ...]]
    """Question → the claims its QuestionLog of the day lists."""
    seen: Mapping[str, tuple[str, ...]]
    """Question → the paper keys its QuestionLogs listed on earlier days."""
    seen_line: tuple[str, ...] = ()
    """The paper keys any QuestionLog of the line listed on earlier days."""


def validate(overrides: Mapping[str, Mapping[str, float]]) -> None:
    """Raise ValueError on a function or threshold name the run does not have."""
    for fn, values in overrides.items():
        if fn not in DEFAULTS:
            raise ValueError(f"unknown function {fn!r}; known: {', '.join(DEFAULTS)}")
        names = {t.name for t in DEFAULTS[fn]}  # pyright: ignore[reportArgumentType]
        for name, value in values.items():
            if name not in names:
                raise ValueError(f"{fn} has no threshold {name!r}; it has {', '.join(names)}")
            if not math.isfinite(value):
                raise ValueError(f"{fn}.{name} must be a finite number, not {value}")


@dataclass(frozen=True)
class Policy:
    overrides: Mapping[str, Mapping[str, float]] = field(
        default_factory=dict[str, Mapping[str, float]]
    )
    slots: SlotOrder = "score"

    def of(self, fn: Fn) -> tuple[Threshold, ...]:
        mine = self.overrides.get(fn, {})
        return tuple(Threshold(name=t.name, value=mine.get(t.name, t.value)) for t in DEFAULTS[fn])

    def loosens(self, fn: Fn) -> bool:
        """A replaced cut below the run's: items the run rejected there may now pass, and
        their next Judgment was never asked."""
        base = {t.name: t.value for t in DEFAULTS[fn]}
        return any(v < base[n] for n, v in self.overrides.get(fn, {}).items())


BASELINE: Final = Policy()


class Judged_:
    """judged_of() over a set's Judgments, each read once."""

    def __init__(self, judgments: Mapping[str, Judgment]) -> None:
        self.judgments = judgments
        self._cache: dict[tuple[str, str], Any] = {}

    def get(self, fn: str, jid: str | None) -> Judged[Any] | None:
        if jid is None or jid not in self.judgments:
            return None
        key = (fn, jid)
        if key not in self._cache:
            j = self.judgments[jid]
            self._cache[key] = judged_of(_ask(fn, j), j)
        return self._cache[key]


def _ask(fn: str, j: Judgment) -> Any:  # noqa: ANN401 - each function's own Ask type
    match fn:
        case "question_prefilter":
            return question_prefilter.ask(sum(1 for a in j.answers if a.key.endswith("_on_topic")))
        case "relevance_triage":
            return relevance_triage.ASK
        case "source_trust":
            return source_trust.ASK
        case "question_screening":
            return question_screening.ASK
        case "claim_detection":
            return claim_detection.ASK
        case _:
            return novelty.ASK


def screen_route(read: Judged_, pair: SPair, policy: Policy) -> str | None:
    """The best route over the pair's screening Judgments (keep > review > drop); None when
    it has none."""
    routes = [
        question_screening.judged_route(judged, policy.of("question_screening"))
        for jid in pair.screening
        if (judged := read.get("question_screening", jid)) is not None
    ]
    return max(routes, key=lambda r: _RANK.get(r, 0)) if routes else None


def s_outcome(read: Judged_, pair: SPair, policy: Policy) -> SOutcome:
    """What `policy` does with the pair, stage by stage (module docstring of
    pipeline.run._gather: prefilter → triage → trust → screen)."""
    pf = read.get("question_prefilter", pair.prefilter)
    if pf is None:
        return "unasked"
    n = sum(1 for a in pf.judgment.answers if a.key.endswith("_on_topic"))
    if pair.index not in question_prefilter.passing(pf, n, policy.of("question_prefilter")):
        return "prefilter"
    for fn, jid, rule in (
        ("relevance_triage", pair.triage, relevance_triage.rule),
        ("source_trust", pair.trust, source_trust.rule),
    ):
        judged = read.get(fn, jid)
        if judged is None:
            return "unasked"
        if not rule(judged, policy.of(fn))[0]:  # pyright: ignore[reportArgumentType]
            return "safe"
    route = screen_route(read, pair, policy)
    if route is None:
        return "unasked"
    return route if route in ("keep", "review", "drop") else "drop"


def weighted_best(read: Judged_, pair: SPair) -> float | None:
    """The highest weighted score over the pair's screening Judgments whose gates pass
    (baseline thresholds); None when none passes."""
    scores = [
        question_screening.weighted(judged)
        for jid in pair.screening
        if (judged := read.get("question_screening", jid)) is not None
        and question_screening.gates_pass(judged.output)
    ]
    return max(scores) if scores else None


def x_pool(read: Judged_, day: XDay, policy: Policy) -> list[XEntry]:
    """The day's entries that pass claim_detection and novelty under `policy`."""
    out: list[XEntry] = []
    for e in day.entries:
        cd = read.get("claim_detection", e.detection)
        nov = read.get("novelty", e.novelty)
        if cd is None or nov is None:
            continue
        if (
            claim_detection.rule(cd, policy.of("claim_detection"))[0]
            and novelty.rule(nov, policy.of("novelty"))[0]
        ):
            out.append(e)
    return out


def score(read: Judged_, e: XEntry) -> float:
    """claim_detection's Decision score, min(bears_on, checkable): the run's slot order."""
    cd = read.get("claim_detection", e.detection)
    return claim_detection.rule(cd)[1] if cd is not None else 0.0


def x_shown(read: Judged_, day: XDay, policy: Policy) -> list[XEntry]:
    """The entries the note shows under `policy` (pipeline.run.capped)."""
    pool = x_pool(read, day, policy)

    def rank(e: XEntry) -> tuple[float, ...]:
        if policy.slots == "new_paper_first":
            return (0.0 if e.key not in day.seen.get(e.question, ()) else 1.0, -score(read, e))
        return (-score(read, e),)

    return capped(
        pool,
        sorted({e.question for e in pool}),
        question=lambda e: e.question,
        source=lambda e: e.source,
        rank=rank,
    )
