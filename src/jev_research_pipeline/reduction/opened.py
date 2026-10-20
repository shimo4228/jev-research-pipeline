"""Opened: which jrp notes the author opened in Obsidian, by the day jrp first saw them.

A signal beside the ticks (plan quality-metrics, author decision 2026-10-20). It feeds the
weekly review's author signal and the "a line whose notes carry O1 yet stay unopened"
exception, and is never a primary metric.

- Obsidian keeps a short list of recently opened files (`lastOpenFiles`) in
  `.obsidian/workspace.json` (desktop) and `.obsidian/workspace-mobile.json` (mobile).
  Under launchd the wrapper (scripts/launchd-jrp.sh) copies exactly those two files into
  the stage every morning, because python never opens the iCloud vault; run directly, the
  vault's own two files are read. No other file of `.obsidian` is read. A list iCloud has
  not downloaded to this Mac (dataless) is not copied that morning, so it is not read.
- Only names of jrp notes (`daily-research/*_jrp_*.md`) are kept. Every other entry of
  the list is dropped as it is read and never stored. The wrapper's copies, which hold
  every entry, are in the stage only while `jrp run` runs: the wrapper removes them when
  the run returns (and when it is stopped by a signal), and removes any a killed wrapper
  left before it stages the next ones.
- A name seen for the first time is appended to `<store>/metrics/opened.jsonl` as
  `{"note": "<file name>", "first_seen": "<YYYY-MM-DD>"}`; a name already there is never
  written again. A line of that file that cannot be read does not count as recorded, so
  its name may be appended again later: a reader takes the earliest `first_seen` of a
  name.
- The list is short and recent: a note opened and pushed out between two runs is never
  seen, and the copy is taken at the run's start, so `first_seen` is at best the morning
  after the note was opened.
- Obsidian's file format is not a public spec. A file that is not JSON (nested deeper
  than json.loads can recurse into included), or has no list of names, yields no name
  rather than an error. A file that cannot be opened (OSError) is an error: the caller
  turns it into one line of the note.
- opened.jsonl is split into rows at LF (U+000A) only. A note name may hold U+2028, U+2029 or
  U+0085, which json.dumps(ensure_ascii=False) writes raw and str.splitlines() would cut
  a row at.
- `metrics/` is not a partition: store.migrate (`partition_files`) never reads or rewrites
  it.
"""

import json
from collections.abc import Iterable
from datetime import date
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Final

from pydantic import JsonValue

from jev_research_pipeline.report.vault import REPORT_DIR

WORKSPACE_FILES: Final = ("workspace.json", "workspace-mobile.json")
"""The two lists the wrapper stages (scripts/launchd-jrp.sh WORKSPACES); nothing else."""
OPENED_FILE: Final = Path("metrics", "opened.jsonl")
"""Under the store root."""
_NOTE_GLOB: Final = "*_jrp_*.md"


def jrp_notes(entries: Iterable[JsonValue]) -> set[str]:
    """The file names of the entries that are vault paths of jrp notes, directly in
    daily-research/. Anything else (another folder, another file, a non-string) is dropped."""
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str):
            continue
        path = PurePosixPath(entry)
        if path.parent == PurePosixPath(REPORT_DIR) and fnmatchcase(path.name, _NOTE_GLOB):
            names.add(path.name)
    return names


def _listed(raw: bytes) -> set[str]:
    try:
        doc: JsonValue = json.loads(raw)
    except (ValueError, RecursionError):  # not JSON, not UTF-8, or nested past the stack
        return set()
    if not isinstance(doc, dict):
        return set()
    files = doc.get("lastOpenFiles")
    return jrp_notes(files) if isinstance(files, list) else set()


def opened_notes(vault: Path) -> set[str]:
    """The jrp notes on either of Obsidian's lists; empty when the vault has neither file."""
    names: set[str] = set()
    for name in WORKSPACE_FILES:
        path = vault / ".obsidian" / name
        if path.is_file():
            names |= _listed(path.read_bytes())
    return names


def recorded(text: str) -> set[str]:
    """The names opened.jsonl already holds; a line that cannot be read holds none. Rows
    are split at LF only (record_opened writes them so), never at the other line breaks
    str.splitlines() knows."""
    names: set[str] = set()
    for line in text.split("\n"):
        try:
            row: JsonValue = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(row, dict) and isinstance(note := row.get("note"), str):
            names.add(note)
    return names


def record_opened(vault: Path, store_root: Path, today: date) -> int:
    """Append the jrp notes on Obsidian's lists that opened.jsonl does not hold yet, in name
    order, each with `today` as its first_seen. Returns how many were appended. Nothing is
    created when there is nothing to append."""
    seen = opened_notes(vault)
    if not seen:
        return 0
    path = store_root / OPENED_FILE
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    new = sorted(seen - recorded(text))
    if not new:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        json.dumps({"note": note, "first_seen": today.isoformat()}, ensure_ascii=False) + "\n"
        for note in new
    ]
    with path.open("a", encoding="utf-8") as out:
        if text and not text.endswith("\n"):
            out.write("\n")  # a last line cut short must not swallow the first new one
        out.writelines(rows)
    return len(new)
