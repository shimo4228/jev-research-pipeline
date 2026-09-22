"""Code cuts units: verbatim sentence spans of a source (judgment map, claim detection row).

Boundaries: [.!?] followed by whitespace, the full-width sentence enders (U+3002 U+FF01
U+FF1F), or a newline. Spans are trimmed of
surrounding whitespace (offsets adjusted, so Unit stays a verbatim slice); fragments
shorter than `min_chars` are dropped; a boundary-less run longer than `max_chars` is cut
at the last space before the cap so no unit floods the Jev state.
"""

import re
from typing import Final

from jev_research_pipeline.model import SourceItem, Unit

_BOUNDARY: Final = re.compile(r"(?<=[.!?])\s+|(?<=[\u3002\uff01\uff1f])|\n+")
MIN_CHARS: Final = 20
MAX_CHARS: Final = 600


def _spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _cap(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    while end - start > max_chars:
        cut = text.rfind(" ", start, start + max_chars)
        cut = cut if cut > start else start + max_chars
        out.append(_trim(text, start, cut))
        start = cut
    out.append(_trim(text, start, end))
    return out


def split_units(
    source: SourceItem, *, min_chars: int = MIN_CHARS, max_chars: int = MAX_CHARS
) -> list[Unit]:
    units: list[Unit] = []
    for raw_start, raw_end in _spans(source.text):
        start, end = _trim(source.text, raw_start, raw_end)
        for s, e in _cap(source.text, start, end, max_chars):
            if e - s >= min_chars:
                units.append(Unit.cut(source, start=s, end=e, granularity="sentence"))
    return units
