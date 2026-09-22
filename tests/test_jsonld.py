"""JSON-LD scheme: @id recipe, @context coverage, graph document round-trip boundary."""

import json
import typing
from datetime import date, datetime

import pytest
from pydantic import BaseModel

from jev_research_pipeline.model import (
    CONTEXT,
    STORE_NS,
    GraphNode,
    Line,
    content_id,
    from_document,
    kind_of,
    to_document,
)
from jev_research_pipeline.model.jsonld import IRI_FIELDS, ORDERED_FIELDS

from .builders import every_node_kind


def test_content_id_is_deterministic_and_namespaced():
    a = content_id("claim", "x", "y")
    assert a == content_id("claim", "x", "y")
    assert a.startswith(f"{STORE_NS}claim/")
    assert kind_of(a) == "claim"


def test_content_id_separates_part_boundaries():
    # ("ab", "c") and ("a", "bc") must not collide — parts are joined with a separator
    # that cannot occur in IRIs or offsets.
    assert content_id("unit", "ab", "c") != content_id("unit", "a", "bc")


def test_kind_of_external_iri_is_none():
    assert kind_of("https://doi.org/10.5281/zenodo.1") is None


def _field_names(model: type[BaseModel]) -> set[str]:
    names: set[str] = set()
    for name, info in model.model_fields.items():
        names.add(name)
        for arg in _walk_types(info.annotation):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                names |= _field_names(arg)
    return names


def _walk_types(tp: object) -> list[object]:
    out = [tp]
    for arg in typing.get_args(tp):
        out.extend(_walk_types(arg))
    return out


def test_every_field_is_a_context_term():
    # Guards DROPPED-KEY: a field missing from @context would still survive via @vocab,
    # but its IRI coercion / @list container would silently be absent.
    terms = set(CONTEXT) - {"@vocab", "schema", "xsd"}
    for node in every_node_kind():
        missing = _field_names(type(node)) - {"id", "type"} - terms
        assert not missing, f"{type(node).__name__}: {missing}"


def test_iri_valued_fields_are_coerced_to_id():
    for name in IRI_FIELDS:
        entry = CONTEXT[name]
        assert isinstance(entry, dict) and entry.get("@type") == "@id", name


def test_ordered_fields_are_lists():
    # JSON-LD arrays are unordered sets unless @list — report order and pair order matter.
    for name in ORDERED_FIELDS:
        entry = CONTEXT[name]
        assert isinstance(entry, dict) and entry.get("@container") == "@list", name


def test_document_round_trips_every_node_kind():
    nodes = every_node_kind()
    doc = to_document(nodes)
    text = json.dumps(doc, ensure_ascii=False)
    back = from_document(json.loads(text))
    assert back == nodes


def test_document_uses_jsonld_keywords():
    doc = to_document(every_node_kind())
    assert doc["@context"] == CONTEXT
    for raw in doc["@graph"]:
        assert "@id" in raw and "@type" in raw
        assert "id" not in raw and "type" not in raw


def test_document_rejects_foreign_context():
    doc = to_document(every_node_kind())
    doc["@context"] = {"@vocab": "https://example.org/"}
    with pytest.raises(ValueError, match="@context"):
        from_document(doc)


def test_document_rejects_unknown_type():
    doc = to_document(every_node_kind())
    doc["@graph"][0]["@type"] = "Concept"
    with pytest.raises(ValueError):
        from_document(doc)


def test_line_keeps_external_graph_id_byte_identical():
    iri = "https://doi.org/10.5281/zenodo.19212119"
    line = Line(id=iri, slug="akc", name="AKC", adapters=("arxiv",))
    raw = to_document([line])["@graph"][0]
    assert raw["@id"] == iri


def test_graph_node_union_covers_all_kinds():
    kinds = {type(n) for n in every_node_kind()}
    assert kinds == set(typing.get_args(typing.get_args(GraphNode)[0]))


def test_dates_serialize_as_iso_strings():
    raw = to_document(every_node_kind())["@graph"]
    for node in raw:
        for value in node.values():
            assert not isinstance(value, datetime | date)


def test_document_rejects_duplicate_ids_both_ways():
    nodes = every_node_kind()
    with pytest.raises(ValueError, match="duplicate @id"):
        to_document([*nodes, nodes[2]])
    doc = to_document(nodes)
    doc["@graph"].append(doc["@graph"][2])
    with pytest.raises(ValueError, match="duplicate @id"):
        from_document(doc)
