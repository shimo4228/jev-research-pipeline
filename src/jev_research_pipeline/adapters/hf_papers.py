"""Hugging Face papers search (huggingface.co/api/papers/search, JSON, no auth). As-of 2026-09-22.

Rate limit: the search bucket allows 50 requests / 5 min per IP → one request per 6 s.
"""

from collections.abc import Mapping
from typing import Final

import httpx2
from pydantic import BaseModel, Field, TypeAdapter

from .base import USER_AGENT, Adapter, RawDraft, iso_date, one_line

ENDPOINT: Final = "https://huggingface.co/api/papers/search"
LIMIT: Final = 20


class _Paper(BaseModel):
    id: str
    title: str
    summary: str
    published_at: str | None = Field(default=None, alias="publishedAt")


class _Hit(BaseModel):
    paper: _Paper


_HITS: Final = TypeAdapter(list[_Hit])


def build_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    return httpx2.Request(
        "GET",
        ENDPOINT,
        params={"q": query[:250], "limit": str(LIMIT)},
        headers={"User-Agent": USER_AGENT},
    )


def parse(body: str) -> list[RawDraft]:
    return [
        RawDraft(
            url=f"https://huggingface.co/papers/{hit.paper.id}",
            title=one_line(hit.paper.title),
            text=one_line(hit.paper.summary),
            published_at=iso_date(hit.paper.published_at),
        )
        for hit in _HITS.validate_json(body)
    ]


def adapter() -> Adapter:
    return Adapter(kind="hf_papers", build_request=build_request, parse=parse, min_interval_s=6.0)
