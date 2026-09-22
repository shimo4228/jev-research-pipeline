"""Typed source adapters, one module per source (decision 4). The model never picks sources."""

from . import arxiv, github, hf_papers, web_search
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
    "github",
    "hf_papers",
    "web_search",
]
