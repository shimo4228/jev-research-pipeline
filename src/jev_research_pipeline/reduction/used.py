"""Used rate: did a surfaced source show up in the author's own documents within 30 days?

A delayed, zero-effort label measured beside the author's ticks (plan used-rate-label,
decisions of 2026-10-19). It is a measurement only: nothing in fit, export-cases or the
Semantic Scholar nets reads a UsedMark.

- A source "appears" when one of its keys (arXiv id, DOI, GitHub owner/repo, normalized
  URL) is found in graph.jsonld, docs/adr/ of a track repo, or a vault note. Titles are not
  matched.
- graph.jsonld nodes carry no date and the vault has no history, so every scan records the
  keys it sees for the first time as Sightings (identity = key, first day wins), with the
  place: graph, adr, or `vault:<top folder>`.
- jrp's own notes, the author's own GitHub owner, and canary papers never count.
- A key already present when the first scan ran (baseline) predates every surfacing the
  scan could observe, so it is `unknown`, as is a key present before its source was
  surfaced. A source surfaced before the scan existed and not seen is `unknown` too: only
  part of its window was observed.
- A scan cannot read every file (iCloud placeholders, the time cap). The files it left are
  remembered as `unread:<path>` markers; a key that first turns up in a file the scan before
  could not read is `unsure`, and counts as `unknown`, never as used.
- A source not seen when its window closes is `unused`, recorded and nothing more: absence
  is not read as a negative.
"""

import json
import re
import stat
import time
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit

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
UNREAD_PREFIX: Final = "unread:"
"""Reserved Sighting key prefix: `unread:<path>` marks a file the last scan could not read."""
MAX_FILE_BYTES: Final = 5_000_000
SCAN_BUDGET_SECONDS: Final = 30.0
"""Wall-clock cap of one scan. An iCloud placeholder downloads on read (a cold vault took
300 s for 467 files), and the scan runs before the day's lines do."""
DATALESS: Final[int] = getattr(stat, "SF_DATALESS", 0x40000000)
"""macOS flag of a file whose data is only in iCloud: reading it blocks on a download.
Other systems never set it (`st_flags` is absent there)."""

_ARXIV: Final = re.compile(
    r"(?:arxiv(?:\.org)?[:/.\s]*(?:(?:abs|pdf)/)?|/(?:abs|pdf|papers)/)"
    r"(\d{2}(?:0[1-9]|1[0-2])\.\d{4,5})(?!\d)",
    re.IGNORECASE,
)
_DOI: Final = re.compile(r"\b10\.\d{4,9}/[^\s)\]>\"'<,;]+")
_GITHUB: Final = re.compile(r"github\.com/([\w.-]+/[\w.-]+)", re.IGNORECASE)
_URL: Final = re.compile(r"https?://[^\s<>\"'`)\]]+")
_TRAILING: Final = ".,;:!?"
_TRACKING: Final = re.compile(r"^(utm_.*|fbclid|gclid|mc_[a-z]+|ref|ref_src|igshid|_hsenc|_hsmi)$")


def normalize_url(raw: str) -> str | None:
    """host + path + query, lower case. Scheme, `www.`, fragment and a trailing slash are
    dropped; the query keeps its parameters sorted, minus tracking ones (`utm_*`, `fbclid`,
    ...), because `watch?v=a` and `watch?v=b` are two documents."""
    parts = urlsplit(raw.rstrip(_TRAILING))
    host = parts.netloc.lower().removeprefix("www.")
    if not host:
        return None
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING.match(k.lower())
    )
    tail = f"?{urlencode(query)}" if query else ""
    return f"{host}{parts.path.rstrip('/')}{tail}".lower()


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


def is_jrp_name(path: Path) -> bool:
    """A jrp note by its file name alone, decided before the file is opened."""
    return "_jrp_" in path.name


def is_jrp_output(path: Path, text: str) -> bool:
    """A jrp note: file name, frontmatter or a mark comment (vault.py `_MARK_LINE_RE`,
    markdown.py). Its sources are listed in its body, so counting it would make every source
    used on the day it was surfaced."""
    return is_jrp_name(path) or "\njrp_report:" in text[:2000] or "<!-- jrp:" in text


def _strings(node: JsonValue) -> Iterable[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, dict):
        for item in node.values():
            yield from _strings(item)


@dataclass
class Scan:
    """What one scan saw. `unread` are the files it could not read (dataless in iCloud, too
    big, an error, or left when the time cap hit), by path. `tainted` are the keys found in
    a file the scan before could not read: their first day cannot be trusted."""

    found: dict[str, SightingPlace] = field(default_factory=dict[str, SightingPlace])
    tainted: set[str] = field(default_factory=set[str])
    unread: set[str] = field(default_factory=set[str])
    capped: bool = False


