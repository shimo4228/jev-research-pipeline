"""Derived FTS5 claim index: Japanese bigrams + unicode61, rebuildable from the store."""

import sqlite3
from pathlib import Path

import pytest

from jev_research_pipeline.model import Claim, SourceItem, Unit
from jev_research_pipeline.store import ClaimIndex, GraphStore, index_tokens

from . import builders as b

TEXTS = (
    "言語モデルの検索拡張は幻覚を減らす。",
    "Retrieval-augmented generation reduces hallucination in language models.",
    "エージェントの記憶は検索で補える。",
    "Narrow questions beat one broad question.",
)


def _claims() -> list[Claim]:
    text = "\n".join(TEXTS)
    src = SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url="https://arxiv.org/abs/9",
        title="t",
        text=text,
        fetched_at=b.T0,
    )
    out: list[Claim] = []
    start = 0
    for t in TEXTS:
        unit = Unit.cut(src, start=start, end=start + len(t), granularity="sentence")
        out.append(Claim.from_unit(unit, line=b.LINE_IRI))
        start += len(t) + 1
    return out


def _store(tmp_path: Path) -> GraphStore:
    store = GraphStore(tmp_path / "store")
    store.line("akc").put(_claims())
    return store


# --- tokenization ----------------------------------------------------------------------


def test_japanese_runs_become_overlapping_bigrams_plus_last_char():
    # The trailing unigram lets a one-char query reach the last char of a run; every
    # other char is the first char of some bigram and is reached by prefix match.
    assert index_tokens("検索拡張") == ["検索", "索拡", "拡張", "張"]


def test_single_cjk_char_is_kept():
    assert index_tokens("本") == ["本"]


def test_latin_words_are_lowercased_whole_words():
    assert index_tokens("Retrieval-Augmented RAG") == ["retrieval", "augmented", "rag"]


def test_mixed_script_splits_at_script_boundary():
    assert index_tokens("LLMの検索") == ["llm", "の検", "検索", "索"]


def test_punctuation_is_dropped():
    assert index_tokens("。、「」!?") == []


# --- retrieval -------------------------------------------------------------------------


def test_two_char_japanese_query_hits(tmp_path: Path):
    # The trigram tokenizer misses this (measured 2026-09-22); bigrams must not.
    index = ClaimIndex.rebuild(tmp_path / "idx.sqlite", _store(tmp_path).line("akc"))
    hits = index.search("検索", limit=10)
    ids = {c.id for c in _claims()}
    assert set(hits) <= ids
    assert set(hits) == {_claims()[0].id, _claims()[2].id}


def test_english_query_hits(tmp_path: Path):
    index = ClaimIndex.rebuild(tmp_path / "idx.sqlite", _store(tmp_path).line("akc"))
    assert index.search("hallucination", limit=10) == [_claims()[1].id]


def test_multi_term_query_is_or_and_ranked(tmp_path: Path):
    # Candidate pre-pass: recall over precision (OR), best match first (bm25).
    index = ClaimIndex.rebuild(tmp_path / "idx.sqlite", _store(tmp_path).line("akc"))
    hits = index.search("言語モデルの検索", limit=10)
    assert hits[0] == _claims()[0].id
    assert _claims()[2].id in hits


def test_limit_is_respected(tmp_path: Path):
    index = ClaimIndex.rebuild(tmp_path / "idx.sqlite", _store(tmp_path).line("akc"))
    assert len(index.search("検索", limit=1)) == 1


def test_query_without_tokens_returns_nothing(tmp_path: Path):
    index = ClaimIndex.rebuild(tmp_path / "idx.sqlite", _store(tmp_path).line("akc"))
    assert index.search("。、", limit=10) == []


def test_query_syntax_is_treated_as_data(tmp_path: Path):
    # Claim/query text is untrusted: FTS5 operators must not parse as syntax.
    index = ClaimIndex.rebuild(tmp_path / "idx.sqlite", _store(tmp_path).line("akc"))
    assert index.search('NEAR( "x" OR * AND', limit=10) == []


