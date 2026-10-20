"""The prose model: which backend writes the one generation site left, and its meter.

JRP_PROSE_MODEL names it as `<backend>:<model>` (design "Prose model"):

    openai-codex:gpt-6-luna    the default (author decisions 2026-09-24 / 09-27). The author's
                               ChatGPT/Codex subscription through pydantic-ai's
                               OpenAICodexProvider: no API key and no per-token price; use
                               counts against the plan's limits. The pipeline keeps a login
                               of its own (generation.codex, `jrp codex login`).
    dashscope:<model>          Qwen on Alibaba Cloud's DashScope intl endpoint (keys are
                               region-bound), DASHSCOPE_API_KEY. The prose bench tuned the
                               prompt on dashscope:qwen3.7-max (2026-09-23).
    claude-code:<model>        Claude on the author's Claude subscription through `claude -p`
                               (generation.claude_code): the prose bench's writer, and a
                               production writer one env var away (author decision 2026-10-01).
    anthropic:<model>          Claude on the Claude API, ANTHROPIC_API_KEY: per-token billing,
                               which the monthly API credits of a Max plan pay (they do not cover
                               Claude Code, so not claude-code:). Same models as claude-code:.

The three HTTP backends go through the run's one injected httpx2 client, so cassettes and OTel
see them alike; claude-code is a subprocess and sees neither.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, override

import httpx2
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModelSettings
from pydantic_ai.models.openai_codex import OpenAICodexModel
from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.providers.alibaba import AlibabaProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai_codex import (
    CredentialsPersistenceError,
    CredentialsRefreshError,
    OpenAICodexProvider,
)
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from .claude_code import CLAUDE_BIN_ENV, ClaudeAuthError, claude_bin, claude_code_model
from .codex import CodexAuthFile, codex_auth_path

type Backend = Literal["openai-codex", "dashscope", "claude-code", "anthropic"]
BACKENDS: Final[tuple[Backend, ...]] = ("openai-codex", "dashscope", "claude-code", "anthropic")

PROSE_MODEL_ENV: Final = "JRP_PROSE_MODEL"
DEFAULT_PROSE_MODEL: Final = "openai-codex:gpt-6-luna"
"""GPT-6 Luna on the author's Codex subscription: the production writer since 2026-09-27, and
the model the prompt (v10 + check6) was read on, on the 3 hard bench cases (not yet on holdout;
design "Prose bench"). Every test that pins it replays a synthetic cassette (tests/fakes.py)."""

DASHSCOPE_BASE_URL: Final = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_KEY_ENV: Final = "DASHSCOPE_API_KEY"
ANTHROPIC_KEY_ENV: Final = "ANTHROPIC_API_KEY"


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
        return self.backend in ("openai-codex", "claude-code")


def parse_model(raw: str) -> ModelSpec:
    """`<backend>:<model>`. No guessing: a bare model name or an unknown backend is an
    error, not a fallback to some other model the author did not ask for."""
    backend, _, name = raw.strip().partition(":")
    match backend:
        case "openai-codex" | "dashscope" | "claude-code" | "anthropic" if name.strip():
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
    """DashScope's or the Claude API's key."""
    codex_auth: Path | None = None
    """The pipeline's own Codex login file (generation.codex)."""
    claude_bin: Path | None = None
    """The Claude Code CLI (generation.claude_code); its login is Claude Code's own."""


def prose_auth(env: Mapping[str, str], spec: ModelSpec | None = None) -> ProseAuth:
    """`spec` defaults to JRP_PROSE_MODEL; the prose bench passes its --model."""
    spec = spec or prose_model_spec(env)
    if (key_env := _key_env(spec)) is not None:
        key = env.get(key_env)
        if not key:
            raise MissingCredentials(f"missing env: {key_env} (for {spec})")
        return ProseAuth(spec=spec, api_key=key)
    if spec.backend == "claude-code":
        binary = claude_bin(env)
        if binary is None:
            raise MissingCredentials(
                f"no Claude Code CLI (for {spec}): install it, or set {CLAUDE_BIN_ENV}"
            )
        return ProseAuth(spec=spec, claude_bin=binary)
    path = codex_auth_path(env)
    if not path.is_file():
        raise MissingCredentials(f"no Codex login at {path} (for {spec}): run `jrp codex login`")
    return ProseAuth(spec=spec, codex_auth=path)


def _key_env(spec: ModelSpec) -> str | None:
    """The env var holding an API-key backend's key; None for the two logins."""
    match spec.backend:
        case "dashscope":
            return DASHSCOPE_KEY_ENV
        case "anthropic":
            return ANTHROPIC_KEY_ENV
        case "openai-codex" | "claude-code":
            return None


