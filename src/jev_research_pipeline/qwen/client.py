"""Qwen via DashScope (decision 10), through pydantic-ai's AlibabaProvider.

Endpoint and model ids verified 2026-09-22 (packet decision 10): intl compatible-mode
endpoint (keys are region-bound); qwen3.8-flash for query candidates, qwen3.8-max for
Japanese prose. Structured output = json_schema strict (supported on 3.7/3.8 by
DashScope). pydantic-ai 2.47's Qwen profile enables json_schema output only for
qwen3.5 names, so the profile is overridden here — without it NativeOutput is refused.
"""

from typing import Final, Literal

import httpx2
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.providers.alibaba import AlibabaProvider
from pydantic_ai.usage import RunUsage

DASHSCOPE_BASE_URL: Final = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
FLASH: Final = "qwen3.8-flash"
MAX: Final = "qwen3.8-max"
API_KEY_ENV: Final = "DASHSCOPE_API_KEY"

type QwenModelId = Literal["qwen3.8-flash", "qwen3.8-max"]


def _native_json_schema(base: ModelProfile) -> ModelProfile:
    return merge_profile(
        base, ModelProfile(supports_json_schema_output=True, supports_json_object_output=True)
    )


def qwen_model(
    name: QwenModelId, http_client: httpx2.AsyncClient, *, api_key: str
) -> OpenAIChatModel:
    provider = AlibabaProvider(
        api_key=api_key, base_url=DASHSCOPE_BASE_URL, http_client=http_client
    )
    return OpenAIChatModel(name, provider=provider, profile=_native_json_schema)


class GenerationMeter:
    """Generation tokens for the operations section (↓ wanted). Counts every request,
    including validation retries and rewrites."""

    def __init__(self) -> None:
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.output_violations = 0
        """Runs that exhausted output retries — the NativeOutput failure rate (operations
        section) that decides whether to move to PromptedOutput."""

    def add(self, usage: RunUsage) -> None:
        self.requests += usage.requests
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
