"""Adapter contract: one typed adapter per (source, net), fixed in code (decision 4).

A net is *how* a source was reached — firehose, recommendation, citation, keyword or
exploration (packet "Discovery"). Keyword search alone converges, so the same source API
can appear under two adapters: `arxiv` keyword search and `arxiv` new listings are one
endpoint each, one `net` each, and every SourceItem records which net found it.

An adapter = (build_request, parse, pacing, optional key). fetch() never raises for
source-side trouble: a missing key, an HTTP error status, a request error (transport,
body decoding, redirects) or an unparseable body becomes FetchOutcome.failure (counted
in the operations section). A single result that fails validation (empty text, non-http
URL) is skipped and counted, not fatal to the other results. Only programming errors —
and CassetteMiss in tests — propagate.
"""

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal, Self, TypedDict
from xml.etree.ElementTree import ParseError

import httpx2
from pydantic import AwareDatetime, JsonValue, TypeAdapter, ValidationError, model_validator

from jev_research_pipeline.model import AdapterKind, DiscoveryNet, Line, SourceItem
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.model.nodes import NonEmptyText
from jev_research_pipeline.query_text import clean_query

type FailureReason = Literal["missing_key", "invalid_query", "http_status", "transport", "parse"]

USER_AGENT: Final = (
    "jev-research-pipeline/0.1 (+https://github.com/shimo4228/jev-research-pipeline; "
    "mailto:shimo4228@gmail.com)"
)
"""Sent by every adapter. Default library UAs are refused by arXiv's edge (406, measured
2026-09-22) and GitHub requires a valid UA; a contact address is arXiv's ToU etiquette."""
_MESSAGE_CHARS: Final = 200
_JSON_BODY: Final = TypeAdapter(dict[str, JsonValue])


def http_status_detail(response: httpx2.Response) -> str:
    """`<status> <kind>: <server message>` — a fetch-failure line that says why.

    kind distinguishes the 403s that look alike: a spent budget (rate limit, headers) from
    a refused caller (credentials). Headers are authoritative; the message is not
    documented and is only quoted."""
    status = response.status_code
    headers = response.headers
    if status == 403 and (
        headers.get("retry-after") or headers.get("x-ratelimit-remaining") == "0"
    ):
        kind = "rate_limit"
    elif status == 403:
        kind = "forbidden"
    elif status == 406:
        kind = "not_acceptable"
    elif status == 429:
        kind = "rate_limit"
    else:
        kind = "error"
    message = ""
    try:
        body = _JSON_BODY.validate_json(response.content)
        message = str(body.get("message", ""))[:_MESSAGE_CHARS]
    except ValidationError:
        message = response.text[:_MESSAGE_CHARS]
    reset = headers.get("x-ratelimit-reset") or headers.get("retry-after")
    suffix = f" (reset {reset})" if kind == "rate_limit" and reset else ""
    return f"{status} {kind}: {' '.join(message.split())}{suffix}".rstrip()


class RawDraft(TypedDict):
    """What a parser extracts from one result, unvalidated."""

    url: str
    title: str
    text: str
    published_at: date | None


class Draft(Value):
    """A validated RawDraft (non-empty title and text) before it becomes a SourceItem."""

    url: str
    title: NonEmptyText
    text: NonEmptyText
    published_at: date | None


class FetchFailure(Value):
    adapter: AdapterKind
    query: str
    reason: FailureReason
    detail: str


class FetchOutcome(Value):
    """Invariant: a failed fetch carries no sources (no partial results enter the store)."""

    adapter: AdapterKind
    query: str
    sources: tuple[SourceItem, ...]
    failure: FetchFailure | None
    cached: bool = False
    skipped: int = 0
    """Results dropped individually for failing validation (empty text, non-http URL)."""

    @model_validator(mode="after")
    def _failure_has_no_sources(self) -> Self:
        if self.failure is not None and self.sources:
            raise ValueError("a failed fetch carries no sources")
        return self


