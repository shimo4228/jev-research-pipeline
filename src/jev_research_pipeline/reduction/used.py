"""Used rate: did a surfaced source show up in the author's own documents within 30 days?

A delayed, zero-effort label measured beside the author's ticks (plan used-rate-label,
decisions of 2026-10-19). It is a measurement only: nothing in fit, gold agreement, rule
candidates, Time-to-Discovery, export-cases or the Semantic Scholar nets reads a UsedMark.

- A source "appears" when one of its keys (arXiv id, DOI, GitHub owner/repo, normalized
  URL) is found in graph.jsonld, docs/adr/ of a track repo, or a vault note. Titles are not
  matched.
- graph.jsonld nodes carry no date and the vault is not under git, so every scan records the
  keys it sees for the first time as Sightings (identity = key, first day wins).
- jrp's own notes, the author's own GitHub owner, and canary papers never count.
- A key already present when the first scan ran (baseline) predates every surfacing the
  scan could observe, so it is `unknown`, as is a key present before its source was
  surfaced. A source surfaced before the scan existed and not seen is `unknown` too: only
  part of its window was observed.
- A source not seen when its window closes is `unused`, recorded and nothing more: absence
  is not read as a negative.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from jev_research_pipeline.model import (
    GraphNodeType,
    Question,
    QuestionLog,
    Sighting,
    SourceItem,
    UsedMark,
    UsedVerdict,
)
from jev_research_pipeline.model.nodes import SightingPlace
from jev_research_pipeline.store import Partition

WINDOW_DAYS: Final = 30
STARTED_KEY: Final = "used:started_on"
"""Reserved Sighting key: the day the first scan ran. No real key has this shape."""
MAX_FILE_BYTES: Final = 5_000_000

_ARXIV: Final = re.compile(
    r"(?:arxiv(?:\.org)?[:/.\s]*(?:(?:abs|pdf)/)?|/(?:abs|pdf|papers)/)"
    r"(\d{2}(?:0[1-9]|1[0-2])\.\d{4,5})(?!\d)",
    re.IGNORECASE,
)
_DOI: Final = re.compile(r"\b10\.\d{4,9}/[^\s)\]>\"'<,;]+")
_GITHUB: Final = re.compile(r"github\.com/([\w.-]+/[\w.-]+)", re.IGNORECASE)
_URL: Final = re.compile(r"https?://[^\s<>\"'`)\]]+")
_TRAILING: Final = ".,;:!?"


def normalize_url(raw: str) -> str | None:
    """host + path, lower case: scheme, `www.`, query, fragment and a trailing slash dropped."""
    parts = urlsplit(raw.rstrip(_TRAILING))
    host = parts.netloc.lower().removeprefix("www.")
    if not host:
        return None
    return f"{host}{parts.path.rstrip('/')}".lower()


def keys_of_text(text: str) -> set[str]:
    """`arxiv:<id>` / `doi:<lower>` / `gh:<owner/repo lower>` / `url:<normalized>`.

    The arXiv pattern needs its context (`arXiv:`, `/abs/`, `/pdf/`, `/papers/`), so a bare
    `2024.1234` in a number does not match. An old-style id (`hep-th/9901001`) is not
    matched."""
    keys = {f"arxiv:{m}" for m in _ARXIV.findall(text)}
    keys |= {f"doi:{d.lower().rstrip(_TRAILING)}" for d in _DOI.findall(text)}
    keys |= {f"gh:{r.lower().removesuffix('.git').rstrip('.')}" for r in _GITHUB.findall(text)}
    keys |= {f"url:{n}" for u in _URL.findall(text) if (n := normalize_url(u))}
    return keys


def is_jrp_output(path: Path, text: str) -> bool:
    """A jrp note: file name, frontmatter or a mark comment (vault.py `_MARK_LINE_RE`,
    markdown.py). Its sources are listed in its body, so counting it would make every source
    used on the day it was surfaced."""
    return "_jrp_" in path.name or "\njrp_report:" in text[:2000] or "<!-- jrp:" in text


def _strings(node: JsonValue) -> Iterable[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, dict):
        for item in node.values():
            yield from _strings(item)


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _graph_text(path: Path) -> str | None:
    text = _read(path)
    if text is None:
        return None
    try:
        return "\n".join(_strings(json.loads(text)))
    except ValueError:
        return text


def _markdown(root: Path) -> Iterable[tuple[Path, str]]:
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.md")):
        if any(p.startswith(".") for p in path.relative_to(root).parts):
            continue  # .obsidian, .trash, .git
        text = _read(path)
        if text is not None:
            yield path, text


def scan_documents(
    repos: Sequence[Path], vault: Path, *, owner: str | None = None
) -> dict[str, SightingPlace]:
    """Every key in the author's documents, with the first place that holds it (graph, then
    adr, then vault). The author's own GitHub owner is dropped."""
    found: dict[str, SightingPlace] = {}

    def add(keys: set[str], place: SightingPlace) -> None:
        for key in keys:
            found.setdefault(key, place)

    for repo in dict.fromkeys(repos):
        if (text := _graph_text(repo / "graph.jsonld")) is not None:
            add(keys_of_text(text), "graph")
    for repo in dict.fromkeys(repos):
        for _, text in _markdown(repo / "docs" / "adr"):
            add(keys_of_text(text), "adr")
    for path, text in _markdown(vault):
        if not is_jrp_output(path, text):
            add(keys_of_text(text), "vault")
    if owner:
        mine = (f"gh:{owner.lower()}/", f"url:github.com/{owner.lower()}/")
        found = {k: p for k, p in found.items() if not k.startswith(mine)}
    return found


