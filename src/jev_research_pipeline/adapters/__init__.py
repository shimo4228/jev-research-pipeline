"""Typed source adapters, one module per source (decision 4). The model never picks sources."""

from . import arxiv, firehose, github, hf_papers, openalex, semantic_scholar, web_search
from .base import USER_AGENT, Adapter, Draft, FetchFailure, FetchOutcome, RawDraft
from .collect import collect

__all__ = [
    "USER_AGENT",
    "Adapter",
    "Draft",
    "FetchFailure",
    "FetchOutcome",
    "RawDraft",
    "arxiv",
    "collect",
    "firehose",
    "github",
    "hf_papers",
    "openalex",
    "semantic_scholar",
    "web_search",
]
