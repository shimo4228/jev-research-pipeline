"""Qwen via DashScope (decision 10), through pydantic-ai's AlibabaProvider.

Endpoint and model ids verified 2026-09-22 (packet decision 10): intl compatible-mode
endpoint (keys are region-bound); qwen3.8-flash for query candidates, qwen3.8-max for
Japanese prose. Structured output = json_schema strict (supported on 3.7/3.8 by
DashScope). pydantic-ai 2.47's Qwen profile enables json_schema output only for
qwen3.5 names, so the profile is overridden here — without it NativeOutput is refused.
"""

from typing import Final, Literal

import httpx2
from pydantic_ai import PromptedOutput
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.providers.alibaba import AlibabaProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

DASHSCOPE_BASE_URL: Final = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
FLASH: Final = "deepseek-v4.1-flash"
"""The structured-output site (query candidates, question proposals). qwen3.8-flash until
2026-09-23, when its free quota ran out; deepseek-v4.1-flash on the same DashScope key and
endpoint supports Structured Outputs and enable_thinking=false (help.aliyun.com
model-studio/deepseek-v4-1-flash, read 2026-09-23). GLM-5.3 was ruled out (thinking cannot
be turned off; json_object only), kimi-k3 on price (≈ 20-30x)."""
MAX: Final = "qwen3.8-max"
API_KEY_ENV: Final = "DASHSCOPE_API_KEY"

type QwenModelId = Literal["deepseek-v4.1-flash", "qwen3.8-max"]


def flash_output[T](output: type[T]) -> PromptedOutput[T]:
    """The FLASH site's output mode: PromptedOutput (the schema goes into the prompt,
    pydantic validates, output retries re-ask). deepseek-v4.1-flash answers 400 "This
    response_format type is unavailable now" to json_schema — strict or not — although
    its docs list Structured Outputs (measured 2026-09-23); PromptedOutput returned clean
    lists on every probe. The query guard (query_text.clean_query) stays behind it."""
    return PromptedOutput(output)


def _native_json_schema(base: ModelProfile) -> ModelProfile:
    return merge_profile(
        base, ModelProfile(supports_json_schema_output=True, supports_json_object_output=True)
    )


NO_THINKING: Final = ModelSettings(extra_body={"enable_thinking": False})
"""qwen3.8 thinks by default. Measured 2026-09-23 on a two-sentence answer: flash 5.0 s ->
2.9 s, max 5.9 s -> 2.2 s with it off, and the reasoning tokens (billed as output) gone;
the first pilot's 122 s for a 705-character section was mostly thinking. Every site here
is structured output or prose over given claims, where the rubric ladder checks the text."""


def qwen_model(
    name: QwenModelId, http_client: httpx2.AsyncClient, *, api_key: str
) -> OpenAIChatModel:
    provider = AlibabaProvider(
        api_key=api_key, base_url=DASHSCOPE_BASE_URL, http_client=http_client
    )
    return OpenAIChatModel(
        name, provider=provider, profile=_native_json_schema, settings=NO_THINKING
    )


class GenerationMeter:
    """Generation tokens for the operations section (↓ wanted). Counts every request,
    including validation retries and rewrites."""

    def __init__(self) -> None:
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.output_violations = 0
        """Runs that exhausted output retries — the structured-output failure rate (operations
        section) that decides whether to move to PromptedOutput."""

    def add(self, usage: RunUsage) -> None:
        self.requests += usage.requests
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
