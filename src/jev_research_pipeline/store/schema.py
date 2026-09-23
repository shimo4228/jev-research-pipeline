"""Is a store file written in today's schema? (judge, 2026-09-23: an old store stopped the
whole run with a bare "document @context differs" ValueError.)

A partition's @context is CONTEXT exactly (model.document). A file from an older build is
one of two kinds:
- additive: its @context is a strict subset of CONTEXT with every shared term unchanged,
  and every node validates under today's model — rewriting it with CONTEXT loses nothing;
- incompatible: a term was removed or re-mapped, or a node no longer validates (e.g. a
  Judgment whose subjects were (unit,) before claim_detection took (unit, question)). No
  context rewrite makes that data true under today's model; it is retired, not migrated.
"""

import json
from pathlib import Path
from typing import Any, Final, Literal, cast

from pydantic import TypeAdapter, ValidationError

from jev_research_pipeline.model import GraphNode, GraphNodeType
from jev_research_pipeline.model.jsonld import CONTEXT
from jev_research_pipeline.model.jsonld import Value as _Value

type Verdict = Literal["current", "additive", "incompatible"]

_NODE: Final[TypeAdapter[GraphNodeType]] = TypeAdapter(GraphNode)
_DETAIL_CHARS: Final = 160


class Inspection(_Value):
    verdict: Verdict
    detail: str
    """One line: what differs (empty when current)."""


def store_path(path: Path) -> str:
    """How a partition is named to the author: relative to the store root."""
    inside = f"lines/{path.name}" if path.parent.name == "lines" else path.name
    return f"store/{inside}"


class StoreSchemaError(ValueError):
    """A partition that today's model cannot read as it is. One line, saying what to do."""

    def __init__(self, path: Path, inspection: Inspection) -> None:
        self.path, self.inspection = path, inspection
        super().__init__(
            f"{store_path(path)} は旧 schema（{inspection.detail}）。`jrp migrate` か退避を"
        )


def _one_line(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _DETAIL_CHARS else flat[: _DETAIL_CHARS - 1] + "…"


def inspect_document(doc: dict[str, Any]) -> Inspection:
    context = doc.get("@context")
    if context == CONTEXT:
        return Inspection(verdict="current", detail="")
    if not isinstance(context, dict):
        return Inspection(verdict="incompatible", detail="@context がない")
    old = cast(dict[str, Any], context)
    removed = sorted(k for k in old if k not in CONTEXT)
    changed = sorted(k for k in old if k in CONTEXT and old[k] != CONTEXT[k])
    if removed or changed:
        what = [f"削除 {', '.join(removed)}" if removed else "", f"変更 {', '.join(changed)}" if changed else ""]
        return Inspection(
            verdict="incompatible",
            detail=_one_line(f"非互換: @context の項目 {' / '.join(w for w in what if w)}"),
        )
    failures: list[str] = []
    graph = cast(list[Any], doc.get("@graph") or [])
    for raw in graph:
        try:
            _NODE.validate_python(raw)
        except ValidationError as e:
            kind = str(cast(dict[str, Any], raw).get("@type", "?")) if isinstance(raw, dict) else "?"
            failures.append(f"{kind}: {e.errors()[0]['msg']}")
    if failures:
        return Inspection(
            verdict="incompatible",
            detail=_one_line(f"非互換: 現行 model で読めないノード {len(failures)} 件, 例 {failures[0]}"),
        )
    added = len(CONTEXT) - len(old)
    return Inspection(verdict="additive", detail=f"@context に {added} 項目を追加")


def inspect_partition(path: Path) -> Inspection:
    return inspect_document(json.loads(path.read_text(encoding="utf-8")))
