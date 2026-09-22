"""Web search via Tavily (api.tavily.com/search). Selected by search-first 2026-09-22:
free monthly tier, returns title/url/content/published_date, and the only candidate whose
ToS does not expressly forbid storing results (Brave's does; Exa's is unclear; Google CSE
and Bing are closing/closed). Whether storing results is permitted remains a human
judgment before the first live recording.

Key: TAVILY_API_KEY, sent as a Bearer header (never in the body, so never in a cassette).
Without the key the adapter is skipped and the skip is recorded (missing_key).
"""

from collections.abc import Mapping
from typing import Final

import httpx2
from pydantic import BaseModel

from .base import Adapter, RawDraft, iso_date, one_line

ENDPOINT: Final = "https://api.tavily.com/search"
KEY_ENV: Final = "TAVILY_API_KEY"
MAX_RESULTS: Final = 10


class _Result(BaseModel):
    title: str
    url: str
    content: str
    published_date: str | None = None


class _Response(BaseModel):
    results: list[_Result]


def build_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    body = {"query": query, "max_results": MAX_RESULTS, "search_depth": "basic", "topic": "general"}
    headers = {"Authorization": f"Bearer {env.get(KEY_ENV, '')}"}
    return httpx2.Request("POST", ENDPOINT, json=body, headers=headers)


def parse(body: str) -> list[RawDraft]:
    return [
        RawDraft(
            url=r.url,
            title=one_line(r.title),
            text=one_line(r.content),
            published_at=iso_date(r.published_date),
        )
        for r in _Response.model_validate_json(body).results
    ]


def adapter() -> Adapter:
    return Adapter(
        kind="web_search",
        build_request=build_request,
        parse=parse,
        min_interval_s=0.0,
        required_env=KEY_ENV,
    )
