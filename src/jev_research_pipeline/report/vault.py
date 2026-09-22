"""Vault I/O: where report notes go, how they are written, and how ticks are harvested.

- The vault root comes only from env JRP_VAULT_DIR; unset or missing → VaultNotConfigured
  (nothing is written). Notes go to <vault>/daily-research/YYYY-MM-DD_jrp_<slug>.md —
  the path is built from the line slug (kebab-validated) and the date only, never from
  source- or model-derived text.
- A same-day re-run keeps the author's ticks: marks already in the note are carried
  over to the matching claim ids before the file is replaced (atomic write).
- Harvest (decision 5): only lines `- [x|-| ] … <!-- jrp:claim:<claim @id> -->` are read.
  [x] = correct, [-] = incorrect, [ ] = no gold: no Label, and an earlier Label for that
  claim is withdrawn (HarvestResult.cleared). Everything else in the note
  is the author's to edit. A missing or unreadable note is skipped with a reason.
"""

import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Final, Literal

from pydantic import AwareDatetime, ValidationError

from jev_research_pipeline.model import Label, kind_of
from jev_research_pipeline.model.jsonld import Value

from .markdown import CLAIM_MARK

VAULT_ENV: Final = "JRP_VAULT_DIR"
REPORT_DIR: Final = "daily-research"
_SLUG_RE: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_CLAIM_LINE_RE: Final = re.compile(
    rf"^(\s*- \[)([xX\- ])(\] .*<!-- {re.escape(CLAIM_MARK)}(\S+) -->)\s*$"
)
_REPORT_ID_RE: Final = re.compile(r"^jrp_report:\s*(.+?)\s*$", re.M)

type Verdict = Literal["correct", "incorrect"]
type SkipReason = Literal["missing", "unreadable", "no_report_id"]


class VaultNotConfigured(RuntimeError):
    pass


class HarvestResult(Value):
    labels: tuple[Label, ...]
    cleared: tuple[str, ...] = ()
    """Label @ids of claims shown as `[ ]`: the author withdrew (or never gave) a tick,
    so any earlier Label for that (claim, report) must be removed from the store."""
    skipped: SkipReason | None


def vault_dir(env: Mapping[str, str]) -> Path:
    raw = env.get(VAULT_ENV)
    if not raw:
        raise VaultNotConfigured(f"{VAULT_ENV} is not set; refusing to guess a vault")
    path = Path(raw)
    if not path.is_dir():
        raise VaultNotConfigured(f"{VAULT_ENV}={raw} is not a directory")
    return path


def note_path(vault: Path, slug: str, run_date: date) -> Path:
    if not _SLUG_RE.match(slug):
        raise ValueError(f"line slug must be kebab-case: {slug!r}")
    return vault / REPORT_DIR / f"{run_date.isoformat()}_jrp_{slug}.md"


def _marks(text: str) -> dict[str, str]:
    marks: dict[str, str] = {}
    for line in text.splitlines():
        m = _CLAIM_LINE_RE.match(line)
        if m:
            marks[m.group(4)] = m.group(2)
    return marks


def harvest_text(text: str) -> dict[str, Verdict]:
    out: dict[str, Verdict] = {}
    for claim_id, mark in _marks(text).items():
        if kind_of(claim_id) != "claim":
            continue
        if mark in "xX":
            out[claim_id] = "correct"
        elif mark == "-":
            out[claim_id] = "incorrect"
    return out


def unticked(text: str) -> list[str]:
    return [c for c, mark in _marks(text).items() if mark == " " and kind_of(c) == "claim"]


def _carry_over(new_text: str, old_marks: dict[str, str]) -> str:
    def replace(line: str) -> str:
        m = _CLAIM_LINE_RE.match(line)
        if m and m.group(4) in old_marks:
            return f"{m.group(1)}{old_marks[m.group(4)]}{m.group(3)}"
        return line

    return "\n".join(replace(line) for line in new_text.split("\n"))


def write_note(vault: Path, slug: str, run_date: date, text: str) -> Path:
    path = note_path(vault, slug, run_date)
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        try:
            old = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            old = ""  # unreadable old note: nothing to carry over
        text = _carry_over(text, _marks(old))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def _report_id(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    head = text[4:].split("\n---", 1)[0]
    m = _REPORT_ID_RE.search(head)
    if m is None:
        return None
    try:
        value = json.loads(m.group(1))
    except ValueError:
        return None
    return value if isinstance(value, str) and kind_of(value) == "report" else None


def note_report_id(path: Path) -> str | None:
    """The jrp_report @id in a note's frontmatter, or None (missing / unreadable / absent)."""
    try:
        return _report_id(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def harvest_note(
    path: Path, *, now: AwareDatetime, report_claims: frozenset[str] | None = None
) -> HarvestResult:
    """`report_claims` (the stored Report.claims) restricts harvesting to claims that were
    actually in this report — lines pasted from another note do not become Labels."""
    if not path.exists():
        return HarvestResult(labels=(), skipped="missing")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return HarvestResult(labels=(), skipped="unreadable")
    report_id = _report_id(text)
    if report_id is None:
        return HarvestResult(labels=(), skipped="no_report_id")
    labels: list[Label] = []
    for claim_id, verdict in harvest_text(text).items():
        if report_claims is not None and claim_id not in report_claims:
            continue
        try:
            labels.append(
                Label.new(
                    subject=claim_id,
                    report=report_id,
                    verdict=verdict,
                    provenance="claim",
                    harvested_at=now,
                )
            )
        except ValidationError:
            continue
    cleared = tuple(
        Label.id_for(claim_id, report_id)
        for claim_id in unticked(text)
        if report_claims is None or claim_id in report_claims
    )
    return HarvestResult(labels=tuple(labels), cleared=cleared, skipped=None)


def report_notes(vault: Path, slug: str) -> list[Path]:
    """Every jrp note of one line, oldest first (dates sort lexically)."""
    if not _SLUG_RE.match(slug):
        raise ValueError(f"line slug must be kebab-case: {slug!r}")
    return sorted((vault / REPORT_DIR).glob(f"*_jrp_{slug}.md"))
