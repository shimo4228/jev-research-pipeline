"""Discovery meters: which net is earning its budget, and whether the search is converging.

Three numbers per run (packet "Discovery" 6), all read from the store:
- accepted-claim share per net: of today's accepted claims, which net found the source.
  A net whose share stays at zero is a net to cut.
- distinct OpenAlex topic count over accepted sources: a *falling* count is the
  convergence alarm, because a search that only exploits ends up in one cluster.
- Time-to-Discovery: the median days from fetching a source to the author marking it
  worth reading (ASReview), so a net that finds the right paper late is visible.
- per-net new-accept rate with a convergence fit f = 1 - exp(-n/tau) (Undermind's shape):
  tau is fitted from the cumulative accepts of the last runs, and f says how much of what
  this net can find has been found. It is reported as an estimate, never as a stop
  condition — and "n consecutive irrelevant results" is explicitly NOT reported as
  convergence (Repke 2026 shows it is not one).
"""

import math
from collections.abc import Mapping, Sequence
from typing import Final

from jev_research_pipeline.adapters import openalex
from jev_research_pipeline.model import Claim, DiscoveryNet, Label, SourceItem, Unit

MIN_POINTS: Final = 3
"""Below this many runs a fit is a line through noise; the meter says so instead."""


def source_of(
    claim: Claim, units: Mapping[str, Unit], sources: Mapping[str, SourceItem]
) -> SourceItem | None:
    unit = units.get(claim.unit)
    return sources.get(unit.source) if unit is not None else None


def share_per_net(
    claims: Sequence[Claim], units: Mapping[str, Unit], sources: Mapping[str, SourceItem]
) -> dict[DiscoveryNet, float]:
    """Of the accepted claims, the fraction whose source each net found."""
    counts: dict[DiscoveryNet, int] = {}
    total = 0
    for claim in claims:
        source = source_of(claim, units, sources)
        if source is None:
            continue
        counts[source.net] = counts.get(source.net, 0) + 1
        total += 1
    return {net: n / total for net, n in counts.items()} if total else {}


def topic_clusters(sources: Sequence[SourceItem]) -> int:
    """Distinct OpenAlex topic ids among the sources that carry one."""
    return len({t for s in sources if (t := openalex.topic_of(s.text)) is not None})


def convergence(cumulative: Sequence[int]) -> float | None:
    """f = 1 - exp(-n/tau) at the latest n, with tau fitted by least squares on log(1 - f).

    `cumulative` is the accepted-claim count after each run, oldest first. Returns None
    when there are too few runs, or when the curve has not bent yet (nothing to fit)."""
    if len(cumulative) < MIN_POINTS or cumulative[-1] <= 0:
        return None
    ceiling = cumulative[-1] * 1.2  # the asymptote is unknown; assume a fifth is left
    numerator = denominator = 0.0
    for n, total in enumerate(cumulative, start=1):
        remaining = 1.0 - min(total / ceiling, 0.999)
        numerator += n * -math.log(remaining)
        denominator += n * n
    if numerator <= 0 or denominator == 0:
        return None
    tau = denominator / numerator
    return 1.0 - math.exp(-len(cumulative) / tau) if tau > 0 else None


def time_to_discovery(
    labels: Sequence[Label],
    sources: Mapping[str, SourceItem],
    claims: Mapping[str, Claim],
    units: Mapping[str, Unit],
) -> float | None:
    """Median days between fetching a source and the author marking it worth reading
    (ASReview's Time-to-Discovery). Only ⭕ counts: a ❌ is not a discovery, and an
    unticked source has not been discovered yet, so it is not a zero either."""
    days: list[float] = []
    for label in labels:
        if label.verdict != "correct":
            continue
        source = sources.get(label.subject)
        if source is None and (claim := claims.get(label.subject)) is not None:
            source = source_of(claim, units, sources)
        if source is not None:
            days.append((label.harvested_at - source.fetched_at).total_seconds() / 86400.0)
    if not days:
        return None
    days.sort()
    middle = len(days) // 2
    return days[middle] if len(days) % 2 else (days[middle - 1] + days[middle]) / 2


def lines(
    per_net_sources: Mapping[DiscoveryNet, int],
    shares: Mapping[DiscoveryNet, float],
    *,
    clusters: int,
    previous_clusters: int | None,
    fit: float | None,
    openalex_credits: int,
    ttd: float | None = None,
) -> list[str]:
    """The operations section's discovery block."""
    out = [
        "net 取得数: "
        + (", ".join(f"{net} {n}" for net, n in sorted(per_net_sources.items())) or "なし"),
        "net 採用率: "
        + (", ".join(f"{net} {share:.2f}" for net, share in sorted(shares.items())) or "なし"),
        f"topic クラスタ数: {clusters}"
        + (
            f" (前回 {previous_clusters}{'・減少' if clusters < previous_clusters else ''})"
            if previous_clusters is not None
            else ""
        ),
    ]
    out.append(
        f"収束推定 f: {fit:.2f}" if fit is not None else "収束推定 f: データ不足 (3 run 未満)"
    )
    out.append(
        f"Time-to-Discovery 中央値: {ttd:.1f} 日"
        if ttd is not None
        else "Time-to-Discovery: 未計測"
    )
    if openalex_credits:
        out.append(f"openalex credit: {openalex_credits}")
    return out
