"""Intervals the evals share (research reports docs/plans/research/2026-10-20-sx-eval-loop.md
and 2026-10-20-intake-eval.md).

- wilson / poisson_interval: the weekly review's (pipeline.wbr), which owns them; re-exported,
  not moved, so every eval prints the same interval for a share and for a count.
- paired_bootstrap: the mean of per-cluster differences with its percentile bootstrap
  (jrp eval gate; a guide below about 30 clusters).
- chao2: a lower bound on the items no sampling unit found, from the incidence counts.
  Convention of Chao & Colwell 2017 (SORT 41(1), eq. 2b) and vegan::specpool:
  S_obs + A·Q1²/(2·Q2) when Q2 > 0, S_obs + A·Q1(Q1-1)/2 when Q2 = 0, A = (T-1)/T; Chao's
  1987 variance; the log-normal interval, whose lower end never falls below S_obs. Premises
  the pipeline breaks: the units are not independent random draws with one detection law
  (nets are seeded by accepted papers, so positively dependent), which pushes the estimate
  down — it is read as "at least", and only toward "coverage is missing", never "exhausted".
  Below MIN_UNITS units nothing is printed: Chao 1987 asks for 5 and its own simulation at
  t = 10 put the point estimate under the truth in 8 of 8 populations.
- paired_diff: a difference of two configurations summed over days, each day's difference
  being paired on the same frozen items. The t interval on the mean daily difference times
  the number of days, and the sign-flip randomization p (Smucker, Allan & Carterette, SIGIR
  2009: the randomization test, with the t test acceptable; the bootstrap reads too narrow
  with few units).
- expected_flips: the judge's noise floor on a difference — over the items judged fresh for
  one side, the chance that a re-ask of the same state lands on the other side of the cut,
  read off the measured |Δp| of identical states.
"""

import itertools
import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from jev_research_pipeline.pipeline.wbr import Z95, poisson_interval, wilson

__all__ = [
    "MIN_UNITS",
    "Chao2",
    "PairedDiff",
    "chao2",
    "expected_flips",
    "paired_bootstrap",
    "paired_diff",
    "poisson_interval",
    "wilson",
]

MIN_UNITS: Final = 10
EXACT_FLIPS: Final = 16
"""Up to this many days the sign-flip p enumerates every sign pattern; beyond, it draws."""
FLIP_DRAWS: Final = 20_000
_T975: Final = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)  # fmt: skip
"""Student's t, two-sided 95%, df 1..30."""


def t975(df: int) -> float:
    """Student's t quantile 0.975; past df 30 the Cornish-Fisher term (2.039 at 30)."""
    if df < 1:
        raise ValueError("df must be >= 1")
    if df <= len(_T975):
        return _T975[df - 1]
    return Z95 + (Z95**3 + Z95) / (4.0 * df)


@dataclass(frozen=True)
class Chao2:
    s_obs: int
    q1: int
    """Items found by exactly one unit."""
    q2: int
    """Items found by exactly two units."""
    units: int
    estimate: float
    variance: float
    low: float
    high: float

    @property
    def missed(self) -> tuple[float, float, float]:
        """(point, low, high) of the items no unit found: at least, under positive dependence."""
        return self.estimate - self.s_obs, self.low - self.s_obs, self.high - self.s_obs


def chao2_from(s_obs: int, q1: int, q2: int, *, factor: float) -> tuple[float, float]:
    """(estimate, variance) for the counts; `factor` is (T-1)/T (1 = Chao 1987 as written)."""
    a = factor
    if q1 == 0:
        return float(s_obs), 0.0
    if q2 > 0:
        r = q1 / q2
        estimate = s_obs + a * q1 * q1 / (2.0 * q2)
        variance = q2 * (0.25 * a * a * r**4 + a * a * r**3 + 0.5 * a * r * r)
        return estimate, variance
    estimate = s_obs + a * q1 * (q1 - 1) / 2.0
    variance = (
        0.25 * a * a * q1 * (2 * q1 - 1) ** 2
        + 0.5 * a * q1 * (q1 - 1)
        - 0.25 * a * a * q1**4 / estimate
    )
    return estimate, max(variance, 0.0)