def credit_exhausted(error: ModelHTTPError) -> bool:
    """The Claude API's answer once the organization's credits are spent: a 400 whose message
    says so (platform docs "API credits for Max and Team plans", as-of 2026-10-19). It repeats
    on every call until the next month's credits arrive or a human buys some, so the weekly
    review's monitoring judge stops on it (pipeline.monitor)."""
    return error.status_code == 400 and "credit balance is too low" in str(error.body)


def auth_failure(error: BaseException) -> bool:
    """Whether a failed prose call was refused for its credentials rather than for its load
    or its content: the Codex grant rejected on refresh or its refresh not saved
    (pydantic-ai's credential errors), a 401/403 from an HTTP backend, the Claude API's
    credits spent, or the Claude Code CLI not signed in. Unlike a timeout it repeats on every
    draft of every line until a human acts, so the run's notification names it
    (pipeline.health)."""
    if isinstance(error, ModelHTTPError):
        return error.status_code in (401, 403) or credit_exhausted(error)
    return isinstance(
        error, CredentialsRefreshError | CredentialsPersistenceError | ClaudeAuthError
    )


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
    # The Codex models reason by default; thinking=False sends effort "none". pydantic-ai 2.47
    # sends no `reasoning` for a model its profile does not know (gpt-6-luna): there neither
    # setting reaches the wire (tests/test_codex.py pins it).
    return OpenAIResponsesModelSettings(
        thinking=thinking, openai_prompt_cache_key=CODEX_PROMPT_CACHE_KEY
    )


def _anthropic_settings(*, thinking: bool) -> AnthropicModelSettings:
    # As claude-code: thinking=True is the model's default (adaptive thinking on the Claude 5
    # models), thinking=False asks for low effort rather than no thinking.
    return AnthropicModelSettings(thinking=True if thinking else "low")


class Writer:
    """The prose model of one process. Every model it hands out shares one provider, so the
    Codex login is loaded once and a refresh is single-flight across the lines that run side
    by side: a second provider would spend the same single-use refresh token. The Codex
    provider attaches its auth to `http` (it only touches requests to the Codex host) and
    refuses a client that already carries one: one Writer per client.

    `max_retries` sets how often the Claude API SDK retries a request by itself (a 408, 409,
    429, 5xx or lost connection; twice when None, the SDK's default), on the `anthropic:`
    backend only. The weekly review's monitoring judge passes 0, since it stops at the first
    429 instead (pipeline.monitor)."""

    def __init__(
        self, auth: ProseAuth, http: httpx2.AsyncClient, *, max_retries: int | None = None
    ) -> None:
        self.spec = auth.spec
        self._provider: OpenAICodexProvider | AlibabaProvider | AnthropicProvider | Path
        if auth.spec.backend == "claude-code":
            if auth.claude_bin is None:
                raise MissingCredentials(f"no Claude Code CLI given (for {auth.spec})")
            self._provider = auth.claude_bin
        elif auth.spec.backend == "openai-codex":
            if auth.codex_auth is None:
                raise MissingCredentials(f"no Codex login given (for {auth.spec})")
            self._provider = OpenAICodexProvider(
                credential_source=CodexAuthFile(auth.codex_auth), http_client=http
            )
        elif not auth.api_key:
            raise MissingCredentials(f"missing env: {_key_env(auth.spec)} (for {auth.spec})")
        elif auth.spec.backend == "anthropic":
            provider = AnthropicProvider(api_key=auth.api_key, http_client=http)
            if max_retries is not None:
                provider.client.max_retries = max_retries
            self._provider = provider
        else:
            self._provider = AlibabaProvider(
                api_key=auth.api_key, base_url=DASHSCOPE_BASE_URL, http_client=http
            )

    def model(self, *, thinking: bool) -> Model:
        if isinstance(self._provider, Path):
            return claude_code_model(self._provider, self.spec.name, thinking=thinking)
        if isinstance(self._provider, OpenAICodexProvider):
            return OpenAICodexModel(
                self.spec.name, provider=self._provider, settings=_codex_settings(thinking=thinking)
            )
        if isinstance(self._provider, AnthropicProvider):
            return AnthropicModel(
                self.spec.name,
                provider=self._provider,
                settings=_anthropic_settings(thinking=thinking),
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
    """Generation tokens (↓ wanted) and the writer's calls for the operations section
    (`requests` → Operations.writer_calls). Counts every request that came back, including
    validation retries, rewrites and self-checks; pydantic-ai records a request only after
    the model answered (2.47.0), so an attempt that raised (timeout, usage limit) is not in
    `requests` (LineHealth.drafts counts the drafts attempted)."""

    def __init__(self) -> None:
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage: RunUsage) -> None:
        self.requests += usage.requests
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
