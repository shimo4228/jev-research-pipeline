"""Intervals the evals share. Wilson's and Garwood's come from the weekly review, which owns
them (pipeline.wbr); they are re-exported, not moved."""

import random
from collections.abc import Sequence

from jev_research_pipeline.pipeline.wbr import poisson_interval, wilson

__all__ = ["paired_bootstrap", "poisson_interval", "wilson"]


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
