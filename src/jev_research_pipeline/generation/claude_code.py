"""The `claude-code` prose backend: Claude on the author's Claude subscription, through the
Claude Code CLI's non-interactive mode (`claude -p`), wrapped as a pydantic-ai FunctionModel
(design "Prose model", author decision 2026-10-01).

Why the CLI and not an API key: the subscription is reachable only through Claude Code's own
login (keychain OAuth). `--bare` would be the cleanest isolation but reads ANTHROPIC_API_KEY
only, never the OAuth login (claude 2.1.285 --help), so the call isolates itself instead:

    --setting-sources ""     no user / project / local settings: no hooks, no CLAUDE.md,
                             no memory (measured 2026-10-01: 756 input tokens in all)
    --strict-mcp-config      no MCP servers
    --tools ""               no tools: the prompt carries third-party text (claims, abstracts),
                             and a model with no tools cannot act on an instruction inside it
    --system-prompt          the prose instructions replace Claude Code's own system prompt
    --no-session-persistence nothing written to ~/.claude/projects
    cwd = a fresh temp dir   nothing to discover beside the call

The prompt goes through stdin (no argv length limit, not visible in `ps`). The binary is
JRP_CLAUDE_BIN, else `claude` on PATH, else ~/.local/bin/claude (launchd's PATH is minimal).
"""

import asyncio
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

CLAUDE_BIN_ENV: Final = "JRP_CLAUDE_BIN"
CLAUDE_BIN_FALLBACK: Final = Path("~/.local/bin/claude")
DEFAULT_TIMEOUT_S: Final = 900.0


class ClaudeCodeError(UnexpectedModelBehavior):
    """The CLI ran and failed. An AgentRunError, so write_prose turns it into a template day."""


class ClaudeUsageLimit(ClaudeCodeError):
    """The subscription's usage or rate limit. A policy signal, not a transient error: the
    prose bench stops its burst on it instead of retrying (harness rule debugging.md)."""


def claude_bin(env: Mapping[str, str]) -> Path | None:
    """The CLI to call, or None when there is none."""
    if raw := env.get(CLAUDE_BIN_ENV):
        path = Path(raw).expanduser()
        return path if path.is_file() else None
    if found := shutil.which("claude"):
        return Path(found)
    fallback = CLAUDE_BIN_FALLBACK.expanduser()
    return fallback if fallback.is_file() else None


def claude_argv(binary: Path, model: str, instructions: str, *, effort: str | None) -> list[str]:
    argv = [
        str(binary),
        "-p",
        "--model",
        model,
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--tools",
        "",
        "--system-prompt",
        instructions,
        "--no-session-persistence",
        "--output-format",
        "json",
    ]
    if effort:
        argv += ["--effort", effort]
    return argv


def prompt_text(messages: Sequence[ModelMessage]) -> str:
    """The conversation so far as one prompt. The prose site sends one user prompt; a
    validation retry adds a retry part and the previous answer, kept in order."""
    parts: list[str] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    parts.append(part.content)
                elif isinstance(part, RetryPromptPart):
                    parts.append(part.model_response())
        else:
            text = "".join(p.content for p in message.parts if isinstance(p, TextPart))
            if text:
                parts.append(f"<previous_answer>\n{text}\n</previous_answer>")
    return "\n\n".join(parts)


_LIMIT_MARKERS: Final = ("usage limit", "rate limit", "rate_limit", "overloaded")


class _CliUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0


class _CliResult(BaseModel):
    """The fields of `claude -p --output-format json` this backend reads."""

    model_config = ConfigDict(extra="ignore")
    result: str = ""
    is_error: bool = False
    subtype: str = ""
    api_error_status: int | None = None
    usage: _CliUsage = _CliUsage()


def parse_result(stdout: bytes, stderr: bytes, returncode: int) -> tuple[str, RequestUsage]:
    """The CLI's `--output-format json` result → (text, usage), or the error it reports."""
    try:
        data = _CliResult.model_validate(json.loads(stdout))
    except (ValueError, ValidationError):
        detail = (stderr or stdout).decode(errors="replace").strip()[:300]
        raise ClaudeCodeError(f"claude exited {returncode}: {detail or 'no output'}") from None
    if data.is_error or data.subtype != "success" or returncode != 0:
        message = f"claude error (status {data.api_error_status}): {data.result[:300]}"
        if data.api_error_status == 429 or any(m in data.result.lower() for m in _LIMIT_MARKERS):
            raise ClaudeUsageLimit(message)
        raise ClaudeCodeError(message)
    u = data.usage
    return data.result, RequestUsage(
        # the prompt cache splits the input three ways; the meter wants all of it
        input_tokens=u.input_tokens + u.cache_creation_input_tokens + u.cache_read_input_tokens,
        output_tokens=u.output_tokens,
    )


async def run_claude(argv: list[str], prompt: str, *, timeout_s: float) -> tuple[str, RequestUsage]:
    with tempfile.TemporaryDirectory(prefix="jrp-claude-") as cwd:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=os.environ.copy(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(prompt.encode()), timeout=timeout_s
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise ClaudeCodeError(f"claude timed out after {timeout_s:.0f} s") from None
    return parse_result(stdout, stderr, proc.returncode or 0)


def claude_code_model(binary: Path, model: str, *, thinking: bool) -> FunctionModel:
    """`thinking=False` asks for low effort; otherwise the model's default effort."""
    effort = None if thinking else "low"

    async def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        settings: dict[str, object] = dict(info.model_settings or {})
        timeout = settings.get("timeout")
        text, usage = await run_claude(
            claude_argv(binary, model, info.instructions or "", effort=effort),
            prompt_text(messages),
            timeout_s=float(timeout) if isinstance(timeout, int | float) else DEFAULT_TIMEOUT_S,
        )
        return ModelResponse(parts=[TextPart(text)], usage=usage, model_name=model)

    return FunctionModel(call, model_name=f"claude-code:{model}")
