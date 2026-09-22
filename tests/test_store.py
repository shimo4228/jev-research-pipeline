"""On-disk JSON-LD store: per-line partitions, upsert by @id, deterministic atomic writes."""

import json
from pathlib import Path

import pytest

from jev_research_pipeline.model import CONTEXT, SourceItem
from jev_research_pipeline.store import GraphStore

from . import builders as b


def _source(text: str) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url="https://arxiv.org/abs/2609.00001",
        title="t",
        text=text,
        fetched_at=b.T0,
    )


def test_put_then_load_round_trips(tmp_path: Path):
    nodes = b.every_node_kind()
    part = GraphStore(tmp_path).line("akc")
    part.put(nodes)
    loaded = GraphStore(tmp_path).line("akc").load()
    assert sorted(loaded) == sorted(n.id for n in nodes)
    assert all(loaded[n.id] == n for n in nodes)


def test_partition_file_is_a_jsonld_document(tmp_path: Path):
    GraphStore(tmp_path).line("akc").put([b.claim()])
    doc = json.loads((tmp_path / "lines" / "akc.jsonld").read_text(encoding="utf-8"))
    assert doc["@context"] == CONTEXT
    assert [n["@id"] for n in doc["@graph"]] == [b.claim().id]


def test_upsert_latest_wins_across_puts(tmp_path: Path):
    part = GraphStore(tmp_path).line("akc")
    part.put([_source("v1")])
    part.put([_source("v2")])
    loaded = part.load()
    assert len(loaded) == 1
    node = loaded[_source("v2").id]
    assert isinstance(node, SourceItem)
    assert node.text == "v2"


def test_upsert_latest_wins_within_one_put(tmp_path: Path):
    part = GraphStore(tmp_path).line("akc")
    part.put([_source("v1"), _source("v2")])
    node = part.get(_source("v1").id)
    assert isinstance(node, SourceItem)
    assert node.text == "v2"


def test_put_keeps_untouched_nodes(tmp_path: Path):
    part = GraphStore(tmp_path).line("akc")
    part.put([b.claim()])
    part.put([b.unit()])
    assert set(part.load()) == {b.claim().id, b.unit().id}


def test_partitions_are_isolated(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.line("akc").put([b.claim()])
    assert store.line("other").load() == {}
    assert store.pipeline().load() == {}


def test_pipeline_partition_has_its_own_file(tmp_path: Path):
    GraphStore(tmp_path).pipeline().put([b.cursor()])
    assert (tmp_path / "pipeline.jsonld").exists()
    assert GraphStore(tmp_path).pipeline().get(b.cursor().id) == b.cursor()


def test_missing_node_is_none(tmp_path: Path):
    assert GraphStore(tmp_path).line("akc").get(b.claim().id) is None


def test_file_bytes_do_not_depend_on_put_order(tmp_path: Path):
    nodes = b.every_node_kind()
    a, c = tmp_path / "a", tmp_path / "c"
    GraphStore(a).line("akc").put(nodes)
    GraphStore(c).line("akc").put(list(reversed(nodes)))
    assert (a / "lines" / "akc.jsonld").read_bytes() == (c / "lines" / "akc.jsonld").read_bytes()


def test_write_leaves_no_temp_files(tmp_path: Path):
    GraphStore(tmp_path).line("akc").put([b.claim()])
    GraphStore(tmp_path).line("akc").put([b.unit()])
    assert sorted(p.name for p in (tmp_path / "lines").iterdir()) == ["akc.jsonld"]


def test_japanese_text_is_stored_verbatim(tmp_path: Path):
    GraphStore(tmp_path).line("akc").put([_source("言語モデルの検索")])
    raw = (tmp_path / "lines" / "akc.jsonld").read_text(encoding="utf-8")
    assert "言語モデルの検索" in raw


def test_foreign_document_is_rejected(tmp_path: Path):
    (tmp_path / "lines").mkdir()
    (tmp_path / "lines" / "akc.jsonld").write_text(
        json.dumps({"@context": {"@vocab": "https://example.org/"}, "@graph": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="@context"):
        GraphStore(tmp_path).line("akc").load()


def test_line_slug_must_be_kebab(tmp_path: Path):
    with pytest.raises(ValueError):
        GraphStore(tmp_path).line("../escape")


def test_empty_put_creates_nothing(tmp_path: Path):
    GraphStore(tmp_path).line("akc").put([])
    assert not (tmp_path / "lines" / "akc.jsonld").exists()


def test_one_node_per_text_line(tmp_path: Path):
    # A changed node shows up as a one-line git diff.
    nodes = b.every_node_kind()
    GraphStore(tmp_path).line("akc").put(nodes)
    lines = (tmp_path / "lines" / "akc.jsonld").read_text(encoding="utf-8").splitlines()
    node_lines = [ln for ln in lines if ln.startswith('{"@id"')]
    assert len(node_lines) == len(nodes)
