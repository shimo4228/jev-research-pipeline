"""`<JRP_STORE_DIR>/metrics/`: append-only JSON Lines files beside the partitions.

The weekly review appends one row a week to `weekly.jsonl` (pipeline.wbr) and one row per
call of its monitoring judge to `judge.jsonl` (pipeline.monitor); reduction.opened keeps
`opened.jsonl` its own way. None of them is a partition: store.migrate never reads or
rewrites `metrics/`, and no run reads these two files.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import JsonValue


def append_row(path: Path, row: Mapping[str, JsonValue]) -> None:
    """One JSON line at the end of `path` (created with its directory); a last line cut short
    is closed first, so it cannot swallow the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tail = path.read_bytes()[-1:] if path.is_file() else b""
    with path.open("a", encoding="utf-8") as out:
        if tail and tail != b"\n":
            out.write("\n")
        out.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def lines(path: Path) -> list[str]:
    """The file's lines, split at LF only: json.dumps(ensure_ascii=False) writes U+2028 and
    U+0085 raw, which str.splitlines would cut. [] when there is no file."""
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").split("\n") if line]
