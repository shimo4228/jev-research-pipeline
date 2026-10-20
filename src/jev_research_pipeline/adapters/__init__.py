"""Typed source adapters, one module per source (decision 4). The model never picks sources."""

from . import arxiv, canary, firehose, github, hf_papers, openalex, semantic_scholar, web_search
from .base import (
    USER_AGENT,
    Adapter,
    Draft,
    FetchFailure,
    FetchOutcome,
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
    "RawDraft",
    "arxiv",
    "canary",
    "collect",
    "firehose",
    "github",
    "hf_papers",
    "http_status_kind",
    "openalex",
    "semantic_scholar",
    "web_search",
]
