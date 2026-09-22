"""Rotation: the next k lines from a fixed config order, cursor persisted in the store."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from jev_research_pipeline.model import RotationCursor
from jev_research_pipeline.store import GraphStore, RotationConfig, advance_rotation, next_lines

ORDER = ("a", "b", "c", "d", "e")
T1 = datetime(2026, 9, 23, 6, 0, tzinfo=UTC)


def test_first_tick_starts_at_the_head():
    assert next_lines(ORDER, None, 3) == (("a", "b", "c"), "d")


def test_wraps_around():
    assert next_lines(ORDER, "d", 3) == (("d", "e", "a"), "b")


def test_every_line_runs_equally_often():
    counts: dict[str, int] = dict.fromkeys(ORDER, 0)
    cursor: str | None = None
    for _ in range(5):
        picked, cursor = next_lines(ORDER, cursor, 3)
        for slug in picked:
            counts[slug] += 1
    assert set(counts.values()) == {3}


def test_k_larger_than_order_picks_each_once():
    assert next_lines(("a", "b"), "b", 3) == (("b", "a"), "b")


def test_unknown_cursor_restarts_at_head():
    # A line removed from config must not stall the rotation.
    assert next_lines(ORDER, "gone", 2) == (("a", "b"), "c")


def test_config_order_nonempty_unique_kebab():
    with pytest.raises(ValidationError):
        RotationConfig(order=())
    with pytest.raises(ValidationError):
        RotationConfig(order=("a", "a"))
    with pytest.raises(ValidationError):
        RotationConfig(order=("A b",))
    with pytest.raises(ValidationError):
        RotationConfig(order=("a",), per_tick=0)
    assert RotationConfig(order=("a",)).per_tick == 3


def test_advance_persists_cursor(tmp_path: Path):
    store = GraphStore(tmp_path)
    config = RotationConfig(order=ORDER)
    assert advance_rotation(store, config, T1) == ("a", "b", "c")
    assert advance_rotation(GraphStore(tmp_path), config, T1) == ("d", "e", "a")
    cursor = store.pipeline().get(RotationCursor.id_for())
    assert isinstance(cursor, RotationCursor)
    assert cursor.next_slug == "b"
    assert cursor.updated_at == T1
