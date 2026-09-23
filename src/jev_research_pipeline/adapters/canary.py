"""Fetch a canary by its URL (packet "Search-first synthesis": canary papers are known key
sources that must screen Keep — SAFE). A probe, not a net: the nets may or may not reach a
canary on a given day, and a screen that drifted is only visible if the canary is judged
every day. Each kind goes through an ordinary Adapter, so pacing and failures behave like
every other fetch.

- github.com/<owner>/<repo>  → its README through the GitHub API (a description of ~100
                               characters is too little to judge evidence by; search also
                               leaves forks out, and one canary is a fork)
- arxiv.org/abs/<id>         → arXiv API `id_list=<id>`
- any other https page       → the page itself, tags stripped
"""

import functools
import html
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Final

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline.model import Line, SourceItem

from .arxiv import ENDPOINT as ARXIV_ENDPOINT
from .arxiv import HEADERS as ARXIV_HEADERS
from .arxiv import adapter as arxiv_adapter
from .base import USER_AGENT, Adapter, RawDraft, one_line
from .github import adapter as github_adapter
from .github import build_request as github_request

_GITHUB: Final = re.compile(r"^https://github\.com/([\w.-]+/[\w.-]+?)/?$")
_ARXIV: Final = re.compile(r"^https://arxiv\.org/abs/([\w.]+?)(v\d+)?/?$")
_TAG: Final = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.DOTALL | re.IGNORECASE)
_TITLE: Final = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_MAIN: Final = re.compile(r"<(main|article)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_MD: Final = re.compile(r"!\[[^\]]*\]\([^)]*\)|[`#*>|]+")
PAGE_CHARS: Final = 4000


def _readme(query: str, env: Mapping[str, str]) -> httpx2.Request:
    headers = dict(github_request("x", env).headers)  # UA, API version, token
    headers["Accept"] = "application/vnd.github.raw+json"
    return httpx2.Request("GET", f"https://api.github.com/repos/{query}/readme", headers=headers)


def readme_parse(repo: str, url: str, body: str) -> list[RawDraft]:
    """The README as plain text: markup and HTML stripped, the first PAGE_CHARS kept."""
    text = one_line(html.unescape(_TAG.sub(" ", _MD.sub(" ", body))))[:PAGE_CHARS]
    return [RawDraft(url=url, title=repo, text=text, published_at=None)]


def _arxiv_id(query: str, _env: Mapping[str, str]) -> httpx2.Request:
    return httpx2.Request("GET", ARXIV_ENDPOINT, params={"id_list": query}, headers=ARXIV_HEADERS)


def _page(query: str, _env: Mapping[str, str]) -> httpx2.Request:
    return httpx2.Request("GET", query, headers={"User-Agent": USER_AGENT})


def page_parse(url: str, body: str) -> list[RawDraft]:
    """Title and text of a page; the <main> or <article> element when there is one, so
    the navigation that opens most docs pages does not fill the excerpt."""
    found = _TITLE.search(body)
    title = one_line(html.unescape(found.group(1))) if found else url
    main = _MAIN.search(body)
    content = main.group(0) if main else body
    text = one_line(html.unescape(_TAG.sub(" ", content)))[:PAGE_CHARS]
    return [RawDraft(url=url, title=title, text=text, published_at=None)]


def plan(url: str) -> tuple[Adapter, str] | None:
    """The adapter and query that fetch this canary, or None for a non-https URL."""
    if m := _GITHUB.match(url):
        repo = m.group(1)
        adapter = replace(
            github_adapter(),
            build_request=_readme,
            parse=functools.partial(readme_parse, repo, url),
            query_kind="token",
        )
        return adapter, repo
    if m := _ARXIV.match(url):
        return replace(arxiv_adapter(), build_request=_arxiv_id, query_kind="token"), m.group(1)
    if url.startswith("https://"):
        adapter = Adapter(
            kind="web_search",
            build_request=_page,
            parse=lambda body: page_parse(url, body),
            min_interval_s=1.0,
            query_kind="token",
        )
        return adapter, url
    return None


async def fetch(
    client: httpx2.AsyncClient,
    line: Line,
    url: str,
    *,
    now: AwareDatetime,
    env: Mapping[str, str],
) -> SourceItem | str:
    """The canary as a SourceItem, or a one-line reason it could not be fetched."""
    planned = plan(url)
    if planned is None:
        return "https でない URL"
    adapter, query = planned
    out = await adapter.fetch(client, line, query, now=now, env=env)
    if out.failure is not None:
        return f"{out.failure.reason} {out.failure.detail}"[:120]
    return out.sources[0] if out.sources else "取得結果なし"
