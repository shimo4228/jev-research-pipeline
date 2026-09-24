"""The prose model: which backend writes the one generation site left, and its meter.

JRP_PROSE_MODEL names it as `<backend>:<model>` (design "Prose model"):

    openai-codex:gpt-5.6-sol   the default (author decision 2026-09-24). The author's
                               ChatGPT/Codex subscription through pydantic-ai's
                               OpenAICodexProvider: no API key and no per-token price; use
                               counts against the plan's limits. The pipeline keeps a login
                               of its own (generation.codex, `jrp codex login`).
    dashscope:<model>          Qwen on Alibaba Cloud's DashScope intl endpoint (keys are
                               region-bound), DASHSCOPE_API_KEY. The prose bench tuned the
                               prompt on dashscope:qwen3.7-max (2026-09-23).

Both backends go through the run's one injected httpx2 client, so cassettes and OTel see
them alike.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, override

import httpx2
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModelSettings
from pydantic_ai.models.openai_codex import OpenAICodexModel
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.providers.alibaba import AlibabaProvider
from pydantic_ai.providers.openai_codex import OpenAICodexProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from .codex import CodexAuthFile, codex_auth_path

type Backend = Literal["openai-codex", "dashscope"]
BACKENDS: Final[tuple[Backend, ...]] = ("openai-codex", "dashscope")

PROSE_MODEL_ENV: Final = "JRP_PROSE_MODEL"
DEFAULT_PROSE_MODEL: Final = "openai-codex:gpt-5.6-sol"
"""GPT-5.6 Sol on the author's Codex subscription. The prompt (v7 + check6) was tuned and
read on qwen3.7-max; the bench has not been re-read on this model yet (design "Prose model")."""

DASHSCOPE_BASE_URL: Final = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_KEY_ENV: Final = "DASHSCOPE_API_KEY"


class ModelSpecError(ValueError):
    pass


class MissingCredentials(RuntimeError):
    """The prose model cannot be reached: said before a run spends anything."""


@dataclass(frozen=True)
class ModelSpec:
    backend: Backend
    name: str

    @override
    def __str__(self) -> str:
        return f"{self.backend}:{self.name}"

    @property
    def subscription(self) -> bool:
        """A flat plan, not per-token billing: its tokens are counted but cost nothing."""
        return self.backend == "openai-codex"


def parse_model(raw: str) -> ModelSpec:
    """`<backend>:<model>`. No guessing: a bare model name or an unknown backend is an
    error, not a fallback to some other model the author did not ask for."""
    backend, _, name = raw.strip().partition(":")
    match backend:
        case "openai-codex" | "dashscope" if name.strip():
            return ModelSpec(backend=backend, name=name.strip())
        case _:
            raise ModelSpecError(
                f"{raw!r}: expected <backend>:<model>, backend one of {', '.join(BACKENDS)}"
            )


def prose_model_spec(env: Mapping[str, str]) -> ModelSpec:
    try:
        return parse_model(env.get(PROSE_MODEL_ENV) or DEFAULT_PROSE_MODEL)
    except ModelSpecError as e:
        raise ModelSpecError(f"{PROSE_MODEL_ENV}={e}") from None


@dataclass(frozen=True)
class ProseAuth:
    """What reaching the prose model takes; `prose_auth` sets exactly the one its backend needs."""

    spec: ModelSpec
    api_key: str | None = None
    """DashScope's key."""
    codex_auth: Path | None = None
    """The pipeline's own Codex login file (generation.codex)."""


def prose_auth(env: Mapping[str, str], spec: ModelSpec | None = None) -> ProseAuth:
    """`spec` defaults to JRP_PROSE_MODEL; the prose bench passes its --model."""
    spec = spec or prose_model_spec(env)
    if spec.backend == "dashscope":
        key = env.get(DASHSCOPE_KEY_ENV)
        if not key:
            raise MissingCredentials(f"missing env: {DASHSCOPE_KEY_ENV} (for {spec})")
        return ProseAuth(spec=spec, api_key=key)
    path = codex_auth_path(env)
    if not path.is_file():
        raise MissingCredentials(
            f"no Codex login at {path} (for {spec}): run `uv run jrp codex login`"
        )
    return ProseAuth(spec=spec, codex_auth=path)


def _native_json_schema(base: ModelProfile) -> ModelProfile:
    return merge_profile(
        base, ModelProfile(supports_json_schema_output=True, supports_json_object_output=True)
    )


NO_THINKING: Final = ModelSettings(extra_body={"enable_thinking": False})
"""DashScope: qwen3.8 thinks by default. Measured 2026-09-23 on a two-sentence answer:
flash 5.0 s -> 2.9 s, max 5.9 s -> 2.2 s with it off, and the reasoning tokens (billed as
output) gone; the first pilot's 122 s for a 705-character section was mostly thinking."""


THINKING: Final = ModelSettings(extra_body={"enable_thinking": True})
"""DashScope, for the prose by policy (generation.prose.prose_thinking): the A/B of
2026-09-23 measured fewer fidelity flags and lower unsupported_statement with it on."""


CODEX_PROMPT_CACHE_KEY: Final = "jrp-prose"
"""Pinned. OpenAICodexModel otherwise keys the prompt cache (a field of the request body) on
each call's fresh conversation id: no call would share the cached instructions prefix,
and no request body would replay from a cassette."""


def _codex_settings(*, thinking: bool) -> OpenAIResponsesModelSettings:
    # GPT-5.6 reasons by default (at medium); thinking=False sends effort "none".
    return OpenAIResponsesModelSettings(
        thinking=thinking, openai_prompt_cache_key=CODEX_PROMPT_CACHE_KEY
    )


class Writer:
    """The prose model of one process. Every model it hands out shares one provider, so the
    Codex login is loaded once and a refresh is single-flight across the lines that run side
    by side: a second provider would spend the same single-use refresh token. The Codex
    provider attaches its auth to `http` (it only touches requests to the Codex host) and
    refuses a client that already carries one: one Writer per client."""

    def __init__(self, auth: ProseAuth, http: httpx2.AsyncClient) -> None:
        self.spec = auth.spec
        self._provider: OpenAICodexProvider | AlibabaProvider
        if auth.spec.backend == "openai-codex":
            if auth.codex_auth is None:
                raise MissingCredentials(f"no Codex login given (for {auth.spec})")
            self._provider = OpenAICodexProvider(
                credential_source=CodexAuthFile(auth.codex_auth), http_client=http
            )
        else:
            if not auth.api_key:
                raise MissingCredentials(f"missing env: {DASHSCOPE_KEY_ENV} (for {auth.spec})")
            self._provider = AlibabaProvider(
                api_key=auth.api_key, base_url=DASHSCOPE_BASE_URL, http_client=http
            )

    def model(self, *, thinking: bool) -> Model:
        if isinstance(self._provider, OpenAICodexProvider):
            return OpenAICodexModel(
                self.spec.name, provider=self._provider, settings=_codex_settings(thinking=thinking)
            )
        return OpenAIChatModel(
            self.spec.name,
            provider=self._provider,
            # kept so the model stays usable for a structured site without re-deriving it
            # (pydantic-ai 2.47's Qwen profile enables json_schema only for qwen3.5 names)
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
