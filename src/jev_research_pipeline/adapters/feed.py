"""An RSS 2.0 or Atom feed by its URL: a question's `- feed: <https URL>` line.

For sources that publish a feed and no search — the claude-code line's official sources,
measured 2026-10-20: Claude Code's release notes (code.claude.com/docs/en/changelog/rss.xml,
each version's notes in full), the Claude Code team's blog (claude.dev/rss.xml, summaries
only) and claude.com's articles, which have no feed of their own (a community scrape,
github.com/Olshansk/rss-feeds feeds/feed_claude.xml, summaries only).

- Window: the items published from WINDOW_DAYS before the run's date on. An item with no
  date is left out: the window cannot place it, and every feed above dates its items.
- Text: the item's full content (RSS content:encoded, Atom content), each block on its own
  line (page.html_lines). An item with only a summary gets its page fetched instead
  (base.Follow): a summary is a teaser the screen cannot judge. An item whose content is
  empty is left out (a release-notes link is an anchor on one long page, not its own page).
  Full content is screened at any length (jev.question_screening: a one-line release is
  complete, not a cut abstract).
- Attribution: a feed's content is kept only for items on the feed's own host. An item that
  links elsewhere (the community scrape on raw.githubusercontent.com links claude.com) is
  read from its page, so text stored under a claude.com URL is what claude.com serves
  (security review 2026-10-20: a scrape that started carrying content would otherwise put
  its own words under an official URL).
- Not a feed (an HTML page, an error page served with 200) is a parse failure, so a feed
  that moved shows in the operations section instead of going quiet.

Parsing is feedparser's (6.0.14, BSD-2; search-first 2026-10-20: the established parser,
RSS 0.9x to 2.0 and Atom, with each format's date forms). It is handed the body as bytes:
given a str, feedparser.parse may take it for a URL or a file path and fetch or open it.
"""

import functools
import io
from collections.abc import Mapping
from datetime import date, timedelta
from time import struct_time
from typing import Final, cast
from urllib.parse import urlsplit

import feedparser  # pyright: ignore[reportMissingTypeStubs]
import httpx2

from .base import USER_AGENT, Adapter, Follow, RawDraft, one_line
from .page import article_parse, html_lines

WINDOW_DAYS: Final = 3
"""Days back from the run's date. A release posted after the 05:00 run is read on the next
day's; the margin covers a run that failed, and an item read again on a later day costs no
second claim (claims already reported are not reported again)."""
FOLLOW_LIMIT: Final = 10
"""Pages one feed may have fetched in a run (summary-only items inside the window)."""
MIN_INTERVAL_S: Final = 1.0
ACCEPT: Final = "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"


def build_request(query: str, _env: Mapping[str, str]) -> httpx2.Request:
    return httpx2.Request("GET", query, headers={"User-Agent": USER_AGENT, "Accept": ACCEPT})


def _date(entry: Mapping[str, object]) -> date | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if isinstance(value, struct_time):
            return date(value.tm_year, value.tm_mon, value.tm_mday)
    return None


def _text(entry: Mapping[str, object]) -> str:
    """The item's full content as lines, or "" when it carries only a summary (Follow)."""
    content = entry.get("content")
    if not isinstance(content, list):
        return ""
    values = (cast("Mapping[str, object]", p).get("value") for p in cast("list[object]", content))
    return "\n".join(html_lines(v) for v in values if isinstance(v, str) and v.strip())


def _entries(body: str) -> list[Mapping[str, object]]:
    """feedparser's entries, typed at the boundary (feedparser ships no type information)."""
    parsed = cast(
        "Mapping[str, object]",
        feedparser.parse(io.BytesIO(body.encode("utf-8"))),  # pyright: ignore[reportUnknownMemberType]
    )
    if not parsed.get("version"):
        raise ValueError("not an RSS or Atom feed")
    entries = parsed.get("entries")
    return cast("list[Mapping[str, object]]", entries) if isinstance(entries, list) else []


def parse(body: str, *, feed_url: str, today: date) -> list[RawDraft]:
    since = today - timedelta(days=WINDOW_DAYS)
    host = urlsplit(feed_url).hostname
    out: list[RawDraft] = []
    for entry in _entries(body):
        published = _date(entry)
        if published is None or published < since:
            continue
        link, title = entry.get("link"), entry.get("title")
        url = link if isinstance(link, str) else ""
        if urlsplit(url).hostname != host:
            text = ""  # another host's page: read it there, never take the feed's word for it
        elif not (text := _text(entry)) and "content" in entry:
            continue  # content with nothing in it: its link is not a page of its own
        out.append(
            RawDraft(
                url=url,
                title=one_line(title) if isinstance(title, str) else "",
                text=text,
                published_at=published,
            )
        )
    return out


def adapter(today: date, feed_url: str) -> Adapter:
    """The feed at `feed_url`, windowed on `today` (the run's date, so a replay keeps the same
    items)."""
    return Adapter(
        kind="feed",
        build_request=build_request,
        parse=functools.partial(parse, feed_url=feed_url, today=today),
        min_interval_s=MIN_INTERVAL_S,
        query_kind="token",
        follow=Follow(parse=article_parse, limit=FOLLOW_LIMIT),
    )
