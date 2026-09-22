"""Recommendation net: Semantic Scholar's paper recommender, learned from the author's ticks.

`POST /recommendations/v1/papers` takes papers to move toward and papers to move away
from, so the author's ⭕ (and the papers behind accepted claims) become positives and the
❌ plus seeded random negatives become negatives — the shape Scholar Inbox uses to keep a
per-user recommender from collapsing onto one theme.

Keyless is documented as allowed but the unauthenticated pool is shared globally: a
single cold request answered 429 when measured (2026-09-23). This adapter therefore
treats a 429 as a policy signal and gives up for the day rather than retrying — the net's
share of the report simply drops, and the operations section says why. Set
SEMANTIC_SCHOLAR_API_KEY to get a budget of your own.

The `query` is a code-built token: `<positive id>,…|<negative id>,…`.
"""

import json
from collections.abc import Mapping
from typing import Final

import httpx2
from pydantic import BaseModel, Field

from .base import USER_AGENT, Adapter, RawDraft, iso_date, one_line

ENDPOINT: Final = "https://api.semanticscholar.org/recommendations/v1/papers"
FIELDS: Final = "title,url,abstract,externalIds,publicationDate"
LIMIT: Final = 50
API_KEY_ENV: Final = "SEMANTIC_SCHOLAR_API_KEY"
MAX_IDS: Final = 100
"""Cap on each side of the request; the pool is shared and the payload is ours to bound."""


def token(positives: list[str], negatives: list[str]) -> str:
    """The `query` of a recommendation fetch. Ids are paper ids (sha40, or `ARXIV:<id>`)."""
    return ",".join(positives[:MAX_IDS]) + "|" + ",".join(negatives[:MAX_IDS])


def split(query: str) -> tuple[list[str], list[str]]:
    positives, _, negatives = query.partition("|")
    return (
        [i for i in positives.split(",") if i],
        [i for i in negatives.split(",") if i],
    )


def build_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    positives, negatives = split(query)
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if key := env.get(API_KEY_ENV):
        headers["x-api-key"] = key
    body = json.dumps({"positivePaperIds": positives, "negativePaperIds": negatives})
    return httpx2.Request(
        "POST",
        ENDPOINT,
        params={"fields": FIELDS, "limit": str(LIMIT)},
        headers=headers,
        content=body.encode("utf-8"),
    )


class _External(BaseModel):
    # The request prefix is `ARXIV:` but the response key is `ArXiv` (measured 2026-09-23).
    arxiv: str | None = Field(default=None, alias="ArXiv")


class _Paper(BaseModel):
    title: str = ""
    url: str | None = None
    abstract: str | None = None
    external_ids: _External = Field(default=_External(), alias="externalIds")
    publication_date: str | None = Field(default=None, alias="publicationDate")


class _Recommendations(BaseModel):
    recommended_papers: list[_Paper] = Field(
        default_factory=list[_Paper], alias="recommendedPapers"
    )


def parse(body: str) -> list[RawDraft]:
    payload = _Recommendations.model_validate_json(body)
    drafts: list[RawDraft] = []
    for paper in payload.recommended_papers:
        arxiv_id = paper.external_ids.arxiv
        url = paper.url or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "")
        drafts.append(
            RawDraft(
                url=url,
                title=one_line(paper.title),
                text=one_line(paper.abstract or ""),
                published_at=iso_date(paper.publication_date),
            )
        )
    return drafts


def adapter() -> Adapter:
    return Adapter(
        kind="semantic_scholar",
        build_request=build_request,
        parse=parse,
        min_interval_s=1.0,  # keyed limit on /recommendations is 1 rps; keyless is stricter
        net="recommendation",
        query_kind="token",
    )
