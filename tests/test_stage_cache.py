"""Idempotent stage cache: (stage, input content hash) -> output @ids; done stages skip."""

import hashlib
from pathlib import Path

from jev_research_pipeline.store import GraphStore, StageCache, input_sha256

from . import builders as b


def test_input_hash_ignores_key_order():
    assert input_sha256({"a": 1, "b": [1, 2]}) == input_sha256({"b": [1, 2], "a": 1})


def test_input_hash_distinguishes_values_and_list_order():
    base = input_sha256({"a": [1, 2]})
    assert base != input_sha256({"a": [2, 1]})
    assert base != input_sha256({"a": [1, 2, 3]})
    assert input_sha256("1") != input_sha256(1)


def test_input_hash_is_reproducible_across_processes():
    # Golden canonical form: sorted keys, compact separators, UTF-8, no ASCII escaping.
    # A change here invalidates every cached stage — do it deliberately.
    canonical = '{"n":2,"text":"検索"}'
    assert input_sha256({"text": "検索", "n": 2}) == hashlib.sha256(canonical.encode()).hexdigest()


def test_miss_then_hit(tmp_path: Path):
    part = GraphStore(tmp_path).line("akc")
    part.put([b.claim()])
    cache = StageCache(part)
    h = input_sha256({"unit": b.unit().id})
    assert cache.lookup("claim_detection", h) is None
    cache.record("claim_detection", h, (b.claim().id,), b.T0)
    assert StageCache(GraphStore(tmp_path).line("akc")).lookup("claim_detection", h) == (
        b.claim().id,
    )


def test_empty_output_is_still_a_hit(tmp_path: Path):
    # A stage that ran and produced nothing (e.g. no claim in a unit) must not rerun.
    cache = StageCache(GraphStore(tmp_path).line("akc"))
    cache.record("claim_detection", "f" * 64, (), b.T0)
    assert cache.lookup("claim_detection", "f" * 64) == ()


def test_stage_names_are_separate_keys(tmp_path: Path):
    cache = StageCache(GraphStore(tmp_path).line("akc"))
    cache.record("claim_detection", "f" * 64, (), b.T0)
    assert cache.lookup("novelty", "f" * 64) is None


def test_dangling_outputs_are_a_miss(tmp_path: Path):
    # Record exists but an output node is gone from the partition → rerun the stage.
    cache = StageCache(GraphStore(tmp_path).line("akc"))
    cache.record("claim_detection", "f" * 64, (b.claim().id,), b.T0)
    assert cache.lookup("claim_detection", "f" * 64) is None
