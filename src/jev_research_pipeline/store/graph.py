"""On-disk JSON-LD store: one document per partition, upsert by @id (latest wins).

Layout under the store root:
    lines/<slug>.jsonld   research data of one line (+ its StageRecords)
    pipeline.jsonld       pipeline-wide state (RotationCursor)
Partition = one file per line (search-first 2026-09-22: named graphs in one file would
rewrite every line on any write; JSONL is not a JSON-LD document) — a line-run commits
with one atomic os.replace of its own file and gets its own git history.

Invariants:
- Every partition file is exactly to_document(nodes): the fixed CONTEXT, unique @ids.
- Nodes are written sorted by @id, one compact node per text line, so the file bytes
  depend only on the node set (not on put order) and a changed node is a one-line diff.
- A write goes to a temp file in the same directory, fsync, then os.replace: a crash
  leaves the previous version intact, never a half-written document.
- put() rewrites the whole file: batch nodes per stage, not per node. Re-evaluate the
  layout past ~10^5 nodes / 50 MB per line (measured: 100k nodes = 39 MB, 0.4 s write).
"""

import json
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

from jev_research_pipeline.model import GraphNodeType, from_document, to_document
from jev_research_pipeline.model.jsonld import CONTEXT

from .schema import StoreSchemaError, inspect_document

_SLUG_RE: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class Partition:
    """One JSON-LD document file. Reads parse and validate the whole file every call."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, GraphNodeType]:
        if not self.path.exists():
            return {}
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        if doc.get("@context") != CONTEXT:
            # Named, with what to do, instead of from_document's bare ValueError. The
            # commands migrate additive files before they get here (store.migrate).
            raise StoreSchemaError(self.path, inspect_document(doc))
        return {node.id: node for node in from_document(doc)}

    def get(self, iri: str) -> GraphNodeType | None:
        return self.load().get(iri)

    def put(self, nodes: Iterable[GraphNodeType]) -> None:
        """Upsert: a node replaces any stored node with the same @id; later wins within `nodes`."""
        incoming = {node.id: node for node in nodes}
        if not incoming:
            return
        merged = self.load() | incoming
        self._write([merged[iri] for iri in sorted(merged)])

    def remove(self, iris: Iterable[str]) -> None:
        """Drop nodes by @id (absent ids are ignored). Used to withdraw Labels."""
        drop = set(iris)
        current = self.load()
        if not drop & set(current):
            return
        self._write([current[i] for i in sorted(current) if i not in drop])

    def write_all(self, nodes: list[GraphNodeType]) -> None:
        """Replace the whole file with `nodes` (a migration's rewrite). Sorted by @id, like
        every write, so the bytes depend only on the node set."""
        self._write(sorted(nodes, key=lambda n: n.id))

    def _write(self, nodes: list[GraphNodeType]) -> None:
        doc = to_document(nodes)
        graph: list[dict[str, Any]] = doc["@graph"]
        context = json.dumps(doc["@context"], ensure_ascii=False, sort_keys=True)
        body = ",\n".join(json.dumps(n, ensure_ascii=False, separators=(",", ":")) for n in graph)
        text = f'{{"@context": {context},\n"@graph": [\n{body}\n]}}\n'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


class GraphStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def line(self, slug: str) -> Partition:
        # The slug becomes a file name: kebab-only keeps it inside lines/.
        if not _SLUG_RE.match(slug):
            raise ValueError(f"line slug must be kebab-case: {slug!r}")
        return Partition(self.root / "lines" / f"{slug}.jsonld")

    def pipeline(self) -> Partition:
        return Partition(self.root / "pipeline.jsonld")
