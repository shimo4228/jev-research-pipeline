"""Shared state pieces for Jev bundles.

State is filtered by code before Jev sees it (vendor jaggedness: large irrelevant state).
Source text is cut to an excerpt window *around the span being judged* (a claim late in a
long source must still be inside what Jev reads); the line is reduced to its name and
concept vocabulary. relevance_triage is the exception: it reads the whole source, since
anything in it can later become a unit and must pass the injection check.
"""

from typing import Final

from pydantic import Field, JsonValue

from jev_research_pipeline.model import Line, SourceItem
from jev_research_pipeline.model.jsonld import Value

EXCERPT_CHARS: Final = 2000


class LineContext(Value):
    """A line plus its read-only concept vocabulary (concept names from the line's
    graph.jsonld; loaded by code, never written back — decision 2)."""

    line: Line
    vocabulary: tuple[str, ...] = Field(min_length=1)


def line_state(ctx: LineContext) -> dict[str, JsonValue]:
    return {"name": ctx.line.name, "vocabulary": list(ctx.vocabulary)}


def excerpt(text: str, around: tuple[int, int] | None = None, limit: int = EXCERPT_CHARS) -> str:
    """`text` if it fits, else a `limit`-char window centred on `around` (default: the start)."""
    if len(text) <= limit:
        return text
    start, end = around if around is not None else (0, 0)
    lo = max(0, min((start + end) // 2 - limit // 2, len(text) - limit))
    hi = lo + limit
    return ("… " if lo > 0 else "") + text[lo:hi] + (" …" if hi < len(text) else "")


def best_match_span(text: str, probe: str) -> tuple[int, int] | None:
    """Where in `text` the longest words of `probe` first occur (code pre-pass, no model)."""
    folded = text.casefold()
    for word in sorted({w.casefold() for w in probe.split() if len(w) > 3}, key=len, reverse=True):
        at = folded.find(word)
        if at >= 0:
            return at, at + len(word)
    return None


def source_state(
    source: SourceItem, *, around: tuple[int, int] | None = None
) -> dict[str, JsonValue]:
    return {
        "title": source.title,
        "url": source.url,
        "adapter": source.adapter,
        "published": source.published_at.isoformat() if source.published_at else None,
        "excerpt": excerpt(source.text, around),
    }


def full_source_state(source: SourceItem) -> dict[str, JsonValue]:
    """The whole source, unexcerpted — for checks that must see every character."""
    return {
        "title": source.title,
        "url": source.url,
        "adapter": source.adapter,
        "text": source.text,
    }
