"""The one generation site: the per-question prose, written by the model JRP_PROSE_MODEL
names (openai-codex, claude-code, anthropic or dashscope; the code default is GPT-6 Luna on
the Codex subscription, generation.client). Jev makes every judgment; queries and questions are authored in
questions/<slug>.md (design "Authored queries")."""

from .client import (
    DEFAULT_PROSE_MODEL,
    PROSE_RETRIES,
    GenerationMeter,
    MissingCredentials,
    ModelSpec,
    ModelSpecError,
    ProseAuth,
    Writer,
    parse_model,
    prose_auth,
    prose_model_spec,
)
from .prose import ProseResult, Rendering, render, write_prose

__all__ = [
    "DEFAULT_PROSE_MODEL",
    "PROSE_RETRIES",
    "GenerationMeter",
    "MissingCredentials",
    "ModelSpec",
    "ModelSpecError",
    "ProseAuth",
    "ProseResult",
    "Rendering",
    "Writer",
    "parse_model",
    "prose_auth",
    "prose_model_spec",
    "render",
    "write_prose",
]