def one_line(text: str) -> str:
    """Collapse runs of whitespace (feeds wrap titles and abstracts)."""
    return " ".join(text.split())


def iso_date(value: object) -> date | None:
    """Leading YYYY-MM-DD of an ISO timestamp, or None when absent/unparseable."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


_LAST_REQUEST: dict[AdapterKind, float] = {}
"""When each source was last asked, process-wide (see Adapter._pace)."""
_PACE_LOCKS: dict[AdapterKind, asyncio.Lock] = {}


def reset_pacing() -> None:
    """Forget every source's last request (tests: each test is a fresh process's worth
    of traffic; a lock is bound to the event loop that first used it)."""
    _LAST_REQUEST.clear()
    _PACE_LOCKS.clear()


@dataclass
class Adapter:
    kind: AdapterKind
    build_request: Callable[[str, Mapping[str, str]], httpx2.Request]
    parse: Callable[[str], list[RawDraft]]
    min_interval_s: float
    """Minimum gap between live requests from this adapter (published rate limits)."""
    required_env: str | None = None
    """Env var that must be set or the adapter is skipped (missing_key failure)."""
    net: DiscoveryNet = "keyword"
    """Which net this adapter is. Stored on every SourceItem it produces."""
    query_kind: Literal["keyword", "token"] = "keyword"
    """A keyword query is a search string and must be searchable text; a token query is a
    code-built parameter (a category list, a paper id, a topic id) and is passed through."""

    async def _pace(self) -> None:
        """The gap is kept per source (`kind`), not per Adapter object: the run builds a
        fresh adapter for every keyword query, and a per-object clock let two arXiv
        requests go out back to back. The lock makes concurrent callers queue for it."""
        lock = _PACE_LOCKS.setdefault(self.kind, asyncio.Lock())
        async with lock:
            last = _LAST_REQUEST.get(self.kind)
            if last is not None:
                wait = self.min_interval_s - (time.monotonic() - last)
                if wait > 0:
                    await asyncio.sleep(wait)
            _LAST_REQUEST[self.kind] = time.monotonic()

    async def fetch(
        self,
        client: httpx2.AsyncClient,
        line: Line,
        query: str,
        *,
        now: AwareDatetime,
        env: Mapping[str, str],
    ) -> FetchOutcome:
        def fail(reason: FailureReason, detail: object) -> FetchOutcome:
            failure = FetchFailure(
                adapter=self.kind, query=query, reason=reason, detail=str(detail)
            )
            return FetchOutcome(adapter=self.kind, query=query, sources=(), failure=failure)

        if self.required_env is not None and not env.get(self.required_env):
            return fail("missing_key", self.required_env)
        # A keyword query must be searchable text (arXiv answers 406 to `all:,`); a token
        # query is code-built, so only an empty one is a wiring mistake worth refusing.
        unusable = clean_query(query) is None if self.query_kind == "keyword" else not query
        if unusable:
            return fail("invalid_query", query[:80] or "empty")
        await self._pace()
        try:
            response = await client.send(self.build_request(query, env))
        except httpx2.RequestError as e:
            return fail("transport", type(e).__name__)
        if response.status_code >= 400:
            return fail("http_status", http_status_detail(response))
        try:
            raws = self.parse(response.text)
        except (ValueError, ValidationError, ParseError, KeyError, TypeError) as e:
            return fail("parse", type(e).__name__)
        sources: list[SourceItem] = []
        for raw in raws:
            try:
                d = Draft.model_validate(raw)
                sources.append(
                    SourceItem.new(
                        line=line.id,
                        adapter=self.kind,
                        net=self.net,
                        url=d.url,
                        title=d.title,
                        text=d.text,
                        fetched_at=now,
                        published_at=d.published_at,
                    )
                )
            except ValidationError:
                continue
        return FetchOutcome(
            adapter=self.kind,
            query=query,
            sources=tuple(sources),
            failure=None,
            skipped=len(raws) - len(sources),
        )