class _Reader:
    def __init__(
        self, prior_unread: Collection[str], budget: float, clock: Callable[[], float]
    ) -> None:
        self.prior, self.clock = prior_unread, clock
        self.deadline = clock() + budget
        self.scan = Scan()

    def read(self, path: Path) -> str | None:
        """The text, or None with the file counted unread. A dataless file is skipped by
        its flag and never opened, so the scan does not wait on a download."""
        name = str(path)
        if self.clock() > self.deadline:
            self.scan.capped = True
            self.scan.unread.add(name)
            return None
        try:
            info = path.stat()
            if getattr(info, "st_flags", 0) & DATALESS or info.st_size > MAX_FILE_BYTES:
                self.scan.unread.add(name)
                return None
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self.scan.unread.add(name)
            return None

    def add(self, path: Path, keys: set[str], place: SightingPlace) -> None:
        for key in keys:
            self.scan.found.setdefault(key, place)
        if str(path) in self.prior:
            self.scan.tainted |= keys


def _graph_text(text: str) -> str:
    try:
        return "\n".join(_strings(json.loads(text)))
    except ValueError:
        return text


def _markdown(root: Path, *, skip_jrp: bool = False) -> Iterable[Path]:
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.md")):
        if any(p.startswith(".") for p in path.relative_to(root).parts):
            continue  # .obsidian, .trash, .git
        if skip_jrp and is_jrp_name(path):
            continue  # decided by name, before the file is opened
        yield path


def scan_documents(
    repos: Sequence[Path],
    vault: Path,
    *,
    owner: str | None = None,
    prior_unread: Collection[str] = (),
    budget: float = SCAN_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> Scan:
    """Every key in the author's documents, with the first place that holds it (graph, then
    adr, then vault as `vault:<top folder>`, plain `vault` for a note at the root). The
    author's own GitHub owner is dropped. `prior_unread` are the paths the scan before could
    not read; `budget` caps the whole scan in wall-clock seconds."""
    reader = _Reader(prior_unread, budget, clock)
    repo_list = list(dict.fromkeys(repos))
    for repo in repo_list:
        path = repo / "graph.jsonld"
        if path.is_file() and (text := reader.read(path)) is not None:
            reader.add(path, keys_of_text(_graph_text(text)), "graph")
    for repo in repo_list:
        for path in _markdown(repo / "docs" / "adr"):
            if (text := reader.read(path)) is not None:
                reader.add(path, keys_of_text(text), "adr")
    for path in _markdown(vault, skip_jrp=True):
        if (text := reader.read(path)) is None or is_jrp_output(path, text):
            continue
        parts = path.relative_to(vault).parts
        reader.add(path, keys_of_text(text), f"vault:{parts[0]}" if len(parts) > 1 else "vault")
    scan = reader.scan
    if owner:
        mine = (f"gh:{owner.lower()}/", f"url:github.com/{owner.lower()}/")
        scan.found = {k: p for k, p in scan.found.items() if not k.startswith(mine)}
    return scan


def unread_paths(pipeline: Partition) -> set[str]:
    """The files the last scan could not read."""
    return {
        n.key.removeprefix(UNREAD_PREFIX)
        for n in pipeline.load().values()
        if isinstance(n, Sighting) and n.key.startswith(UNREAD_PREFIX)
    }


def record_sightings(pipeline: Partition, scan: Scan, today: date) -> dict[str, Sighting]:
    """Add the keys seen for the first time (first day wins) and return every Sighting.
    The first scan of a store writes STARTED_KEY and marks its keys `baseline`; a key found
    in a file the scan before could not read is `unsure`. The `unread:` markers are brought
    in line with this scan's unread files."""
    stored = {n.key: n for n in pipeline.load().values() if isinstance(n, Sighting)}
    baseline = STARTED_KEY not in stored
    fresh = [
        Sighting.new(
            key=key, first_seen=today, place=place, baseline=baseline, unsure=key in scan.tainted
        )
        for key, place in scan.found.items()
        if key not in stored
    ]
    if baseline:
        fresh.append(Sighting.new(key=STARTED_KEY, first_seen=today, place="vault", baseline=True))
    marked = {k for k in stored if k.startswith(UNREAD_PREFIX)}
    wanted = {f"{UNREAD_PREFIX}{p}" for p in scan.unread}
    fresh += [
        Sighting.new(key=k, first_seen=today, place="vault", baseline=True) for k in wanted - marked
    ]
    pipeline.remove(Sighting.id_for(k) for k in marked - wanted)
    pipeline.put(fresh)
    return stored | {s.key: s for s in fresh}


def verdict_of(
    mark: UsedMark, matching: Sequence[Sighting], today: date, window: int = WINDOW_DAYS
) -> tuple[UsedVerdict, date | None]:
    """(verdict, seen_on) of one mark against the sightings of its source's keys."""
    if any(s.baseline or s.unsure or s.first_seen <= mark.surfaced_on for s in matching):
        # There before the source was surfaced, the same day, or first seen in a file the
        # scan before could not read.
        return "unknown", None
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
