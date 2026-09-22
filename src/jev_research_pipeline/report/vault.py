"""Vault I/O: where report notes go, how they are written, and how ticks are harvested.

- The vault root comes only from env JRP_VAULT_DIR; unset or missing → VaultNotConfigured
  (nothing is written). Notes go to <vault>/daily-research/YYYY-MM-DD_jrp_<slug>.md —
  the path is built from the line slug (kebab-validated) and the date only, never from
  source- or model-derived text.
- A same-day re-run keeps the author's ticks: marks already in the note are carried
  over to the matching claim ids before the file is replaced (atomic write).
- Harvest: only lines `- [x|-| ] … <!-- jrp:<kind>:<payload> -->` are read, for the four
  kinds the note writes: `qday` (a question-day — the primary unit), `source`, `claim`
  and `question` (a proposal the author adopts). [x] = correct, [-] = incorrect,
  [ ] = no gold: no Label, and an earlier Label for that subject is withdrawn
  (HarvestResult.cleared). A question-day tick propagates to the claims and sources its
  QuestionLog cites, so the fit layer gets claim-level gold from one checkbox. A ticked
  proposal is returned as `adopted` for the runner to append to questions/<slug>.md —
  this module never writes there itself. Everything else in the note is the author's to
  edit. A missing or unreadable note is skipped with a reason.
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

from jev_research_pipeline.model import Label, LabelProvenance, QuestionLog, kind_of
from jev_research_pipeline.model.jsonld import Value

VAULT_ENV: Final = "JRP_VAULT_DIR"
REPORT_DIR: Final = "daily-research"
_SLUG_RE: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MARK_LINE_RE: Final = re.compile(r"^(\s*>?\s*- \[)([xX\- ])(\] .*<!-- jrp:([a-z]+):(\S+) -->)\s*$")
_REPORT_ID_RE: Final = re.compile(r"^jrp_report:\s*(.+?)\s*$", re.M)

type Verdict = Literal["correct", "incorrect"]
type SkipReason = Literal["missing", "unreadable", "no_report_id"]


class VaultNotConfigured(RuntimeError):
    pass


class HarvestResult(Value):
    labels: tuple[Label, ...]
    cleared: tuple[str, ...] = ()
    """Label @ids of subjects shown as `[ ]`: the author withdrew (or never gave) a tick,
    so any earlier Label for that (subject, report) must be removed from the store."""
    adopted: tuple[str, ...] = ()
    """Slugs of question proposals the author ticked; the runner appends them to the
    question file (this module never writes there)."""
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


def _marks(text: str) -> dict[tuple[str, str], str]:
    """(kind, payload) → the character inside the box, for every machine-read line."""
    marks: dict[tuple[str, str], str] = {}
    for line in text.splitlines():
        m = _MARK_LINE_RE.match(line)
        if m:
            marks[(m.group(4), m.group(5))] = m.group(2)
    return marks


def _verdict(mark: str) -> Verdict | None:
    if mark in "xX":
        return "correct"
    return "incorrect" if mark == "-" else None


def ticks(text: str, kind: str) -> dict[str, Verdict]:
    """Payload → verdict for one mark kind; unticked payloads are left out."""
    return {
        payload: verdict
        for (k, payload), mark in _marks(text).items()
        if k == kind and (verdict := _verdict(mark)) is not None
    }


def harvest_text(text: str) -> dict[str, Verdict]:
    """Claim ticks, the shape the reduction layer has always read."""
    return {i: v for i, v in ticks(text, "claim").items() if kind_of(i) == "claim"}


def unticked(text: str, kind: str = "claim") -> list[str]:
    return [p for (k, p), mark in _marks(text).items() if k == kind and mark == " "]


def _carry_over(new_text: str, old_marks: dict[tuple[str, str], str]) -> str:
    def replace(line: str) -> str:
        m = _MARK_LINE_RE.match(line)
        key = (m.group(4), m.group(5)) if m else None
        if m and key in old_marks:
            return f"{m.group(1)}{old_marks[key]}{m.group(3)}"
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


def _labels(
    text: str,
    *,
    report_id: str,
    now: AwareDatetime,
    logs: Mapping[str, QuestionLog],
    report_claims: frozenset[str] | None,
) -> dict[str, Label]:
    """One Label per ticked subject. A question-day tick propagates to what that day
    cited; a claim's own tick wins over a propagated one, because the author said
    something specific about it."""
    labels: dict[str, Label] = {}

    def label(subject: str, verdict: Verdict, provenance: LabelProvenance) -> None:
        try:
            made = Label.new(
                subject=subject,
                report=report_id,
                verdict=verdict,
                provenance=provenance,
                harvested_at=now,
            )
        except ValidationError:
            return
        if made.id not in labels or provenance != "question_day":
            labels[made.id] = made

    for mark, verdict in ticks(text, "qday").items():
        log = logs.get(mark)
        if log is not None:
            for subject in (log.id, *log.claims, *log.sources):
                label(subject, verdict, "question_day")
    for source_id, verdict in ticks(text, "source").items():
        label(source_id, verdict, "source")
    for claim_id, verdict in harvest_text(text).items():
        if report_claims is None or claim_id in report_claims:
            label(claim_id, verdict, "claim")
    return labels


def _cleared(
    text: str,
    *,
    report_id: str,
    logs: Mapping[str, QuestionLog],
    report_claims: frozenset[str] | None,
) -> list[str]:
    """Label @ids to withdraw: every subject the author left, or made, blank."""
    subjects: list[str] = []
    for mark in unticked(text, "qday"):
        log = logs.get(mark)
        if log is not None:
            subjects += [log.id, *log.claims, *log.sources]
    subjects += unticked(text, "source")
    subjects += [
        claim_id
        for claim_id in unticked(text, "claim")
        if report_claims is None or claim_id in report_claims
    ]
    return [Label.id_for(i, report_id) for i in subjects]


def harvest_note(
    path: Path,
    *,
    now: AwareDatetime,
    report_claims: frozenset[str] | None = None,
    logs: Mapping[str, QuestionLog] | None = None,
) -> HarvestResult:
    """`report_claims` (the stored Report.claims) restricts claim harvesting to claims
    that were actually in this report — lines pasted from another note do not become
    Labels. `logs` maps a question-day mark (`<question @id>:<date>`) to its QuestionLog,
    so one tick propagates to the claims and sources that day cited."""
    if not path.exists():
        return HarvestResult(labels=(), skipped="missing")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return HarvestResult(labels=(), skipped="unreadable")
    report_id = _report_id(text)
    if report_id is None:
        return HarvestResult(labels=(), skipped="no_report_id")
    by_mark = logs or {}
    labels = _labels(text, report_id=report_id, now=now, logs=by_mark, report_claims=report_claims)
    cleared = _cleared(text, report_id=report_id, logs=by_mark, report_claims=report_claims)
    return HarvestResult(
        labels=tuple(labels.values()),
        cleared=tuple(i for i in dict.fromkeys(cleared) if i not in labels),
        adopted=tuple(ticks(text, "question")),
        skipped=None,
    )


def report_notes(vault: Path, slug: str) -> list[Path]:
    """Every jrp note of one line, oldest first (dates sort lexically)."""
    if not _SLUG_RE.match(slug):
        raise ValueError(f"line slug must be kebab-case: {slug!r}")
    return sorted((vault / REPORT_DIR).glob(f"*_jrp_{slug}.md"))
