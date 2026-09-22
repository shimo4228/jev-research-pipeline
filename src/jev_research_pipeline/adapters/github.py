"""GitHub repository search (api.github.com/search/repositories). As-of 2026-09-22.

Token optional (GITHUB_TOKEN → Authorization: Bearer). Search rate limit is 10/min
unauthenticated, 30/min with a token; pacing uses the unauthenticated bound (6 s).
Repositories without a description are skipped: there is no text to cut units from.
"""

from collections.abc import Mapping
from typing import Final

import httpx2
from pydantic import BaseModel

from .base import Adapter, RawDraft, iso_date, one_line

ENDPOINT: Final = "https://api.github.com/search/repositories"
API_VERSION: Final = "2026-03-10"
PER_PAGE: Final = 20
TOKEN_ENV: Final = "GITHUB_TOKEN"


class _Repo(BaseModel):
    full_name: str
    html_url: str
    description: str | None = None
    topics: list[str] = []
    created_at: str | None = None


class _Result(BaseModel):
    items: list[_Repo]


def build_request(query: str, env: Mapping[str, str]) -> httpx2.Request:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}
    token = env.get(TOKEN_ENV)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"q": query[:256], "sort": "updated", "order": "desc", "per_page": str(PER_PAGE)}
    return httpx2.Request("GET", ENDPOINT, params=params, headers=headers)


def parse(body: str) -> list[RawDraft]:
    drafts: list[RawDraft] = []
    for repo in _Result.model_validate_json(body).items:
        if not repo.description or not repo.description.strip():
            continue
        text = one_line(repo.description)
        if repo.topics:
            text = f"{text} Topics: {', '.join(repo.topics)}."
        drafts.append(
            RawDraft(
                url=repo.html_url,
                title=repo.full_name,
                text=text,
                published_at=iso_date(repo.created_at),
            )
        )
    return drafts


def adapter() -> Adapter:
    return Adapter(kind="github", build_request=build_request, parse=parse, min_interval_s=6.0)