def record_sightings(
    pipeline: Partition, found: Mapping[str, SightingPlace], today: date
) -> dict[str, Sighting]:
    """Add the keys seen for the first time (first day wins) and return every Sighting.
    The first scan of a store writes STARTED_KEY and marks its keys `baseline`."""
    stored = {n.key: n for n in pipeline.load().values() if isinstance(n, Sighting)}
    baseline = STARTED_KEY not in stored
    fresh = [
        Sighting.new(key=key, first_seen=today, place=place, baseline=baseline)
        for key, place in found.items()
        if key not in stored
    ]
    if baseline:
        fresh.append(Sighting.new(key=STARTED_KEY, first_seen=today, place="vault", baseline=True))
    pipeline.put(fresh)
    return stored | {s.key: s for s in fresh}


def verdict_of(
    mark: UsedMark, matching: Sequence[Sighting], today: date, window: int = WINDOW_DAYS
) -> tuple[UsedVerdict, date | None]:
    """(verdict, seen_on) of one mark against the sightings of its source's keys."""
    if any(s.baseline or s.first_seen <= mark.surfaced_on for s in matching):
        return "unknown", None  # there before the source was surfaced, or the same day
    closes = mark.surfaced_on + timedelta(days=window)
    seen = min((s.first_seen for s in matching), default=None)
    if seen is not None and seen <= closes:
        return "used", seen
    if today < closes:
        return "pending", None
    if mark.observed_from > mark.surfaced_on:
        return "unknown", None  # the scan began inside the window
    return "unused", None


def _canary_keys(nodes: Iterable[GraphNodeType]) -> set[str]:
    return {
        key
        for n in nodes
        if isinstance(n, Question)
        for u in n.canary_papers
        for key in keys_of_text(u)
    }


def mark_used(
    part: Partition,
    sightings: Mapping[str, Sighting],
    today: date,
    window: int = WINDOW_DAYS,
) -> int:
    """Create the UsedMark of every source a QuestionLog carried and settle the ones whose
    window has closed. Returns how many marks were written. One load, one write."""
    nodes = part.load()
    started = sightings.get(STARTED_KEY)
    began = started.first_seen if started else today
    sources = {n.id: n for n in nodes.values() if isinstance(n, SourceItem)}
    marks = {n.id: n for n in nodes.values() if isinstance(n, UsedMark)}
    canary = _canary_keys(nodes.values())
    out: list[UsedMark] = []
    for log in (n for n in nodes.values() if isinstance(n, QuestionLog)):
        for sid in log.sources:
            source = sources.get(sid)
            mark = marks.get(UsedMark.id_for(sid, log.report))
            if source is None or (mark is not None and mark.verdict != "pending"):
                continue
            keys = keys_of_text(source.url)
            if keys & canary:
                continue
            base = mark or UsedMark.new(
                source=sid,
                report=log.report,
                surfaced_on=log.run_date,
                observed_from=max(log.run_date, began),
                verdict="pending",
            )
            matching = [sightings[k] for k in keys if k in sightings]
            verdict, seen_on = verdict_of(base, matching, today, window)
            if mark is None or verdict != mark.verdict:
                out.append(
                    UsedMark.new(
                        source=sid,
                        report=log.report,
                        surfaced_on=base.surfaced_on,
                        observed_from=base.observed_from,
                        verdict=verdict,
                        seen_on=seen_on,
                    )
                )
    part.put(out)
    return len(out)


class UsedRate:
    """Counts of a line's marks. The rate's denominator is the sources whose window closed
    with a known answer (used + unused); `unknown` and `pending` are shown beside it."""

    def __init__(self, marks: Iterable[UsedMark]) -> None:
        counts: dict[str, int] = {"pending": 0, "used": 0, "unused": 0, "unknown": 0}
        for m in marks:
            counts[m.verdict] += 1
        self.pending, self.used = counts["pending"], counts["used"]
        self.unused, self.unknown = counts["unused"], counts["unknown"]

    @property
    def decided(self) -> int:
        return self.used + self.unused

    @property
    def rate(self) -> float | None:
        return self.used / self.decided if self.decided else None
