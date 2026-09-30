"""Whether a line-run that finished did its job — the DEGRADED notification (runner.run_summary).

A line never stops for a broken dependency, by design (pipeline.run): a failed draft falls
back to the template section, a Jev failure becomes an unjudged item, a failed fetch an
operations line, the cost cap a partial note. So a run whose every draft failed on a
rejected Codex grant still exited 0 and its summary said only "N claims" — the degradation
was visible only in the note's `## 運用` block, which nobody reads before the prose. LineHealth
carries the counts behind those operations lines as values (never parsed back out of the
Japanese text) and `reasons()` names the ones that mean the note is not what a healthy run
writes. A rubric rejection that ends in the template is the ladder working, not a failure:
it is not counted; a rubric that could not judge (its Jev call failed) is.
"""

from dataclasses import dataclass
from typing import Final

UNJUDGED_SHARE: Final = 0.05
"""Jev failures on this share of (source, question) pairs or more is degraded. Healthy days
sit at 0-0.4% (production notes 2026-09-30 / 10-01): 5% is an outage, not noise."""

FAILURE_CHARS: Final = 120
"""The first failure is quoted to this length: enough to tell a timeout from a 500."""


@dataclass(frozen=True)
class LineHealth:
    drafts: int = 0
    """Prose drafts attempted (one or two per question that moved)."""
    prose_failures: tuple[str, ...] = ()
    """ProseResult.failure of every draft that produced no text (timeout, HTTP error, auth,
    empty answer) — the template fallback that is not the rubric's choice."""
    writer_auth: bool = False
    """At least one draft failed on the writer's credentials (generation.client.auth_failure)."""
    unverified: int = 0
    """Sections that fell to the template because the rubric's Jev call failed: the draft
    was written but could not be checked, so it was not published."""
    fetch_failures: tuple[str, ...] = ()
    """`<net>/<adapter> <reason>` of every failed fetch; a skip for an unset key is intended
    and not here (nets._record_failure)."""
    failed_pairs: int = 0
    pairs: int = 0
    """(source, question) pairs whose Jev request failed, of those asked (the 未判定 share)."""
    cost_capped: bool = False
    """The cost cap stopped the line: the note is partial."""

    def reasons(self) -> list[str]:
        """One short phrase per kind of degradation, most actionable first; [] = healthy."""
        out: list[str] = []
        if self.writer_auth:
            out.append("writer auth failed — sign in again")
        if self.prose_failures:
            first = self.prose_failures[0][:FAILURE_CHARS]
            out.append(f"prose failed {len(self.prose_failures)}/{self.drafts} drafts ({first})")
        if self.unverified:
            out.append(f"prose unverified (rubric Jev failed) in {self.unverified} section(s)")
        if self.pairs and self.failed_pairs / self.pairs >= UNJUDGED_SHARE:
            share = self.failed_pairs / self.pairs
            out.append(f"unjudged {self.failed_pairs}/{self.pairs} pairs ({share:.0%})")
        if self.fetch_failures:
            out.append(f"fetch failed: {', '.join(dict.fromkeys(self.fetch_failures))}")
        if self.cost_capped:
            out.append("cost cap reached (partial note)")
        return out
