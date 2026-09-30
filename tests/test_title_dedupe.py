"""One work under several URLs is triaged and screened once per run (run.same_title_merged)."""

from jev_research_pipeline.model import AdapterKind, SourceItem
from jev_research_pipeline.pipeline.run import same_title_merged, title_key

from . import builders as b

PTSL = "Pattern Theory of Selflessness: How Meditation May Transform the Self-Pattern"


def _source(
    url: str, title: str, text: str = "x" * 300, adapter: AdapterKind = "web_search"
) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI, adapter=adapter, url=url, title=title, text=text, fetched_at=b.T0
    )


def test_one_paper_on_four_portals_is_one_key():
    # the ans line, 2026-09-26: Tavily returned these four as four sources
    titles = [
        f"{PTSL} - Israeli Research Community Portal",
        f"{PTSL} | mijn-bsl",
        f"{PTSL} - the University of Groningen research portal",
        PTSL.lower(),
    ]
    keys = {title_key(_source(f"https://e{i}.org/p", t)) for i, t in enumerate(titles)}
    assert len(keys) == 1


def test_a_short_head_keeps_its_suffix():
    home = _source("https://a.org", "Home - Example Lab")
    other = _source("https://b.org", "Home - Other Lab")
    assert title_key(home) != title_key(other)


def test_only_web_titles_lose_a_suffix():
    # an arXiv title with a dash in it is the title
    one = _source("https://arxiv.org/abs/1", f"{PTSL} - Part One", adapter="arxiv")
    two = _source("https://arxiv.org/abs/2", f"{PTSL} - Part Two", adapter="arxiv")
    assert title_key(one) != title_key(two)


def test_a_japanese_title_is_not_folded_to_nothing():
    one = _source("https://note.com/a", "AIで作りたいものがなくなった")
    two = _source("https://note.com/b", "AIに頼みたいことが尽きた")
    assert title_key(one)
    assert title_key(one) != title_key(two)


def test_copies_merge_into_the_longest_text_with_every_question():
    arxiv = _source("https://arxiv.org/abs/2609.1", "Agent Memory", "a" * 300, "arxiv")
    hf = _source("https://huggingface.co/papers/2609.1", "Agent memory", "b" * 900, "hf_papers")
    other = _source("https://arxiv.org/abs/2609.2", "Something Else", "c" * 300, "arxiv")
    unpassed = _source("https://arxiv.org/abs/2609.3", "Agent Memory", "d" * 2000, "arxiv")
    passing = {arxiv.id: [0], hf.id: [2], other.id: [1]}
    kept, hits, merged = same_title_merged([arxiv, other, hf, unpassed], passing)
    assert [s.id for s in kept] == [hf.id, other.id]  # first copy's place, longest text
    assert hits == {hf.id: [0, 2], other.id: [1]}
    assert merged == 1  # a source the prefilter did not pass is not a copy


def test_nothing_to_merge_changes_nothing():
    a = _source("https://arxiv.org/abs/2609.1", "Agent Memory", adapter="arxiv")
    kept, hits, merged = same_title_merged([a], {a.id: [0, 1]})
    assert (kept, hits, merged) == ([a], {a.id: [0, 1]}, 0)
