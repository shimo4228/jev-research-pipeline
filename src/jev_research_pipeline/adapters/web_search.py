"""Web search via Tavily (api.tavily.com/search). Selected by search-first 2026-09-22:
free monthly tier, returns title/url/content/published_date, and the only candidate whose
ToS does not expressly forbid storing results (Brave's does; Exa's is unclear; Google CSE
and Bing are closing/closed). Whether storing results is permitted remains a human
judgment before the first live recording.

Key: TAVILY_API_KEY, sent as a Bearer header (never in the body, so never in a cassette).
Without the key the adapter is skipped and the skip is recorded (missing_key).

A line's `web_time_range` (config.toml `[tracks.<slug>]`, pipeline.nets.for_line) narrows its
searches to results published in the last day / week / month / year and asks for each
result's published_date, which Tavily returns only when asked or on topic "news"
(docs.tavily.com /search, 2026-10-20). A line without it sends the request unchanged.
"""

import functools
from collections.abc import Mapping
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Final, Literal

import httpx2
from pydantic import BaseModel

from .base import USER_AGENT, Adapter, RawDraft, iso_date, one_line

ENDPOINT: Final = "https://api.tavily.com/search"
KEY_ENV: Final = "TAVILY_API_KEY"
MAX_RESULTS: Final = 10
type TimeRange = Literal["day", "week", "month", "year"]
TIME_RANGES: Final[tuple[TimeRange, ...]] = ("day", "week", "month", "year")


class _Result(BaseModel):
    title: str
    url: str
    content: str
    published_date: str | None = None


class _Response(BaseModel):
    results: list[_Result]


def build_request(
    query: str, env: Mapping[str, str], *, time_range: TimeRange | None = None
) -> httpx2.Request:
    body: dict[str, object] = {
        "query": query,
        "max_results": MAX_RESULTS,
        "search_depth": "basic",
        "topic": "general",
    }
    if time_range is not None:
        body |= {"time_range": time_range, "include_published_date": True}
    headers = {"Authorization": f"Bearer {env.get(KEY_ENV, '')}", "User-Agent": USER_AGENT}
    return httpx2.Request("POST", ENDPOINT, json=body, headers=headers)


def published(value: str | None) -> date | None:
    """A result's published_date: Tavily writes RFC 822 ("Fri, 16 Oct 2026 17:00:00 GMT",
    measured 2026-10-20); an ISO date is read too."""
    if value is None:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, OverflowError):
        return iso_date(value)


def parse(body: str) -> list[RawDraft]:
    return [
        RawDraft(
            url=r.url,
            title=one_line(r.title),
            text=one_line(r.content),
            published_at=published(r.published_date),
        )
        for r in _Response.model_validate_json(body).results
    ]


def adapter(time_range: TimeRange | None = None) -> Adapter:
    """Tavily search; `time_range` = the line's web_time_range (module docstring)."""
    return Adapter(
        kind="web_search",
        build_request=functools.partial(build_request, time_range=time_range),
        parse=parse,
        min_interval_s=0.0,
        required_env=KEY_ENV,
    )
