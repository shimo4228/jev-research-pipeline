"""Graph document boundary: nodes ⇄ {"@context": CONTEXT, "@graph": [...]}.

This is the only place JSON-LD documents are built or parsed. Loading rejects any
@context other than CONTEXT (a context change is a store format change) and dispatches
each node on "@type" through the closed GraphNode union — an unknown type is an error,
never a silently skipped node. Each @id appears at most once per document: two nodes
with one @id would be merged by a JSON-LD processor into a node with doubled values
(e.g. two text / content_sha256 pairs), silently breaking the per-node invariants.
"""

from typing import Any

from pydantic import TypeAdapter

from .jsonld import CONTEXT
from .nodes import GraphNode, GraphNodeType

_NODES: TypeAdapter[list[GraphNodeType]] = TypeAdapter(list[GraphNode])


def _require_unique_ids(nodes: list[GraphNodeType]) -> None:
    seen: set[str] = set()
    for node in nodes:
        if node.id in seen:
            raise ValueError(f"duplicate @id in document: {node.id}")
        seen.add(node.id)


def to_document(nodes: list[GraphNodeType]) -> dict[str, Any]:
    _require_unique_ids(nodes)
    return {"@context": CONTEXT, "@graph": _NODES.dump_python(nodes, mode="json", by_alias=True)}


def from_document(doc: dict[str, Any]) -> list[GraphNodeType]:
    if doc.get("@context") != CONTEXT:
        raise ValueError("document @context differs from the pipeline CONTEXT")
    nodes = _NODES.validate_python(doc.get("@graph"))
    _require_unique_ids(nodes)
    return nodes
