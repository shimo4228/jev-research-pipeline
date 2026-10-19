"""Discovery meters: which net is earning its budget (packet "Discovery" 6).

Read from the run and the store, one line each in the operations section:
- sources per net: what each net returned this run (after the run's dedupe and the
  firehose cap).
- accepted-claim share per net: of today's accepted claims, which net found the source.
  A net whose share stays at zero is a net to cut.
- OpenAlex credits spent, when any were.

No line reports convergence or says when the search is done. In particular "n
consecutive irrelevant results" is not a convergence signal (Repke 2026), so no meter
counts or prints one.
"""

from collections.abc import Mapping, Sequence

from jev_research_pipeline import note_text as t
from jev_research_pipeline.model import Claim, DiscoveryNet, SourceItem, Unit
from jev_research_pipeline.note_text import Lang


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


def lines(
    per_net_sources: Mapping[DiscoveryNet, int],
    shares: Mapping[DiscoveryNet, float],
    *,
    openalex_credits: int,
    lang: Lang = t.DEFAULT_LANG,
) -> list[str]:
    """The operations section's discovery block."""
    none = t.NONE_WORD(lang)
    counts = ", ".join(f"{net} {n}" for net, n in sorted(per_net_sources.items()))
    net_shares = ", ".join(f"{net} {share:.2f}" for net, share in sorted(shares.items()))
    out = [
        t.NET_SOURCES(lang, counts=counts or none),
        t.NET_SHARES(lang, shares=net_shares or none),
    ]
    if openalex_credits:
        out.append(f"openalex credit: {openalex_credits}")
    return out
