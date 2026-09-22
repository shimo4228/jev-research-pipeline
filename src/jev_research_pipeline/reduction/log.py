"""The decision log: a line partition indexed for reduction (decision 6).

Links every Jev judgment/decision to the claims (and through them the author's Labels)
and to the source whose code-computable features rules may use:
    source-subject functions  → claims cut from that source
    unit-subject functions    → claims made from that unit
    claim-subject functions   → subjects[0] (the claim judged; for pairs, the new claim)
"""

from dataclasses import dataclass, field
from typing import Literal

from jev_research_pipeline.model import (
    Claim,
    Decision,
    GraphNodeType,
    Judgment,
    Label,
    SourceItem,
    Unit,
    kind_of,
)
from jev_research_pipeline.store import Partition

type Verdict = Literal["correct", "incorrect"]


@dataclass
class DecisionLog:
    claims: dict[str, Claim] = field(default_factory=dict[str, Claim])
    units: dict[str, Unit] = field(default_factory=dict[str, Unit])
    sources: dict[str, SourceItem] = field(default_factory=dict[str, SourceItem])
    judgments: list[Judgment] = field(default_factory=list[Judgment])
    decisions: list[Decision] = field(default_factory=list[Decision])
    labels: list[Label] = field(default_factory=list[Label])

    @classmethod
    def from_nodes(cls, nodes: list[GraphNodeType]) -> "DecisionLog":
        log = cls()
        for n in nodes:
            match n:
                case Claim():
                    log.claims[n.id] = n
                case Unit():
                    log.units[n.id] = n
                case SourceItem():
                    log.sources[n.id] = n
                case Judgment():
                    log.judgments.append(n)
                case Decision():
                    log.decisions.append(n)
                case Label():
                    log.labels.append(n)
                case _:
                    pass
        return log

    @classmethod
    def from_partition(cls, partition: Partition) -> "DecisionLog":
        return cls.from_nodes(list(partition.load().values()))

    def claims_of(self, subject: str) -> list[str]:
        match kind_of(subject):
            case "claim":
                return [subject]
            case "unit":
                return [c.id for c in self.claims.values() if c.unit == subject]
            case "source":
                return [
                    c.id
                    for c in self.claims.values()
                    if (u := self.units.get(c.unit)) is not None and u.source == subject
                ]
            case _:
                return []

    def source_of(self, subject: str) -> SourceItem | None:
        match kind_of(subject):
            case "source":
                return self.sources.get(subject)
            case "unit":
                u = self.units.get(subject)
                return self.sources.get(u.source) if u else None
            case "claim":
                c = self.claims.get(subject)
                return self.source_of(c.unit) if c else None
            case _:
                return None

    def current(self, function: str, bundle_sha256: str) -> list[Judgment]:
        """One judgment per subject tuple: this bundle's wording, latest judged. Re-runs and
        stale wordings never count twice (fits and cases read only these)."""
        latest: dict[tuple[str, ...], Judgment] = {}
        for j in sorted(self.judgments, key=lambda j: (j.judged_at, j.id)):
            if j.function == function and j.bundle_sha256 == bundle_sha256:
                latest[j.subjects] = j
        return list(latest.values())

    def gold(self) -> dict[str, Verdict]:
        """claim @id → verdict. A claim labeled in several reports keeps the latest harvest.
        Labels on a question-day or a source are not claim gold; the ones they propagated
        to their claims are, and those are stored as claim labels of their own."""
        latest: dict[str, Label] = {}
        for lb in sorted(self.labels, key=lambda lb: lb.harvested_at):
            if kind_of(lb.subject) == "claim":
                latest[lb.subject] = lb
        return {c: lb.verdict for c, lb in latest.items()}

    def labeled_pairs(self, function: str) -> list[tuple[Judgment, Verdict]]:
        gold = self.gold()
        pairs: list[tuple[Judgment, Verdict]] = []
        for j in self.judgments:
            if j.function != function:
                continue
            for claim_id in self.claims_of(j.subjects[0]):
                if claim_id in gold:
                    pairs.append((j, gold[claim_id]))
        return pairs
