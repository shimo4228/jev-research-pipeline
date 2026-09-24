"""arXiv API (export.arxiv.org/api/query, Atom XML, no auth). As-of 2026-09-22.

Rate limit (ToU): at most 1 request per 3 s, one connection at a time. XML is parsed with defusedxml: the feed is
untrusted input, and entity expansion is refused rather than evaluated.
"""

from collections.abc import Mapping
from typing import Final

import httpx2
from defusedxml import ElementTree

from .base import USER_AGENT, Adapter, RawDraft, iso_date, one_line

ENDPOINT: Final = "https://export.arxiv.org/api/query"
MAX_RESULTS: Final = 20
_NS: Final = {"a": "http://www.w3.org/2005/Atom"}
# The edge in front of export.arxiv.org answers 406 to default library headers
# (measured 2026-09-22; explicit atom Accept + descriptive UA → 200 on 2026-09-23).
HEADERS: Final = {"Accept": "application/atom+xml", "User-Agent": USER_AGENT}

ARXIV_RETRY: Final = frozenset({406})
"""export.arxiv.org's edge answers 406 in bursts to a client it has scored (measured
2026-09-23: the same request 406 from httpx2 and 200 from curl in the same minute, and
200 from httpx2 again minutes later; not header order, query encoding, HTTP version or
the query text). Undocumented, so it is waited out rather than worked around. A 406 that
outlasts the resends stops keyword search for the day (nets._record_failure)."""
ARXIV_RETRY_WAITS: Final = (10.0, 20.0)


def build_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    terms = " AND ".join(f"all:{word}" for word in query.split())
    params = {
        "search_query": terms,
        "start": "0",
        "max_results": str(MAX_RESULTS),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return httpx2.Request("GET", ENDPOINT, params=params, headers=HEADERS)


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
    return Adapter(
        kind="arxiv",
        build_request=build_request,
        parse=parse,
        min_interval_s=3.0,
        retry_status=ARXIV_RETRY,
        retry_waits=ARXIV_RETRY_WAITS,
        one_connection=True,
    )
