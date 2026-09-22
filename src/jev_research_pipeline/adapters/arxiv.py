"""arXiv API (export.arxiv.org/api/query, Atom XML, no auth). As-of 2026-09-22.

Rate limit (ToU): at most 1 request per 3 s. XML is parsed with defusedxml: the feed is
untrusted input, and entity expansion is refused rather than evaluated.
"""

from collections.abc import Mapping
from typing import Final

import httpx2
from defusedxml import ElementTree

from .base import Adapter, RawDraft, iso_date, one_line

ENDPOINT: Final = "https://export.arxiv.org/api/query"
MAX_RESULTS: Final = 20
_NS: Final = {"a": "http://www.w3.org/2005/Atom"}


def build_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    terms = " AND ".join(f"all:{word}" for word in query.split())
    params = {
        "search_query": terms,
        "start": "0",
        "max_results": str(MAX_RESULTS),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return httpx2.Request("GET", ENDPOINT, params=params)


def parse(body: str) -> list[RawDraft]:
    root = ElementTree.fromstring(body, forbid_dtd=True)
    drafts: list[RawDraft] = []
    for entry in root.findall("a:entry", _NS):
        link = next(
            (el.get("href") for el in entry.findall("a:link", _NS) if el.get("rel") == "alternate"),
            None,
        )
        title = entry.findtext("a:title", default="", namespaces=_NS)
        summary = entry.findtext("a:summary", default="", namespaces=_NS)
        drafts.append(
            RawDraft(
                url=link or "",  # no alternate link → fails URL validation → skipped
                title=one_line(title),
                text=one_line(summary),
                published_at=iso_date(entry.findtext("a:published", namespaces=_NS)),
            )
        )
    return drafts


def adapter() -> Adapter:
    return Adapter(kind="arxiv", build_request=build_request, parse=parse, min_interval_s=3.0)
