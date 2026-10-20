"""Typed source adapters, one module per source (decision 4). The model never picks sources."""

from . import (
    arxiv,
    canary,
    feed,
    firehose,
    github,
    hf_papers,
    openalex,
    page,
    semantic_scholar,
    sitemap,
    web_search,
)
from .base import (
    USER_AGENT,
    Adapter,
    Draft,
    FetchFailure,
    FetchOutcome,
    Follow,
    RawDraft,
    http_status_kind,
)
from .collect import collect

__all__ = [
    "USER_AGENT",
    "Adapter",
    "Draft",
    "FetchFailure",
    "FetchOutcome",
    "Follow",
    "RawDraft",
    "arxiv",
    "canary",
    "collect",
    "feed",
    "firehose",
    "github",
    "hf_papers",
    "http_status_kind",
    "openalex",
    "page",
    "semantic_scholar",
    "sitemap",
    "web_search",
]
