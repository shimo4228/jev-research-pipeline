"""Whether a line-run that finished did its job — the DEGRADED notification (runner.run_summary).

A line never stops for a broken dependency, by design (pipeline.run): a failed draft falls
back to the template section, a Jev failure becomes an unjudged item, a failed fetch an
operations line, the cost cap a partial note. So a run whose every draft failed on a
rejected Codex grant still exited 0 and its summary said only "N claims" — the degradation
was visible only in the note's `## 運用` block, which nobody reads before the prose. LineHealth
carries the counts behind those operations lines as values (never parsed back out of the
Japanese text) and `reasons()` names the ones that mean the note is not what a healthy run
writes. A rubric rejection that ends in the template is the ladder working, not a failure:
it is not counted; a rubric that could not judge (its Jev call failed) is. Likewise a rate
limit on a source asked without its optional key is the shared keyless pool's expected
answer (nets.NetOutcome.expected_limits), not a failed fetch.

A note can also fail quietly with nothing broken: no claim and no Review (the author gets a
note with nothing to read), or a line whose prose cites no claim on two of its runs in a
row (Review keeps coming but nothing reaches the body). Both are reasons too, for a line
with an open question. "Two runs" is the line's own Reports, not two calendar days: a
rotation line runs every few days.
"""

from dataclasses import dataclass
from typing import Final

UNJUDGED_SHARE: Final = 0.05
"""Jev failures on this share of (source, question) pairs or more is degraded. Healthy days
sit at 0-0.4% (production notes 2026-09-30 / 10-01): 5% is an outage, not noise."""

FAILURE_CHARS: Final = 120
"""The first failure is quoted to this length: enough to tell a timeout from a 500."""
WRITER_REFUSED: Final = (
    "writer refused its credentials — sign in again, or check the API key and its credits"
)
"""A refused login (Codex, Claude Code), a refused API key or spent API credits
(generation.client.auth_failure): each repeats on every draft until a human acts."""


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
    and not here, nor is a rate limit on a source asked without its optional key
    (nets._record_failure)."""
    failed_pairs: int = 0
    pairs: int = 0
    """(source, question) pairs whose Jev request failed, of those asked (the 未判定 share)."""
    cost_capped: bool = False
    """The cost cap stopped the line: the note is partial."""
    has_questions: bool = False
    """The line had an open question to answer. The note's two quiet reasons (empty note,
    no citation) are only reasons then: False (the default, as for a LineHealth built by
    hand) never sounds them."""
    claims: int = 0
    """Claims on the note (Report.claims)."""
    review: int = 0
    """Review entries on the note, after the note was fitted to its byte budget."""
    cited: int = 0
    """Claims the day's prose cites: the distinct [n] of each QuestionLog.text, summed over
    the questions (each question numbers its own claims from 1; generation.prose.citations).
    A template section cites nothing."""
    previous_cited: int | None = None
    """`cited` of the line's latest earlier Report, counted the same way from its
    QuestionLogs (a Report with none cites 0); None when the line has no earlier Report."""

    def reasons(self) -> list[str]:
        """One short phrase per kind of degradation, most actionable first; [] = healthy."""
        out: list[str] = []
        if self.writer_auth:
            out.append(WRITER_REFUSED)
        if self.prose_failures:
            first = self.prose_failures[0][:FAILURE_CHARS]
            out.append(f"prose failed {len(self.prose_failures)}/{self.drafts} drafts ({first})")
        if self.unverified:
            out.append(f"prose unverified (rubric Jev failed) in {self.unverified} section(s)")
        if self.pairs and self.failed_pairs / self.pairs >= UNJUDGED_SHARE:
            share = self.failed_pairs / self.pairs
            out.append(f"unjudged {self.failed_pairs}/{self.pairs} pairs ({share:.0%})")
        if self.has_questions and self.claims == 0 and self.review == 0:
            out.append("empty note (no claim, no review)")
        if self.has_questions and self.cited == 0 and self.previous_cited == 0:
            out.append("no citation 2 runs in a row")
        if self.fetch_failures:
            out.append(f"fetch failed: {', '.join(dict.fromkeys(self.fetch_failures))}")
        if self.cost_capped:
            out.append("cost cap reached (partial note)")
        return out