def lognormal_interval(s_obs: int, estimate: float, variance: float) -> tuple[float, float]:
    """Chao's 1987 interval: log(estimate - S_obs) taken as normal; the low end ≥ S_obs."""
    missed = estimate - s_obs
    if missed <= 0:
        return float(s_obs), float(s_obs)
    r = math.exp(Z95 * math.sqrt(math.log(1.0 + variance / (missed * missed))))
    return s_obs + missed / r, s_obs + missed * r


def chao2(incidence: Iterable[int], units: int) -> Chao2 | None:
    """`incidence`: for each item found, the number of units that found it (≥ 1). None
    below MIN_UNITS units."""
    if units < MIN_UNITS:
        return None
    counts = [c for c in incidence if c > 0]
    q1 = sum(1 for c in counts if c == 1)
    q2 = sum(1 for c in counts if c == 2)
    s_obs = len(counts)
    estimate, variance = chao2_from(s_obs, q1, q2, factor=(units - 1) / units)
    low, high = lognormal_interval(s_obs, estimate, variance)
    return Chao2(s_obs, q1, q2, units, estimate, variance, low, high)


@dataclass(frozen=True)
class PairedDiff:
    total: float
    """Σ over days of (candidate - baseline)."""
    days: int
    low: float | None
    high: float | None
    """The t interval of the total; None with fewer than 2 days."""
    p: float | None
    """Two-sided sign-flip randomization p; None when every day's difference is 0."""


def _sign_flip_p(deltas: Sequence[float], seed: int) -> float:
    observed = abs(math.fsum(deltas))
    tolerance = 1e-9 * max(1.0, observed)
    if len(deltas) <= EXACT_FLIPS:
        patterns = itertools.product((1.0, -1.0), repeat=len(deltas))
        hits = sum(
            1
            for signs in patterns
            if abs(math.fsum(s * d for s, d in zip(signs, deltas, strict=True)))
            >= observed - tolerance
        )
        return hits / 2 ** len(deltas)
    rng = random.Random(seed)
    hits = sum(
        1
        for _ in range(FLIP_DRAWS)
        if abs(math.fsum(d if rng.random() < 0.5 else -d for d in deltas)) >= observed - tolerance
    )
    return (hits + 1) / (FLIP_DRAWS + 1)


def paired_diff(deltas: Sequence[float], *, seed: int = 0) -> PairedDiff:
    """The difference summed over paired days (module docstring)."""
    n = len(deltas)
    total = math.fsum(deltas)
    p = None if all(d == 0 for d in deltas) else _sign_flip_p(deltas, seed)
    if n < 2:
        return PairedDiff(total, n, None, None, p)
    mean = total / n
    sd = math.sqrt(math.fsum((d - mean) ** 2 for d in deltas) / (n - 1))
    half = t975(n - 1) * sd / math.sqrt(n)
    return PairedDiff(total, n, n * (mean - half), n * (mean + half), p)


def expected_flips(margins: Iterable[float], jitter: Sequence[float]) -> float:
    """Σ over items of P(|Δp| ≥ margin), with P read off the measured `jitter` (|Δp| of
    identical states re-asked). `margins`: each item's |p - cut| at its closest question.
    0 when no jitter was measured — the caller says the floor is unmeasured."""
    if not jitter:
        return 0.0
    ordered = sorted(jitter)
    n = len(ordered)
    total = 0.0
    for m in margins:
        below = sum(1 for j in ordered if j < m)
        total += (n - below) / n
    return total


def paired_bootstrap(
    diffs: Sequence[float], *, reps: int = 2000, seed: int = 0, confidence: float = 0.95
) -> tuple[float, float, float]:
    """(mean, low, high) of the mean of `diffs`, one difference (candidate - baseline) per
    cluster, by the percentile bootstrap over clusters with random.Random(seed). Small
    numbers of clusters cover poorly (research report 2026-10-20-sx-eval-loop, Bowyer): read
    the interval as a guide below about 30 clusters."""
    if not diffs:
        raise ValueError("paired_bootstrap needs at least one cluster")
    n = len(diffs)
    mean = sum(diffs) / n
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    tail = (1.0 - confidence) / 2.0
    low = means[min(reps - 1, int(tail * reps))]
    high = means[min(reps - 1, int((1.0 - tail) * reps))]
    return mean, low, high
