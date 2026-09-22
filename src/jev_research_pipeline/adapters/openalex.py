"""Citation and exploration nets: OpenAlex forward citations, and neighbouring topics.

- Citations: `works?filter=cites:<work id>` — who cited a paper this line already
  accepted. Snowballing is what keyword search cannot do (packet "Discovery").
- Exploration: `works?filter=primary_topic.id:<topic>` for a topic *next to* the line's
  own (a sibling under the same subfield), which is where a bridge comes from.

Credits, measured from the response headers (2026-09-23): keyless is 1,000 credits and
$0.10 a day, a filtered list costs 1 credit, a `search=` costs 10, a singleton lookup is
free, and the budget resets at midnight UTC. `mailto=` no longer buys a polite pool — the
only identifier is an API key. credits_used() reads the headers so the operations section
can report the day's spend, and a 429 means either the 100 rps ceiling or an exhausted
budget: `x-ratelimit-remaining` tells them apart.
"""

from collections.abc import Mapping
from typing import Final

import httpx2
from pydantic import BaseModel, Field

from .base import USER_AGENT, Adapter, RawDraft, iso_date, one_line

WORKS: Final = "https://api.openalex.org/works"
TOPICS: Final = "https://api.openalex.org/topics"
API_KEY_ENV: Final = "OPENALEX_API_KEY"
PER_PAGE: Final = 100
"""The documented maximum (help/api/paging, 2026-09-18); 200 is refused."""
SELECT: Final = "id,doi,ids,title,publication_date,primary_topic"
CITES: Final = "cites:"
TOPIC: Final = "primary_topic.id:"
KEYLESS_DAILY_CREDITS: Final = 1000
"""What a keyless day buys. The config caps our own use below it."""


def cites_token(work_id: str) -> str:
    return CITES + work_id


def topic_token(topic_id: str) -> str:
    return TOPIC + topic_id


def build_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    params = {
        "filter": query,
        "sort": "publication_date:desc",
        "per_page": str(PER_PAGE),
        "select": SELECT,
    }
    headers = {"User-Agent": USER_AGENT}
    if key := env.get(API_KEY_ENV):
        headers["Authorization"] = f"Bearer {key}"
    return httpx2.Request("GET", WORKS, params=params, headers=headers)


def credits_used(response: httpx2.Response) -> int:
    """What this response cost, from `x-ratelimit-credits-used` (0 when absent)."""
    try:
        return int(response.headers.get("x-ratelimit-credits-used", "0"))
    except ValueError:
        return 0


def credits_remaining(response: httpx2.Response) -> int | None:
    try:
        return int(response.headers["x-ratelimit-remaining"])
    except (KeyError, ValueError):
        return None


class _Topic(BaseModel):
    id: str | None = None
    display_name: str | None = None


class _Work(BaseModel):
    id: str | None = None
    doi: str | None = None
    title: str | None = None
    publication_date: str | None = None
    primary_topic: _Topic | None = None


class _Works(BaseModel):
    results: list[_Work] = Field(default_factory=list[_Work])


def _abstract(work: _Work) -> str:
    """OpenAlex ships no abstract under `select`; the title plus its topic is what there
    is, and screening routes a source this short to "incomplete" rather than judging it
    blind — the citation net's job is to surface the paper, not to summarize it."""
    name = work.primary_topic.display_name if work.primary_topic else None
    return one_line(f"{work.title or ''} — OpenAlex topic: {name or 'unknown'}")


def parse(body: str) -> list[RawDraft]:
    return [
        RawDraft(
            url=work.doi or work.id or "",
            title=one_line(work.title or ""),
            text=_abstract(work),
            published_at=iso_date(work.publication_date),
        )
        for work in _Works.model_validate_json(body).results
    ]


def topics_of(body: str) -> list[str]:
    """Topic ids of the works in a response — the cluster meter's input."""
    return [
        w.primary_topic.id
        for w in _Works.model_validate_json(body).results
        if w.primary_topic is not None and w.primary_topic.id
    ]


def citation_adapter() -> Adapter:
    return Adapter(
        kind="openalex",
        build_request=build_request,
        parse=parse,
        min_interval_s=0.5,
        net="citation",
        query_kind="token",
    )


def exploration_adapter() -> Adapter:
    return Adapter(
        kind="openalex",
        build_request=build_request,
        parse=parse,
        min_interval_s=0.5,
        net="exploration",
        query_kind="token",
    )
