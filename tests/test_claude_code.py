"""The claude-code prose backend (generation.claude_code): Claude on the author's subscription
through `claude -p`. A fake CLI (a shell script) records what it was given and answers, so
every test is offline."""

import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path

import httpx2
import pytest

from jev_research_pipeline.generation import (
    GenerationMeter,
    MissingCredentials,
    ProseAuth,
    Writer,
    parse_model,
    prose_auth,
    write_prose,
)
from jev_research_pipeline.generation.claude_code import ClaudeUsageLimit, parse_result
from jev_research_pipeline.pipeline.costs import generation_price

from .test_prose import CTX, QUESTION

SONNET = parse_model("claude-code:sonnet")


def fake_claude(tmp_path: Path, answer: Mapping[str, object] | str, *, sleep: float = 0) -> Path:
    """A `claude` that saves its argv, stdin and cwd beside itself and prints `answer`."""
    out = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    (tmp_path / "answer").write_text(out, encoding="utf-8")
    script = tmp_path / "claude"
    script.write_text(
        "#!/bin/bash\n"
        f'd="{tmp_path}"\n'
        'printf "%s\\0" "$@" > "$d/argv"\n'
        'cat > "$d/stdin"\n'
        'pwd > "$d/cwd"\n'
        f"sleep {sleep}\n"
        'cat "$d/answer"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def ok(text: str) -> dict[str, object]:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text,
        "usage": {
            "input_tokens": 2,
            "cache_creation_input_tokens": 700,
            "cache_read_input_tokens": 100,
            "output_tokens": 40,
        },
    }


def argv(tmp_path: Path) -> list[str]:
    return (tmp_path / "argv").read_text(encoding="utf-8").split("\0")[:-1]


def flag(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def writer(binary: Path) -> Writer:
    return Writer(ProseAuth(spec=SONNET, claude_bin=binary), httpx2.AsyncClient())


async def write(w: Writer, *, thinking: bool = True):
    return await write_prose(
        w.model(thinking=thinking), CTX, QUESTION, ["claim 1"], feedback=None, meter=METER
    )


METER = GenerationMeter()


def test_the_backend_is_named_like_the_others_and_is_a_subscription():
    assert (SONNET.backend, SONNET.name, str(SONNET)) == (
        "claude-code",
        "sonnet",
        "claude-code:sonnet",
    )
    assert SONNET.subscription
    assert generation_price(SONNET) == (0.0, 0.0)


def test_reaching_it_takes_the_cli_and_says_how_to_fix_its_absence(tmp_path: Path):
    env = {"JRP_PROSE_MODEL": "claude-code:sonnet", "JRP_CLAUDE_BIN": str(tmp_path / "none")}
    with pytest.raises(MissingCredentials, match="JRP_CLAUDE_BIN"):
        prose_auth(env)
    binary = fake_claude(tmp_path, ok("x"))
    assert prose_auth({**env, "JRP_CLAUDE_BIN": str(binary)}) == ProseAuth(
        spec=SONNET, claude_bin=binary
    )


async def test_prose_is_written_by_claude_with_nothing_but_the_prompt(tmp_path: Path):
    meter = GenerationMeter()
    w = writer(fake_claude(tmp_path, ok("本文 [1]。")))
    result = await write_prose(
        w.model(thinking=True), CTX, QUESTION, ["claim 1"], feedback=None, meter=meter
    )
    assert result.prose == "本文 [1]。"
    assert (meter.requests, meter.input_tokens, meter.output_tokens) == (1, 802, 40)
    args = argv(tmp_path)
    assert (args[0], flag(args, "--model")) == ("-p", "sonnet")
    assert flag(args, "--system-prompt").startswith("あなたは、研究ラインの「問い」について")
    # isolation: no settings (hooks, CLAUDE.md, memory), no MCP, no tools, no session file
    assert flag(args, "--setting-sources") == ""
    assert flag(args, "--tools") == ""
    assert {"--strict-mcp-config", "--no-session-persistence"} <= set(args)
    assert flag(args, "--output-format") == "json"
    assert "--effort" not in args  # thinking → the model's own default
    # the prompt (third-party text inside) goes through stdin, never argv
    stdin = (tmp_path / "stdin").read_text(encoding="utf-8")
    assert "<claims>" in stdin and "claim 1" in stdin
    assert not any("claim 1" in a for a in args)
    # a fresh directory: nothing beside the call for the CLI to discover
    cwd = Path((tmp_path / "cwd").read_text(encoding="utf-8").strip()).resolve()
    assert cwd != Path(os.getcwd()).resolve() and "jrp-claude-" in cwd.name


async def test_no_thinking_asks_for_low_effort(tmp_path: Path):
    await write(writer(fake_claude(tmp_path, ok("x"))), thinking=False)
    assert flag(argv(tmp_path), "--effort") == "low"


@pytest.mark.parametrize(
    "answer",
    [
        {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "boom"},
        "not json at all",
        "",
    ],
)
async def test_a_cli_failure_is_a_template_not_a_crash(
    tmp_path: Path, answer: Mapping[str, object] | str
):
    result = await write(writer(fake_claude(tmp_path, answer)))
    assert result.prose is None and result.failure and "ClaudeCodeError" in result.failure


async def test_the_usage_limit_is_named_so_a_burst_can_stop_on_it(tmp_path: Path):
    limit = {
        "subtype": "success",
        "is_error": True,
        "api_error_status": 429,
        "result": "Claude AI usage limit reached",
    }
    result = await write(writer(fake_claude(tmp_path, limit)))
    assert result.prose is None and result.failure and "ClaudeUsageLimit" in result.failure
    with pytest.raises(ClaudeUsageLimit):
        parse_result(
            json.dumps({"is_error": True, "result": "You've hit your usage limit"}).encode(), b"", 1
        )


async def test_a_hung_cli_is_killed_at_the_prose_timeout(tmp_path: Path):
    w = writer(fake_claude(tmp_path, ok("late"), sleep=5))
    result = await write_prose(
        w.model(thinking=True), CTX, QUESTION, ["c"], feedback=None, meter=METER, timeout_s=0.3
    )
    assert result.prose is None and result.failure and "timed out" in result.failure
