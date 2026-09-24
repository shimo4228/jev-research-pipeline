"""The pipeline's own login to the ChatGPT/Codex subscription (design "Prose model").

Not the Codex CLI's ~/.codex/auth.json: OpenAI's refresh tokens are single-use, and
pydantic-ai reads that file read-only and keeps a refreshed set in memory only. The first
refresh inside a run would spend the token the CLI has stored, and both the CLI and the
next scheduled run would be left holding a dead grant. So `jrp codex login` runs the same
browser login as the CLI (the public Codex client; its redirect is pinned to
localhost:1455) once, keeps the result in a file of the pipeline's own, and every refresh
is written back to that file (pydantic-ai docs, "Persisting credentials").
"""

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Final, TypedDict, override

from pydantic import TypeAdapter, ValidationError
from pydantic_ai.providers.openai_codex import (
    OpenAICodexCredentials,
    OpenAICodexCredentialSource,
    OpenAICodexOAuthFlow,
)

CODEX_AUTH_ENV: Final = "JRP_CODEX_AUTH"
DEFAULT_CODEX_AUTH: Final = Path("~/.config/jrp/codex-auth.json")
"""Beside ~/.config/jrp/env, the run's other secrets; never in the repo or ~/.codex."""


class CodexLoginError(RuntimeError):
    """The stored login is missing or unreadable: `jrp codex login` fixes both."""


class _Stored(TypedDict):
    access_token: str
    refresh_token: str
    account_id: str


_STORED: Final = TypeAdapter(_Stored)


def codex_auth_path(env: Mapping[str, str]) -> Path:
    raw = env.get(CODEX_AUTH_ENV)
    return (Path(raw) if raw else DEFAULT_CODEX_AUTH).expanduser()


def read_credentials(path: Path) -> OpenAICodexCredentials:
    try:
        stored = _STORED.validate_json(path.read_bytes())
    except FileNotFoundError:
        raise CodexLoginError(f"no Codex login at {path}: run `uv run jrp codex login`") from None
    except ValidationError as e:
        raise CodexLoginError(
            f"unreadable Codex login at {path} ({e.error_count()} errors): "
            "run `uv run jrp codex login`"
        ) from None
    return OpenAICodexCredentials(**stored)


def write_credentials(path: Path, credentials: OpenAICodexCredentials) -> None:
    """Whole-file replace, readable by the owner only: the file holds a refresh token that
    grants the subscription. A crash mid-write leaves the previous login in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(asdict(credentials), f)
    tmp.replace(path)


class CodexAuthFile(OpenAICodexCredentialSource):
    """The provider loads the login from here on first use and saves every refresh back,
    after re-reading it first (another process may have refreshed already)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @override
    async def load(self) -> OpenAICodexCredentials:
        return read_credentials(self.path)

    @override
    async def save(self, credentials: OpenAICodexCredentials) -> None:
        write_credentials(self.path, credentials)


async def login(path: Path, *, show: Callable[[str], object]) -> OpenAICodexCredentials:
    """Browser login: `show` gets the authorization URL (open it, print it), then this waits
    for the redirect on localhost:1455 and stores what it exchanges the code for."""
    flow = OpenAICodexOAuthFlow()
    show(flow.authorization_url())
    credentials = await flow.exchange_code_from_callback()
    write_credentials(path, credentials)
    return credentials
