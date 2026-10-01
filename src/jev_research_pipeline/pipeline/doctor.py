"""`jrp doctor`: what a run needs, checked without running one — one line per check, a
non-zero exit when any fails.

    env        JRP_VAULT_DIR and JRP_STORE_DIR are set
    config     config.toml reads and every line resolves (its graph.jsonld vocabulary)
    questions  the question files parse; lines without an open question are named
    typesafe   TYPESAFE_API_KEY is set
    writer     the JRP_PROSE_MODEL writer is reachable: the Codex login file reads (never
               refreshed: a refresh spends the single-use token the next run needs),
               DashScope's key is set, or the Claude Code CLI is found and
               `claude auth status` says loggedIn

Why it exists: the writer's login is the dependency that fails silently (a rejected Codex
grant turns every section into a template; Claude Code's login lives in the macOS keychain,
which a launchd job may not be allowed to read). scripts/launchd-jrp.sh runs this before
every scheduled run and logs it, so the 05:00 log answers "could launchd reach the writer"
before the run spends anything; a failure is notified and the run still goes ahead.

Nothing is written, and the vault is never opened — only whether it is set: under launchd
python must not touch the iCloud vault (the wrapper points JRP_VAULT_DIR at its stage), and
a stat there can wait on the same invisible consent prompt as an open(). No network either:
`claude auth status` reads the CLI's local login.
"""

import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from jev_research_pipeline.generation import ModelSpec, ModelSpecError, prose_model_spec
from jev_research_pipeline.generation.claude_code import CLAUDE_BIN_ENV, child_env, claude_bin
from jev_research_pipeline.generation.client import DASHSCOPE_KEY_ENV
from jev_research_pipeline.generation.codex import (
    CodexLoginError,
    codex_auth_path,
    read_credentials,
)
from jev_research_pipeline.questions import parse_questions, questions_dir, questions_path
from jev_research_pipeline.report import VAULT_ENV

from .config import config_path, env_tracks, line_context, rotation_config
from .runner import KEY_ENVS, STORE_ENV, lines_per_day

AUTH_STATUS_TIMEOUT_S: Final = 30.0
"""`claude auth status` answers in about a second; one waiting on a keychain prompt that
nobody can see under launchd never does."""

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

type AuthStatus = Callable[[list[str], Mapping[str, str]], tuple[int, str]]
"""Runs `claude auth status --json` → (exit status, stdout); injectable for tests."""


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        return f"{'ok  ' if self.ok else 'FAIL'} {self.name}: {self.detail}"


