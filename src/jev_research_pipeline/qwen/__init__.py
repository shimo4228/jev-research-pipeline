"""Qwen generation sites: query candidates (and the question proposals cut from the same
cloth) and the per-question prose. Jev still makes every judgment."""

from .client import DASHSCOPE_BASE_URL, FLASH, MAX, GenerationMeter, qwen_model
from .proposals import ProposalResult, propose_questions
from .prose import ProseResult, Rendering, render, write_prose
from .queries import QueryResult, query_candidates

__all__ = [
    "DASHSCOPE_BASE_URL",
    "FLASH",
    "MAX",
    "GenerationMeter",
    "ProposalResult",
    "ProseResult",
    "QueryResult",
    "Rendering",
    "propose_questions",
    "query_candidates",
    "qwen_model",
    "render",
    "write_prose",
]