# --- derived: the index is a pure function of the store --------------------------------


def test_index_holds_exactly_the_store_claims(tmp_path: Path):
    store = _store(tmp_path)
    store.line("akc").put([b.source(), b.unit()])  # non-claims are not indexed
    index = ClaimIndex.rebuild(tmp_path / "idx.sqlite", store.line("akc"))
    assert index.claim_ids() == {c.id for c in _claims()}


def test_rebuild_from_scratch_gives_identical_results(tmp_path: Path):
    store = _store(tmp_path)
    db = tmp_path / "idx.sqlite"
    first = ClaimIndex.rebuild(db, store.line("akc")).search("検索", limit=10)
    db.unlink()
    second = ClaimIndex.rebuild(db, GraphStore(tmp_path / "store").line("akc")).search(
        "検索", limit=10
    )
    assert first == second


def test_rebuild_is_idempotent(tmp_path: Path):
    store = _store(tmp_path)
    db = tmp_path / "idx.sqlite"
    ClaimIndex.rebuild(db, store.line("akc"))
    index = ClaimIndex.rebuild(db, store.line("akc"))
    with sqlite3.connect(db) as con:
        (count,) = con.execute("SELECT count(*) FROM claims").fetchone()
    assert count == len(_claims())
    assert index.claim_ids() == {c.id for c in _claims()}


def test_rebuild_tracks_store_changes(tmp_path: Path):
    store = _store(tmp_path)
    db = tmp_path / "idx.sqlite"
    ClaimIndex.rebuild(db, store.line("akc"))
    extra = Claim.from_unit(
        Unit.cut(b.source(), start=0, end=19, granularity="sentence"), line=b.LINE_IRI
    )
    store.line("akc").put([extra])
    index = ClaimIndex.rebuild(db, store.line("akc"))
    assert index.search("memory", limit=10) == [extra.id]


def test_open_missing_index_fails_loudly(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ClaimIndex.open(tmp_path / "missing.sqlite")


def test_open_existing_index(tmp_path: Path):
    db = tmp_path / "idx.sqlite"
    ClaimIndex.rebuild(db, _store(tmp_path).line("akc"))
    assert ClaimIndex.open(db).search("hallucination", limit=10) == [_claims()[1].id]


def test_fullwidth_and_halfwidth_forms_are_normalized():
    assert index_tokens("\uff2c\uff2c\uff2d") == ["llm"]  # full-width LLM
    assert index_tokens("ｶﾀｶﾅ") == index_tokens("カタカナ")


@pytest.mark.parametrize("query", ["社", "犬", "う"])
def test_single_cjk_char_query_hits_inside_a_run(tmp_path: Path, query: str):
    src = SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url="https://arxiv.org/abs/7",
        title="t",
        text="X社は犬を飼う",
        fetched_at=b.T0,
    )
    claim = Claim.from_unit(
        Unit.cut(src, start=0, end=len(src.text), granularity="sentence"), line=b.LINE_IRI
    )
    store = GraphStore(tmp_path / "store")
    store.line("akc").put([claim])
    index = ClaimIndex.rebuild(tmp_path / "idx.sqlite", store.line("akc"))
    assert index.search(query, limit=10) == [claim.id]


def test_search_after_index_deleted_fails_without_creating_a_file(tmp_path: Path):
    db = tmp_path / "idx.sqlite"
    index = ClaimIndex.rebuild(db, _store(tmp_path).line("akc"))
    db.unlink()
    with pytest.raises(sqlite3.OperationalError):
        index.search("検索", limit=10)
    with pytest.raises(sqlite3.OperationalError):
        index.claim_ids()
    assert not db.exists()
    with pytest.raises(FileNotFoundError):
        ClaimIndex.open(db)
