"""Unit cutting: code splits source text into verbatim sentence spans (judgment map)."""

from jev_research_pipeline.model import SourceItem
from jev_research_pipeline.pipeline.units import split_units

from . import builders as b


def _src(text: str) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url="https://arxiv.org/abs/u",
        title="t",
        text=text,
        fetched_at=b.T0,
    )


def test_sentences_are_verbatim_spans():
    src = _src("Agents need long-term memory. Narrow questions beat broad prompts! Is that so?")
    units = split_units(src, min_chars=10)
    assert [u.text for u in units] == [
        "Agents need long-term memory.",
        "Narrow questions beat broad prompts!",
        "Is that so?",
    ]
    assert all(u.matches(src) for u in units)


def test_japanese_sentence_boundaries():
    units = split_units(
        _src("狭い質問に分解すると判定が安定する。確率は較正されている。"), min_chars=5
    )
    assert [u.text for u in units] == [
        "狭い質問に分解すると判定が安定する。",
        "確率は較正されている。",
    ]


def test_short_fragments_are_dropped():
    units = split_units(_src("Hi. This sentence is long enough to count."), min_chars=20)
    assert [u.text for u in units] == ["This sentence is long enough to count."]


def test_long_runs_are_capped():
    units = split_units(_src("word " * 400), min_chars=10, max_chars=200)
    assert all(len(u.text) <= 200 for u in units)
    assert units
