"""Adapter contract: one typed adapter per source, fixed in code per line (decision 4).

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
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Self, TypedDict
from xml.etree.ElementTree import ParseError

import httpx2
from pydantic import AwareDatetime, ValidationError, model_validator

from jev_research_pipeline.model import AdapterKind, Line, SourceItem
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.model.nodes import NonEmptyText

type FailureReason = Literal["missing_key", "http_status", "transport", "parse"]


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


@dataclass
class Adapter:
    kind: AdapterKind
    build_request: Callable[[str, Mapping[str, str]], httpx2.Request]
    parse: Callable[[str], list[RawDraft]]
    min_interval_s: float
    """Minimum gap between live requests from this adapter (published rate limits)."""
    required_env: str | None = None
    """Env var that must be set or the adapter is skipped (missing_key failure)."""
    _last_request: float | None = field(default=None, init=False, repr=False)

    async def _pace(self) -> None:
        if self._last_request is not None:
            wait = self.min_interval_s - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_request = time.monotonic()

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
        await self._pace()
        try:
            response = await client.send(self.build_request(query, env))
        except httpx2.RequestError as e:
            return fail("transport", type(e).__name__)
        if response.status_code >= 400:
            return fail("http_status", response.status_code)
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
