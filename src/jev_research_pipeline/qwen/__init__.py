"""The one Qwen generation site: the per-question prose. Jev makes every judgment; queries
and questions are authored in questions/<slug>.md (design "Authored queries")."""

from .client import DASHSCOPE_BASE_URL, MAX, GenerationMeter, qwen_model
from .prose import ProseResult, Rendering, render, write_prose

__all__ = [
    "DASHSCOPE_BASE_URL",
    "MAX",
    "GenerationMeter",
    "ProseResult",
    "Rendering",
    "qwen_model",
    "render",
    "write_prose",
]
