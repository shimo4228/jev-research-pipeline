"""Line rotation: each tick runs the next `per_tick` lines of a fixed config order.

next_lines() is pure; advance_rotation() reads/writes the RotationCursor in the
pipeline partition. The cursor advances when lines are picked, not when their runs
succeed — a failed line-run is retried by idempotent stages on its next turn, and one
bad line never blocks the others.
"""

from typing import Annotated

from pydantic import AwareDatetime, Field, model_validator

from jev_research_pipeline.model import RotationCursor
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.model.nodes import Slug

from .graph import GraphStore


class RotationConfig(Value):
    """Invariant: order is non-empty, unique, kebab slugs (= store partition names)."""

    order: tuple[Slug, ...] = Field(min_length=1)
    per_tick: Annotated[int, Field(ge=1)] = 3

    @model_validator(mode="after")
    def _unique(self) -> "RotationConfig":
        if len(set(self.order)) != len(self.order):
            raise ValueError("rotation order must be unique")
        return self


def next_lines(
    order: tuple[str, ...], next_slug: str | None, k: int
) -> tuple[tuple[str, ...], str]:
    """(lines to run now, slug to resume at). Starts at the head when the cursor is unset
    or names a line no longer in `order`. Never picks a line twice in one tick."""
    start = order.index(next_slug) if next_slug in order else 0
    n = min(k, len(order))
    picked = tuple(order[(start + i) % len(order)] for i in range(n))
    return picked, order[(start + n) % len(order)]


def advance_rotation(
    store: GraphStore, config: RotationConfig, now: AwareDatetime
) -> tuple[str, ...]:
    pipeline = store.pipeline()
    cursor = pipeline.get(RotationCursor.id_for())
    current = cursor.next_slug if isinstance(cursor, RotationCursor) else None
    picked, resume = next_lines(config.order, current, config.per_tick)
    pipeline.put([RotationCursor.new(next_slug=resume, updated_at=now)])
    return picked
