"""Labelled samples drawn by design, and design-based estimates over them (research report
2026-10-20-sx-eval-loop).

The population is known item by item (every pair's route is recomputed for free); only the
labels are sampled. A stratum is fixed when the set is frozen, from the baseline's own score
band, so a stratum that the current policy drops still gets labels (positivity by design).
An estimate splits each stratum into cells by what the policies being compared do with an
item (kept by the baseline, by the candidate, ...): a cell's population N is counted
exactly, and its positive rate is read from its labelled items.

The interval is Webber's (TOIS 2013): each cell's rate gets a Beta(0.5 + r, 0.5 + n - r)
posterior, the posteriors are drawn together, and the quantity is computed per draw. A cell
with no labelled item borrows its stratum's posterior (one draw shared by all such cells of
the stratum); a stratum with no labelled item at all leaves the estimate unmeasured.
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

DRAWS: Final = 10_000
"""Posterior draws per estimate: the 2.5% and 97.5% quantiles move by about 0.002 of the
interval's width between runs at this count."""


def draw(
    strata: Mapping[str, Sequence[str]], sizes: Mapping[str, int], seed: str
) -> dict[str, tuple[str, ...]]:
    """Per stratum, min(size, len) ids without replacement, from the ids sorted and seeded:
    the same population gives the same sample whatever order its ids came in."""
    out: dict[str, tuple[str, ...]] = {}
    for name in sorted(strata):
        ids = sorted(strata[name])
        k = min(sizes.get(name, 0), len(ids))
        out[name] = tuple(random.Random(f"{seed}/{name}").sample(ids, k))
    return out


def interleaved(sample: Mapping[str, Sequence[str]]) -> list[tuple[str, str]]:
    """(stratum, id) taking one from each stratum in turn: labelling in this order and
    stopping at a budget leaves every stratum about equally labelled."""
    out: list[tuple[str, str]] = []
    depth = max((len(v) for v in sample.values()), default=0)
    for i in range(depth):
        for name in sorted(sample):
            if i < len(sample[name]):
                out.append((name, sample[name][i]))
    return out


@dataclass(frozen=True)
class Cell:
    """The items of one stratum that the policies compared treat alike."""

    stratum: str
    population: int
    labelled: int = 0
    positive: int = 0


@dataclass(frozen=True)
class Interval:
    value: float
    low: float
    high: float


type Linear = Mapping[str, float]
"""Cell key → the coefficient of that cell's positives (in the population) in a sum."""


def _totals(cells: Mapping[str, Cell]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for c in cells.values():
        r, n = out.get(c.stratum, (0, 0))
        out[c.stratum] = (r + c.positive, n + c.labelled)
    return out


def _positives(cell: Cell, rate: float) -> float:
    """The cell's positives in the population: the labelled ones, plus the rest at `rate`."""
    return cell.positive + (cell.population - cell.labelled) * rate


def estimate(
    cells: Mapping[str, Cell],
    num: Linear,
    den: Linear | float,
    *,
    draws: int = DRAWS,
    seed: int = 0,
    confidence: float = 0.95,
) -> Interval | None:
    """Σ num[c]·Y_c / (Σ den[c]·Y_c, or the constant `den`), Y_c being cell c's positives in
    the population; None when a cell it needs has no labelled item in its whole stratum, or
    the denominator is 0. The value uses each cell's own rate r/n (its stratum's when n = 0);
    the interval is the quantiles of the same quantity over the posterior draws."""
    used: set[str] = {k for k, a in num.items() if a}
    if not isinstance(den, float | int):
        used |= {k for k, a in den.items() if a}
    strata = _totals(cells)
    if any(strata[cells[k].stratum][1] == 0 for k in used if cells[k].population):
        return None

    def value(rates: Mapping[str, float]) -> float | None:
        top = sum(a * _positives(cells[k], rates[k]) for k, a in num.items() if a)
        bottom = (
            float(den)
            if isinstance(den, float | int)
            else sum(a * _positives(cells[k], rates[k]) for k, a in den.items() if a)
        )
        return top / bottom if bottom else None

    def own(k: str) -> tuple[int, int]:
        c = cells[k]
        return (c.positive, c.labelled) if c.labelled else strata[c.stratum]

    point = value({k: own(k)[0] / own(k)[1] if own(k)[1] else 0.0 for k in cells})
    if point is None:
        return None
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(draws):
        shared = {s: rng.betavariate(0.5 + r, 0.5 + n - r) for s, (r, n) in strata.items() if n}
        rates = {
            k: rng.betavariate(0.5 + c.positive, 0.5 + c.labelled - c.positive)
            if c.labelled
            else shared.get(c.stratum, 0.0)
            for k, c in cells.items()
        }
        v = value(rates)
        if v is not None:
            values.append(v)
    if not values:
        return None
    values.sort()
    tail = (1.0 - confidence) / 2.0
    low = values[min(len(values) - 1, int(tail * len(values)))]
    high = values[min(len(values) - 1, int((1.0 - tail) * len(values)))]
    return Interval(point, low, high)
