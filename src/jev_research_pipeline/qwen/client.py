"""Qwen via DashScope (decision 10), through pydantic-ai's AlibabaProvider.

Endpoint and model ids verified 2026-09-22 (packet decision 10): intl compatible-mode
endpoint (keys are region-bound); qwen3.8-max for the Japanese prose, the one generation
site left (the query and question-proposal sites were removed, design "Authored queries").
The prose is free text; the json_schema profile override below is kept so the model stays
usable for a structured site without re-deriving it (pydantic-ai 2.47's Qwen profile enables
json_schema only for qwen3.5 names).
"""

from typing import Final, Literal

import httpx2
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.providers.alibaba import AlibabaProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

DASHSCOPE_BASE_URL: Final = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
MAX: Final = "qwen3.8-max"
API_KEY_ENV: Final = "DASHSCOPE_API_KEY"

type QwenModelId = Literal["qwen3.8-max"]


def _native_json_schema(base: ModelProfile) -> ModelProfile:
    return merge_profile(
        base, ModelProfile(supports_json_schema_output=True, supports_json_object_output=True)
    )


NO_THINKING: Final = ModelSettings(extra_body={"enable_thinking": False})
"""qwen3.8 thinks by default. Measured 2026-09-23 on a two-sentence answer: flash 5.0 s ->
2.9 s, max 5.9 s -> 2.2 s with it off, and the reasoning tokens (billed as output) gone;
the first pilot's 122 s for a 705-character section was mostly thinking. Every site here
is structured output or prose over given claims, where the rubric ladder checks the text."""


THINKING: Final = ModelSettings(extra_body={"enable_thinking": True})
"""For the prose site only, by policy (qwen.prose.prose_thinking): the A/B of 2026-09-23
measured fewer fidelity flags and lower unsupported_statement with it on."""


def qwen_model(
    name: QwenModelId, http_client: httpx2.AsyncClient, *, api_key: str, thinking: bool = False
) -> OpenAIChatModel:
    provider = AlibabaProvider(
        api_key=api_key, base_url=DASHSCOPE_BASE_URL, http_client=http_client
    )
    return OpenAIChatModel(
        name,
        provider=provider,
        profile=_native_json_schema,
        settings=THINKING if thinking else NO_THINKING,
    )


class GenerationMeter:
    """Generation tokens for the operations section (↓ wanted). Counts every request,
    including validation retries and rewrites."""

    def __init__(self) -> None:
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage: RunUsage) -> None:
        self.requests += usage.requests
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
