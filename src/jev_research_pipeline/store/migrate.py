"""Bring a store written by an older build up to today's schema (store.schema decides).

prepare_store()  every jrp command, first: rewrites additive partitions with CONTEXT (a
                 one-line note each) and raises StoreSchemaError on the first incompatible
                 one — the run stops before it reads, writes or harvests anything.
migrate_store()  `jrp migrate [--dry-run]`: the same rewrite, and an incompatible partition
                 is moved (never deleted) to <store>/retired/<date>/, with its derived
                 index, so the next run starts that line on an empty partition. What it
                 would do is printed first; --dry-run prints and stops.
"""

import json
import shutil
from datetime import date
from pathlib import Path

from jev_research_pipeline.model import from_document
from jev_research_pipeline.model.jsonld import CONTEXT

from .graph import Partition
from .schema import Inspection, StoreSchemaError, inspect_partition

__all__ = ["StoreSchemaError", "inspect_partition", "migrate_store", "prepare_store"]


def partition_files(root: Path) -> list[Path]:
    """Every partition document of a store, lines first (sorted), then pipeline.jsonld."""
    files = sorted((root / "lines").glob("*.jsonld")) if (root / "lines").is_dir() else []
    pipeline = root / "pipeline.jsonld"
    return files + ([pipeline] if pipeline.exists() else [])


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _rewrite(path: Path) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    nodes = from_document({**doc, "@context": CONTEXT})
    Partition(path).write_all(nodes)


def prepare_store(root: Path) -> list[str]:
    notes: list[str] = []
    for path in partition_files(root):
        found = inspect_partition(path)
        if found.verdict == "incompatible":
            raise StoreSchemaError(path, found)
        if found.verdict == "additive":
            _rewrite(path)
            notes.append(f"store: {_relative(root, path)} を現行 schema に移行 ({found.detail})")
    return notes


def _retire(root: Path, path: Path, today: date) -> Path:
    target = root / "retired" / today.isoformat() / _relative(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(path, target)
    if path.parent.name == "lines":
        index = root / "index" / f"{path.stem}.sqlite"
        if index.exists():
            (target.parent.parent / "index").mkdir(parents=True, exist_ok=True)
            shutil.move(index, target.parent.parent / "index" / index.name)
    return target


def migrate_store(root: Path, *, dry_run: bool, today: date) -> list[str]:
    lines: list[str] = []
    plan: list[tuple[Path, Inspection]] = [
        (path, found)
        for path in partition_files(root)
        if (found := inspect_partition(path)).verdict != "current"
    ]
    for path, found in plan:
        name = _relative(root, path)
        if found.verdict == "additive":
            if not dry_run:
                _rewrite(path)
            lines.append(f"{name}: {'移行予定' if dry_run else '移行'} ({found.detail})")
        else:
            where = f"retired/{today.isoformat()}/{name}"
            if not dry_run:
                _retire(root, path, today)
            lines.append(f"{name}: 非互換 → {'退避予定' if dry_run else '退避'} {where} ({found.detail})")
    return lines
