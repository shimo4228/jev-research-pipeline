"""`jrp doctor` (pipeline.doctor): what a run needs, checked without a run — env, config,
questions, the TypeSafe key and the prose writer's login — one line each, non-zero exit on
any failure. Nothing here touches the network, the store or the vault; the Claude Code CLI
is a fake runner."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from jev_research_pipeline.pipeline.doctor import Check, doctor

from .fakes import codex_login
from .test_config import CONFIG, GRAPH

FAKE_VALUE = "replay-value"
"""A stand-in for every key: the test asserts it never reaches the printed lines."""

QUESTION = (
    "<!-- jrp:questions:{slug} -->\n\n"
    "## 記憶は何で決まるのか\n"
    "- slug: memory\n"
    "- version: 1\n"
    "- status: open\n"
    "- arxiv: agent memory\n"
)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    repo = tmp_path / "agent-knowledge-cycle"
    repo.mkdir()
    (repo / "graph.jsonld").write_text(json.dumps(GRAPH), encoding="utf-8")
    (tmp_path / "edge-frontier").mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        CONFIG.format(repo_akc=repo, repo_edge=tmp_path / "edge-frontier"), encoding="utf-8"
    )
    questions = tmp_path / "questions"
    questions.mkdir()
    for slug in ("akc", "jev"):
        (questions / f"{slug}.md").write_text(QUESTION.format(slug=slug), encoding="utf-8")
    return {
        # a vault that does not exist: the doctor only asks whether it is set (under
        # launchd python must not touch the iCloud vault; the wrapper passes the stage)
        "JRP_VAULT_DIR": str(tmp_path / "no-vault"),
        "JRP_STORE_DIR": str(tmp_path / "store"),
        "JRP_DAILY_RESEARCH_CONFIG": str(cfg),
        "JRP_QUESTIONS_DIR": str(questions),
        "TYPESAFE_API_KEY": FAKE_VALUE,
        "JRP_CODEX_AUTH": str(codex_login(tmp_path / "codex-auth.json")),
    }


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {c.name: c for c in checks}


def test_a_ready_setup_passes_every_check(env: dict[str, str], tmp_path: Path):
    checks = doctor(env)
    assert [c.name for c in checks] == ["env", "config", "questions", "typesafe", "writer"]
    assert all(c.ok for c in checks), [c.line() for c in checks]
    c = by_name(checks)
    assert "akc, edge" in c["config"].detail and "daily jev" in c["config"].detail
    assert "open questions akc 1, jev 1" in c["questions"].detail
    assert "edge: no open question" in c["questions"].detail
    assert "openai-codex:" in c["writer"].detail and "not refreshed" in c["writer"].detail
    assert not (tmp_path / "store").exists()  # nothing written
    assert FAKE_VALUE not in "\n".join(ch.line() for ch in checks)  # keys never printed


def test_each_line_says_ok_or_fail():
    assert Check("env", True, "x").line() == "ok   env: x"
    assert Check("env", False, "y").line() == "FAIL env: y"


@pytest.mark.parametrize("missing", ["JRP_VAULT_DIR", "JRP_STORE_DIR"])
def test_a_missing_env_var_fails_the_env_check(env: dict[str, str], missing: str):
    del env[missing]
    check = by_name(doctor(env))["env"]
    assert not check.ok and missing in check.detail


def test_a_missing_typesafe_key_fails(env: dict[str, str]):
    del env["TYPESAFE_API_KEY"]
    assert not by_name(doctor(env))["typesafe"].ok


def test_an_unreadable_config_fails_config_and_questions(env: dict[str, str], tmp_path: Path):
    env["JRP_DAILY_RESEARCH_CONFIG"] = str(tmp_path / "missing.toml")
    c = by_name(doctor(env))
    assert not c["config"].ok and "missing.toml" in c["config"].detail
    assert not c["questions"].ok and "config" in c["questions"].detail


def test_a_missing_questions_dir_fails(env: dict[str, str], tmp_path: Path):
    env["JRP_QUESTIONS_DIR"] = str(tmp_path / "nowhere")
    assert not by_name(doctor(env))["questions"].ok


@pytest.mark.parametrize("content", [None, "{not json"])
def test_a_missing_or_unreadable_codex_login_fails(
    env: dict[str, str], tmp_path: Path, content: str | None
):
    path = tmp_path / "codex-auth.json"
    path.unlink()
    if content is not None:
        path.write_text(content, encoding="utf-8")
    check = by_name(doctor(env))["writer"]
    assert not check.ok and "jrp codex login" in check.detail


def test_dashscope_needs_its_key(env: dict[str, str]):
    env["JRP_PROSE_MODEL"] = "dashscope:qwen3.7-max"
    assert not by_name(doctor(env))["writer"].ok
    env["DASHSCOPE_API_KEY"] = "k"
    assert by_name(doctor(env))["writer"].ok


def test_an_unknown_prose_model_fails(env: dict[str, str]):
    env["JRP_PROSE_MODEL"] = "gpt-6-luna"
    check = by_name(doctor(env))["writer"]
    assert not check.ok and "JRP_PROSE_MODEL" in check.detail


class FakeClaude:
    """`claude auth status --json`: records the argv and env it was run with."""

    def __init__(self, status: int, out: str) -> None:
        self.status, self.out = status, out
        self.calls: list[tuple[list[str], Mapping[str, str]]] = []

    def __call__(self, argv: list[str], env: Mapping[str, str]) -> tuple[int, str]:
        self.calls.append((argv, env))
        return self.status, self.out


def _claude_env(env: dict[str, str], tmp_path: Path) -> dict[str, str]:
    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    return env | {
        "JRP_PROSE_MODEL": "claude-code:sonnet",
        "JRP_CLAUDE_BIN": str(binary),
        "ANTHROPIC_API_KEY": FAKE_VALUE,
    }


def test_claude_code_is_ready_when_the_cli_reports_logged_in(env: dict[str, str], tmp_path: Path):
    env = _claude_env(env, tmp_path)
    status = json.dumps(
        {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max", "email": "a@b"}
    )
    fake = FakeClaude(0, status)
    check = by_name(doctor(env, auth_status=fake))["writer"]
    assert check.ok and "claude.ai" in check.detail and "max" in check.detail
    assert "a@b" not in check.detail  # the account's identity stays out of the log
    ((argv, child),) = fake.calls
    assert argv == [str(tmp_path / "claude"), "auth", "status", "--json"]
    # the same scrub as a prose call: no API key to switch it off the subscription
    assert "ANTHROPIC_API_KEY" not in child and "TYPESAFE_API_KEY" not in child


@pytest.mark.parametrize(
    ("status", "out"),
    [(1, json.dumps({"loggedIn": False})), (0, "not json"), (0, json.dumps({"loggedIn": "yes"}))],
)
def test_claude_code_not_logged_in_fails(
    env: dict[str, str], tmp_path: Path, status: int, out: str
):
    check = by_name(doctor(_claude_env(env, tmp_path), auth_status=FakeClaude(status, out)))[
        "writer"
    ]
    assert not check.ok and "not logged in" in check.detail


def test_a_claude_cli_that_does_not_answer_fails(env: dict[str, str], tmp_path: Path):
    def hangs(argv: list[str], env: Mapping[str, str]) -> tuple[int, str]:
        raise TimeoutError

    check = by_name(doctor(_claude_env(env, tmp_path), auth_status=hangs))["writer"]
    assert not check.ok and "keychain" in check.detail


def test_no_claude_cli_fails(env: dict[str, str], tmp_path: Path):
    env = _claude_env(env, tmp_path) | {"JRP_CLAUDE_BIN": str(tmp_path / "nope")}
    check = by_name(doctor(env, auth_status=FakeClaude(0, "{}")))["writer"]
    assert not check.ok and "Claude Code CLI" in check.detail


def test_the_cli_prints_one_line_per_check_and_exits_non_zero_on_a_failure(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from jev_research_pipeline import cli

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("JRP_PROSE_MODEL", raising=False)
    assert cli.main(["doctor"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 5
    monkeypatch.delenv("TYPESAFE_API_KEY")
    assert cli.main(["doctor"]) == 1
    assert "FAIL typesafe" in capsys.readouterr().out
