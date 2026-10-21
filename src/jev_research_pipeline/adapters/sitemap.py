"""The pages under a URL prefix that a site's sitemap.xml says changed: a question's
`- sitemap: <https URL prefix>` line.

For a site with no feed whose sitemap dates its pages — anthropic.com, measured 2026-10-20:
no RSS (/rss.xml and /news/rss.xml answer 404), and https://www.anthropic.com/sitemap.xml
carries a lastmod on 536 of its 566 URLs. The query `https://www.anthropic.com/news/`
asks for `https://www.anthropic.com/sitemap.xml` and keeps the URLs below that prefix (the
prefix's own listing page is not one of them) whose lastmod falls in the window; each page
is then fetched (base.Follow), since a sitemap entry has no text. A lastmod is the page's
last edit, so an edited post comes back too: its new sentences are new claims, the ones
already reported are not reported again.

A sitemap with no lastmod (claude.com's, 3,794 URLs) cannot be windowed and yields nothing;
a sitemap index (`<sitemapindex>`) is not followed. Either shows as 0 results for the query.
Parsed with defusedxml (no DTD), the same guard as the arXiv listing (adapters.firehose).
"""

import functools
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Final
from urllib.parse import urlsplit

import httpx2
from defusedxml import ElementTree

from .base import USER_AGENT, Adapter, Follow, RawDraft, iso_date
from .feed import FOLLOW_LIMIT, WINDOW_DAYS
from .page import article_parse

_NS: Final = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
MIN_INTERVAL_S: Final = 1.0


def sitemap_url(prefix: str) -> str:
    """`<scheme>://<host>/sitemap.xml` of the prefix's site."""
    parts = urlsplit(prefix)
    return f"{parts.scheme}://{parts.netloc}/sitemap.xml"


def build_request(query: str, _env: Mapping[str, str]) -> httpx2.Request:
    return httpx2.Request("GET", sitemap_url(query), headers={"User-Agent": USER_AGENT})


def _below(url: str, prefix: str) -> bool:
    """`url` is a page under `prefix`, not the prefix's own page. The query's trailing
    slash may be gone (run.authored_candidates strips edge punctuation)."""
    root = prefix.rstrip("/") + "/"
    return url.startswith(root) and url.rstrip("/") != root.rstrip("/")


def parse(body: str, *, prefix: str, today: date) -> list[RawDraft]:
    """The pages under `prefix` changed in the window, newest first: Follow's limit takes
    them in this order, and a sitemap lists its pages in its own (anthropic.com by name,
    support.claude.com by article id), which spent the limit on old pages and cut the new
    ones (2026-10-22: 25 cut, among them new Claude Code help articles). Ties keep the
    sitemap's order; the raw lastmod string orders pages of one day by time."""
    root = ElementTree.fromstring(body, forbid_dtd=True)
    since = today - timedelta(days=WINDOW_DAYS)
    found: list[tuple[date, str, str]] = []
    for entry in root.iter(f"{_NS}url"):
        loc = (entry.findtext(f"{_NS}loc") or "").strip()
        stamp = (entry.findtext(f"{_NS}lastmod") or "").strip()
        changed = iso_date(stamp)
        if not _below(loc, prefix) or changed is None or changed < since:
            continue
        found.append((changed, stamp, loc))
    found.sort(key=lambda f: (f[0], f[1]), reverse=True)
    return [RawDraft(url=loc, title=loc, text="", published_at=d) for d, _, loc in found]


def adapter(today: date, prefix: str) -> Adapter:
    """The pages under `prefix` changed in the window before `today` (the run's date)."""
    return Adapter(
        kind="sitemap",
        build_request=build_request,
        parse=functools.partial(parse, prefix=prefix, today=today),
        min_interval_s=MIN_INTERVAL_S,
        query_kind="token",
        follow=Follow(parse=article_parse, limit=FOLLOW_LIMIT),
    )
