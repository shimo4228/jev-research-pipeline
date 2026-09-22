"""Firehose net: what was announced today, with no query at all.

Keyword search is exploitation and converges (packet "Discovery"). The firehose is the
opposite end: every new listing in a few fixed categories, screened per question by Jev.
No key, no query — the "query" is the code-built category token or the date.

- arXiv new listings: `https://rss.arxiv.org/rss/<cat>+<cat>` (search-first 2026-09-23;
  the feed carries the full abstract and an `arxiv:announce_type` of new / cross /
  replace / replace-cross — only `new` and `cross` are today's announcements). The
  description is prefixed "arXiv:<id>vN Announce Type: new", which is stripped here.
  Empty on weekends (skipDays) — that is the feed working, not a failure.
- Hugging Face daily papers: `https://huggingface.co/api/daily_papers?date=&limit=`
  (live-verified keyless JSON, undocumented — the field set is pinned by a golden test;
  `paper.summary` is the abstract and the url is built from `paper.id`).
"""

import re
from collections.abc import Mapping
from typing import Final

import httpx2
from defusedxml import ElementTree
from pydantic import BaseModel, Field, TypeAdapter

from .base import USER_AGENT, Adapter, RawDraft, iso_date, one_line

ARXIV_RSS: Final = "https://rss.arxiv.org/rss/"
DEFAULT_CATEGORIES: Final = ("cs.AI", "cs.CL", "cs.LG", "cs.HC")
HF_DAILY: Final = "https://huggingface.co/api/daily_papers"
HF_LIMIT: Final = 50
_ANNOUNCE_RE: Final = re.compile(r"^arXiv:\S+\s+Announce Type:\s*(\S+)\s*", re.I)
_TODAY: Final = ("new", "cross")
_ARXIV_NS: Final = {"arxiv": "http://arxiv.org/schemas/atom"}
HEADERS: Final = {"Accept": "application/rss+xml, application/xml", "User-Agent": USER_AGENT}


def categories_token(categories: tuple[str, ...] = DEFAULT_CATEGORIES) -> str:
    """The `query` of an arXiv firehose fetch: the categories, in one feed."""
    return "+".join(categories)


def arxiv_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    return httpx2.Request("GET", ARXIV_RSS + query, headers=HEADERS)


def arxiv_parse(body: str) -> list[RawDraft]:
    root = ElementTree.fromstring(body, forbid_dtd=True)
    drafts: list[RawDraft] = []
    for item in root.iter("item"):
        description = item.findtext("description", default="")
        announce = _ANNOUNCE_RE.match(description.strip())
        if announce is not None and announce.group(1).lower() not in _TODAY:
            continue  # a replacement is not today's announcement
        text = _ANNOUNCE_RE.sub("", description.strip(), count=1)
        drafts.append(
            RawDraft(
                url=item.findtext("link", default=""),
                title=one_line(item.findtext("title", default="")),
                text=one_line(text),
                published_at=None,  # RSS pubDate is the announcement, not the submission
            )
        )
    return drafts


def hf_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    params = {"date": query, "limit": str(HF_LIMIT)}
    headers = dict(HEADERS)
    if token := env.get("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"  # keyless works; a token raises the limit
    return httpx2.Request("GET", HF_DAILY, params=params, headers=headers)


class _Paper(BaseModel):
    id: str = ""
    title: str = ""
    summary: str = ""
    published_at: str | None = Field(default=None, alias="publishedAt")


class _Daily(BaseModel):
    paper: _Paper = _Paper()


_DAILY: Final = TypeAdapter(list[_Daily])


def hf_parse(body: str) -> list[RawDraft]:
    return [
        RawDraft(
            url=f"https://huggingface.co/papers/{d.paper.id}" if d.paper.id else "",
            title=one_line(d.paper.title),
            text=one_line(d.paper.summary),
            published_at=iso_date(d.paper.published_at),
        )
        for d in _DAILY.validate_json(body)
    ]


def arxiv_adapter() -> Adapter:
    return Adapter(
        kind="arxiv",
        build_request=arxiv_request,
        parse=arxiv_parse,
        min_interval_s=3.0,  # arXiv ToU, one request every three seconds
        net="firehose",
        query_kind="token",
    )


def hf_adapter() -> Adapter:
    return Adapter(
        kind="hf_papers",
        build_request=hf_request,
        parse=hf_parse,
        min_interval_s=1.0,
        net="firehose",
        query_kind="token",
    )
