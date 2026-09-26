"""Citation and exploration nets: OpenAlex forward citations, and neighbouring topics.

- Citations: `works?filter=cites:<work id>` — who cited a paper this line already
  accepted. Snowballing is what keyword search cannot do (packet "Discovery"). The filter
  takes only a work id, so a paper known by its DOI is looked up first (resolve_work).
- Exploration: `works?filter=primary_topic.id:<topic>` for a topic *next to* the line's
  own (a sibling under the same subfield), which is where a bridge comes from.

Credits, measured from the response headers (2026-09-23): keyless is 1,000 credits and
$0.10 a day, a filtered list costs 1 credit, a `search=` costs 10, a singleton lookup is
free, and the budget resets at midnight UTC. `mailto=` no longer buys a polite pool — the
only identifier is an API key: with one the day is 10,000 credits and $1 (measured
2026-09-26 from `x-ratelimit-limit`). Adapter.fetch reads `x-ratelimit-credits-used` so
the operations section can report the day's spend, and a 429 means either the 100 rps
ceiling or an exhausted budget: `x-ratelimit-remaining` tells them apart. The arXiv
keyword search (adapters.arxiv) is an OpenAlex `search=` and spends the same budget.
"""

from collections.abc import Mapping
from typing import Final
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, Field, ValidationError

from .base import (
    USER_AGENT,
    Adapter,
    FailureReason,
    FetchFailure,
    RawDraft,
    http_status_detail,
    iso_date,
    one_line,
)

WORKS: Final = "https://api.openalex.org/works"
TOPICS: Final = "https://api.openalex.org/topics"
API_KEY_ENV: Final = "OPENALEX_API_KEY"
PER_PAGE: Final = 100
"""The documented maximum (help/api/paging, 2026-09-18); 200 is refused."""
SELECT: Final = "id,doi,ids,title,publication_date,primary_topic"
CITES: Final = "cites:"
DOI: Final = "doi:"
"""A paper addressed by DOI (nets.openalex_work): the singleton lookup's namespace, which
`cites:` does not accept."""
TOPIC: Final = "primary_topic.id:"
KEYLESS_DAILY_CREDITS: Final = 1000
"""What a keyless day buys. The config caps our own use below it."""
FILTER_CREDITS: Final = 1
"""A filtered list (`filter=` without `search=`), measured 2026-09-23."""


def cites_token(work_id: str) -> str:
    return CITES + work_id


def topic_token(topic_id: str) -> str:
    return TOPIC + topic_id


def headers(env: Mapping[str, str]) -> dict[str, str]:
    """The contact UA, and the API key as a bearer token when there is one."""
    out = {"User-Agent": USER_AGENT}
    if key := env.get(API_KEY_ENV):
        out["Authorization"] = f"Bearer {key}"
    return out


def build_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    params = {
        "filter": query,
        "sort": "publication_date:desc",
        "per_page": str(PER_PAGE),
        "select": SELECT,
    }
    return httpx2.Request("GET", WORKS, params=params, headers=headers(env))


def lookup_request(work: str, env: Mapping[str, str]) -> httpx2.Request:
    """The singleton `works/doi:<doi>`, id only. The DOI is escaped into the path: `?` and
    `#` are legal in a DOI, and a control character would make httpx2 raise InvalidURL;
    existing `%` escapes are kept (OpenAlex decodes them — measured 2026-09-25)."""
    path = quote(work, safe=":/%")
    return httpx2.Request("GET", f"{WORKS}/{path}", params={"select": "id"}, headers=headers(env))


async def resolve_work(
    client: httpx2.AsyncClient, work: str, *, env: Mapping[str, str]
) -> str | FetchFailure | None:
    """The OpenAlex work id (`W…`) of a `doi:` value, for the `cites:` filter, which takes
    nothing else: `cites:doi:10.48550/arXiv.…` answered 400 "is not a valid OpenAlex ID" on
    every line of the 2026-09-25 run. None when OpenAlex does not hold the work (404: a
    days-old arXiv paper may not be indexed yet).

    The lookup costs no credit (x-ratelimit-credits-used: 0, measured 2026-09-25) and is
    not paced: the ceiling is 100 rps and a line looks up at most its citation budget. Like
    Adapter.fetch, source-side trouble is returned as a FetchFailure, never raised."""

    def fail(reason: FailureReason, detail: str) -> FetchFailure:
        return FetchFailure(adapter="openalex", query=work, reason=reason, detail=detail)

    try:
        response = await client.send(lookup_request(work, env))
    except httpx2.RequestError as e:
        return fail("transport", type(e).__name__)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        return fail("http_status", http_status_detail(response))
    try:
        found = _Work.model_validate_json(response.content).id
    except ValidationError as e:
        return fail("parse", type(e).__name__)
    return found.rsplit("/", 1)[-1] if found else None


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


TOPIC_MARK: Final = "OpenAlex topic: "
"""What a stored OpenAlex source carries instead of an abstract: `<id> <display name>`.
The id is first because the exploration net and the cluster meter read the id, not the
name — a name is not a filter value."""


def _abstract(work: _Work) -> str:
    """OpenAlex ships no abstract under `select`; the title plus its topic is what there
    is, and screening routes a source this short to "incomplete" rather than judging it
    blind — the citation net's job is to surface the paper, not to summarize it."""
    topic = work.primary_topic
    id_ = topic.id.rsplit("/", 1)[-1] if topic is not None and topic.id else "unknown"
    name = (topic.display_name if topic is not None else None) or ""
    return one_line(f"{work.title or ''} — {TOPIC_MARK}{id_} {name}")


def topic_of(text: str) -> str | None:
    """The topic id in a stored OpenAlex source's text, or None."""
    if TOPIC_MARK not in text:
        return None
    tail = text.rsplit(TOPIC_MARK, 1)[1].split(" ", 1)[0].strip()
    return tail if tail.startswith("T") else None


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
    """Topic ids of the works in a response, unprefixed (`/works` filters want `T####`)."""
    return [
        w.primary_topic.id.rsplit("/", 1)[-1]
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
        credit_cost=FILTER_CREDITS,
    )


def exploration_adapter() -> Adapter:
    return Adapter(
        kind="openalex",
        build_request=build_request,
        parse=parse,
        min_interval_s=0.5,
        net="exploration",
        query_kind="token",
        credit_cost=FILTER_CREDITS,
    )
