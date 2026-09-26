"""arXiv keyword search, through OpenAlex restricted to the arXiv source. As-of 2026-09-26.

`works?search=<words>&filter=primary_location.source.id:S4306400194` — OpenAlex's full text
search over the works whose primary location is arXiv, newest first. Why not arXiv's own
API: since 2026-09-24 export.arxiv.org answers 406 to every Python client (httpx2 and
urllib) while curl gets 200 for the same bytes, even for a query no cache held; other
projects report the same 406 since 2026-09-13. The author decided against a client
workaround (it would be evading bot detection), so that path was removed.

Measured 2026-09-26: the search answers with arXiv works whose DOI is the DataCite form
`https://doi.org/10.48550/arxiv.<id>`, the newest ~3 days behind the announcement. A search
costs 10 credits (a filtered list 1), counted against the same OpenAlex daily budget as
the citation net. The SourceItem keeps adapter kind "arxiv" and the URL
`https://arxiv.org/abs/<id>` — the form the RSS firehose stores (no version) — so the same
paper found by both nets is one node. The abstract comes as `abstract_inverted_index`
(word → positions) and is put back in order; a work without one fails validation and is
skipped, like any result with no text.
"""

from collections.abc import Mapping
from typing import Final
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, Field

from .base import Adapter, RawDraft, iso_date, one_line
from .openalex import WORKS, headers

SOURCE: Final = "S4306400194"
"""arXiv as an OpenAlex source."""
MAX_RESULTS: Final = 20
SEARCH_CREDITS: Final = 10
"""A `search=` list, measured from x-ratelimit-credits-used (2026-09-23)."""
SELECT: Final = "id,doi,title,publication_date,abstract_inverted_index"
DOI_PREFIX: Final = "10.48550/arxiv."
"""arXiv's DataCite DOI prefix, lower-cased (OpenAlex answers `arxiv`, arXiv writes `arXiv`)."""
ABS: Final = "https://arxiv.org/abs/"


class _Work(BaseModel):
    doi: str | None = None
    title: str | None = None
    publication_date: str | None = None
    abstract_inverted_index: dict[str, list[int]] | None = None


class _Works(BaseModel):
    results: list[_Work] = Field(default_factory=list[_Work])


def abs_url(doi: str | None) -> str:
    """`https://arxiv.org/abs/<id>` from an arXiv DOI, or "" (fails URL validation)."""
    tail = (doi or "").split("doi.org/", 1)[-1]
    if not tail.lower().startswith(DOI_PREFIX):
        return ""
    return ABS + tail[len(DOI_PREFIX) :]


def abstract(index: Mapping[str, list[int]] | None) -> str:
    """Plain text of an inverted index: every word placed at each of its positions."""
    if not index:
        return ""
    at = {pos: word for word, positions in index.items() for pos in positions}
    return one_line(" ".join(at[pos] for pos in sorted(at)))


def _draft(work: _Work) -> RawDraft:
    return RawDraft(
        url=abs_url(work.doi),
        title=one_line(work.title or ""),
        text=abstract(work.abstract_inverted_index),
        published_at=iso_date(work.publication_date),
    )


def build_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    params = {
        "search": query,
        "filter": f"primary_location.source.id:{SOURCE}",
        "sort": "publication_date:desc",
        "per_page": str(MAX_RESULTS),
        "select": SELECT,
    }
    return httpx2.Request("GET", WORKS, params=params, headers=headers(env))


def parse(body: str) -> list[RawDraft]:
    return [_draft(work) for work in _Works.model_validate_json(body).results]


def paper_request(arxiv_id: str, env: Mapping[str, str]) -> httpx2.Request:
    """The singleton `works/doi:10.48550/arXiv.<id>` with its abstract (free: a singleton
    costs no credit). A 404 means OpenAlex has not indexed the paper yet."""
    path = quote(f"doi:10.48550/arXiv.{arxiv_id}", safe=":/")
    return httpx2.Request("GET", f"{WORKS}/{path}", params={"select": SELECT}, headers=headers(env))


def paper_parse(body: str) -> list[RawDraft]:
    return [_draft(_Work.model_validate_json(body))]


def adapter() -> Adapter:
    return Adapter(
        kind="arxiv",
        build_request=build_request,
        parse=parse,
        min_interval_s=0.5,
        credit_cost=SEARCH_CREDITS,
    )
