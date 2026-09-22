"""Qwen generation sites (packet: exactly two — query candidates and report prose)."""

from .client import DASHSCOPE_BASE_URL, FLASH, MAX, GenerationMeter, qwen_model
from .prose import ProseResult, Rendering, render, write_prose
from .queries import QueryResult, query_candidates

__all__ = [
    "DASHSCOPE_BASE_URL",
    "FLASH",
    "MAX",
    "GenerationMeter",
    "ProseResult",
    "QueryResult",
    "Rendering",
    "query_candidates",
    "qwen_model",
    "render",
    "write_prose",
]