def _auth_status(argv: list[str], env: Mapping[str, str]) -> tuple[int, str]:
    try:
        done = subprocess.run(
            argv,
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=AUTH_STATUS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError from None
    return done.returncode, done.stdout


class _ClaudeStatus(BaseModel):
    """The fields of `claude auth status --json` read here (claude 2.1.285); the account's
    email and organisation are left out so they never reach the log."""

    model_config = ConfigDict(extra="ignore")
    loggedIn: StrictBool = False  # the CLI's own key names
    authMethod: str = ""
    subscriptionType: str = ""


def _env(env: Mapping[str, str]) -> Check:
    needed = (VAULT_ENV, STORE_ENV)
    missing = [k for k in needed if not env.get(k)]
    if missing:
        return Check("env", False, f"not set: {', '.join(missing)}")
    return Check("env", True, f"{', '.join(needed)} set")


def _config(env: Mapping[str, str]) -> tuple[Check, dict[str, str]]:
    """The check, and the slug → line @id of every line a run can pick."""
    path = config_path(env)
    try:
        tracks = env_tracks(env)
        per_day = lines_per_day(path)
        ids = {t.slug: line_context(t).line.id for t in tracks}
    except Exception as e:  # any way it fails to load is the finding
        return Check("config", False, f"{path}: {type(e).__name__}: {e}"), {}
    rotation = rotation_config(tracks, per_tick=per_day).order
    daily = [t.slug for t in tracks if t.daily]
    detail = f"{path}: rotation {', '.join(rotation) or 'none'} ({per_day} per day)"
    if daily:
        detail += f"; daily {', '.join(daily)}"
    runnable = {slug: ids[slug] for slug in (*rotation, *daily)}
    if not runnable:
        return Check("config", False, f"{detail}: no line to run"), {}
    return Check("config", True, detail), runnable


def _questions(env: Mapping[str, str], lines: Mapping[str, str] | None) -> Check:
    root = questions_dir(env)
    if lines is None:
        return Check("questions", False, "not checked: config.toml gave no line")
    if not root.is_dir():
        return Check("questions", False, f"{root} is not a directory")
    counts: list[str] = []
    empty: list[str] = []
    for slug, line in lines.items():
        path = questions_path(env, slug)
        try:
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            # opened_at is a placeholder: only the count of open questions is read here
            parsed = parse_questions(text, line=line, opened_at=_EPOCH)
        except (OSError, UnicodeDecodeError) as e:
            return Check("questions", False, f"{path}: {type(e).__name__}: {e}")
        n = sum(1 for q in parsed if q.status == "open")
        if n:
            counts.append(f"{slug} {n}")
        else:
            empty.append(slug)
    detail = f"{root}: open questions {', '.join(counts) or 'none'}"
    if empty:
        # by design a skip the run reports, not a failure: the questions are the author's
        detail += f"; {', '.join(f'{s}: no open question' for s in empty)}"
    return Check("questions", True, detail)


def _typesafe(env: Mapping[str, str]) -> Check:
    missing = [k for k in KEY_ENVS if not env.get(k)]
    if missing:
        return Check("typesafe", False, f"not set: {', '.join(missing)}")
    return Check("typesafe", True, f"{', '.join(KEY_ENVS)} set")


def _writer(env: Mapping[str, str], auth_status: AuthStatus) -> Check:
    try:
        spec = prose_model_spec(env)
    except ModelSpecError as e:
        return Check("writer", False, str(e))
    match spec.backend:
        case "dashscope":
            ok = bool(env.get(DASHSCOPE_KEY_ENV))
            return Check("writer", ok, f"{spec}: {DASHSCOPE_KEY_ENV} {'set' if ok else 'not set'}")
        case "openai-codex":
            return _codex(spec, env)
        case "claude-code":
            return _claude_code(spec, env, auth_status)


def _codex(spec: ModelSpec, env: Mapping[str, str]) -> Check:
    path = codex_auth_path(env)
    try:
        read_credentials(path)  # parsed only: a refresh would spend the run's single-use token
    except (CodexLoginError, OSError) as e:
        return Check("writer", False, f"{spec}: {e}")
    return Check("writer", True, f"{spec}: login at {path} reads (not refreshed)")


def _claude_code(spec: ModelSpec, env: Mapping[str, str], auth_status: AuthStatus) -> Check:
    binary = claude_bin(env)
    if binary is None:
        return Check(
            "writer", False, f"{spec}: no Claude Code CLI (install it, or set {CLAUDE_BIN_ENV})"
        )
    try:
        # the same scrub as a prose call: with ANTHROPIC_API_KEY set the CLI would report
        # the API key's login, not the subscription's the run will use
        status, out = auth_status([str(binary), "auth", "status", "--json"], child_env(env))
    except (TimeoutError, OSError) as e:
        why = "no answer" if isinstance(e, TimeoutError) else f"{type(e).__name__}: {e}"
        return Check(
            "writer",
            False,
            f"{spec}: `claude auth status` failed ({why}; under launchd, a keychain prompt?)",
        )
    try:
        parsed = _ClaudeStatus.model_validate(json.loads(out))
    except (ValueError, ValidationError):
        parsed = _ClaudeStatus()
    if status != 0 or not parsed.loggedIn:
        return Check(
            "writer", False, f"{spec}: {binary} not logged in: run `claude` and /login once"
        )
    how = ", ".join(filter(None, [parsed.authMethod, parsed.subscriptionType]))
    return Check("writer", True, f"{spec}: {binary} logged in ({how or 'method unknown'})")


def doctor(env: Mapping[str, str], *, auth_status: AuthStatus = _auth_status) -> list[Check]:
    config, lines = _config(env)
    return [
        _env(env),
        config,
        _questions(env, lines if config.ok else None),
        _typesafe(env),
        _writer(env, auth_status),
    ]
