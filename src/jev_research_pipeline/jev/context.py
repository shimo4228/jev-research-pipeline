"""Shared state pieces for Jev bundles.

State is filtered by code before Jev sees it (vendor jaggedness: large irrelevant state).
Source text is cut to an excerpt; the line is reduced to its name and concept vocabulary.
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


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + " …"


def source_state(source: SourceItem) -> dict[str, JsonValue]:
    return {
        "title": source.title,
        "url": source.url,
        "adapter": source.adapter,
        "published": source.published_at.isoformat() if source.published_at else None,
        "excerpt": excerpt(source.text),
    }
