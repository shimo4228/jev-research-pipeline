"""The prose model's backends (generation.client) and the default one, GPT-5.6 Sol on the
ChatGPT/Codex subscription with the pipeline's own login (generation.codex)."""

import base64
import json
import stat
from pathlib import Path

import httpx2
import pytest
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials

from jev_research_pipeline.generation import (
    GenerationMeter,
    MissingCredentials,
    ModelSpec,
    ModelSpecError,
    ProseAuth,
    Writer,
    parse_model,
    prose_auth,
    prose_model_spec,
    write_prose,
)
from jev_research_pipeline.generation.codex import (
    CodexAuthFile,
    CodexLoginError,
    codex_auth_path,
    read_credentials,
)
from jev_research_pipeline.pipeline.costs import Budget, generation_price
from jev_research_pipeline.pipeline.runner import MissingKey, keys

from .conftest import ClientFactory
from .fakes import codex_login, fake_codex
from .test_prose import CTX, QUESTION

SOL = parse_model("openai-codex:gpt-5.6-sol")
CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"


# --- which model -----------------------------------------------------------------------------


def test_the_default_prose_model_is_gpt56_sol_on_the_subscription():
    assert prose_model_spec({}) == SOL
    assert str(SOL) == "openai-codex:gpt-5.6-sol"
    assert SOL.subscription


def test_the_prose_model_is_named_by_env():
    spec = prose_model_spec({"JRP_PROSE_MODEL": "dashscope:qwen3.7-max"})
    assert spec == ModelSpec(backend="dashscope", name="qwen3.7-max")
    assert not spec.subscription


@pytest.mark.parametrize("raw", ["qwen3.7-max", "openai:gpt-5.6-sol", "openai-codex:", ":x"])
def test_a_model_that_names_no_known_backend_is_an_error_not_a_fallback(raw: str):
    with pytest.raises(ModelSpecError, match="<backend>:<model>"):
        parse_model(raw)


# --- what reaching it takes ------------------------------------------------------------------


def test_the_codex_backend_needs_the_pipelines_own_login(tmp_path: Path):
    env = {"JRP_CODEX_AUTH": str(tmp_path / "codex-auth.json")}
    with pytest.raises(MissingCredentials, match="jrp codex login"):
        prose_auth(env)
    codex_login(tmp_path / "codex-auth.json")
    assert prose_auth(env) == ProseAuth(spec=SOL, codex_auth=tmp_path / "codex-auth.json")


def test_the_login_lives_beside_the_run_env_by_default():
    assert codex_auth_path({}) == Path("~/.config/jrp/codex-auth.json").expanduser()


def test_dashscope_needs_its_key_only_when_it_writes():
    env = {"JRP_PROSE_MODEL": "dashscope:qwen3.7-max"}
    with pytest.raises(MissingCredentials, match="DASHSCOPE_API_KEY"):
        prose_auth(env)
    assert prose_auth({**env, "DASHSCOPE_API_KEY": "k"}).api_key == "k"


def test_a_run_stops_before_the_store_without_a_way_to_the_prose_model(tmp_path: Path):
    env = {"TYPESAFE_API_KEY": "t", "JRP_CODEX_AUTH": str(tmp_path / "none.json")}
    with pytest.raises(MissingKey, match="jrp codex login"):
        keys(env)
    with pytest.raises(MissingKey, match="JRP_PROSE_MODEL"):
        keys({**env, "JRP_PROSE_MODEL": "qwen3.7-max"})
    codex_login(tmp_path / "none.json")
    api, prose = keys(env)  # no DASHSCOPE_API_KEY needed for the default
    assert (api.typesafe, prose.spec) == ("t", SOL)


# --- the stored login ------------------------------------------------------------------------


def test_the_login_file_is_the_owners_alone_and_reads_back(tmp_path: Path):
    path = codex_login(tmp_path / "jrp" / "codex-auth.json")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_credentials(path) == OpenAICodexCredentials(
        access_token="replay", refresh_token="r1", account_id="acct"
    )


@pytest.mark.parametrize("content", [None, "{}", "not json"], ids=["missing", "empty", "garbled"])
def test_a_missing_or_unreadable_login_says_how_to_fix_it(tmp_path: Path, content: str | None):
    path = tmp_path / "codex-auth.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(CodexLoginError, match="jrp codex login"):
        read_credentials(path)


async def test_a_refreshed_login_is_written_back(tmp_path: Path):
    path = codex_login(tmp_path / "codex-auth.json")
    rotated = OpenAICodexCredentials(access_token="a2", refresh_token="r2", account_id="acct")
    await CodexAuthFile(path).save(rotated)
    assert await CodexAuthFile(path).load() == rotated
    assert not path.with_name("codex-auth.json.tmp").exists()


# --- the model on the wire -------------------------------------------------------------------


def _sol(http: httpx2.AsyncClient, login: Path) -> Writer:
    return Writer(ProseAuth(spec=SOL, codex_auth=login), http)


async def test_prose_is_written_by_gpt56_sol_on_the_codex_backend(
    cassette: ClientFactory, cassette_path: Path, tmp_path: Path
):
    meter = GenerationMeter()
    writer = _sol(cassette(fake_codex("本文 [1]。")), codex_login(tmp_path / "a.json"))
    result = await write_prose(
        writer.model(thinking=True), CTX, QUESTION, ["claim 1"], feedback=None, meter=meter
    )
    assert result.prose == "本文 [1]。"
    assert (meter.requests, meter.input_tokens, meter.output_tokens) == (1, 120, 40)
    ((key, entry),) = json.loads(cassette_path.read_text(encoding="utf-8")).items()
    assert key.startswith(f"POST {CODEX_URL} ")
    sent = json.loads(entry["request_body"])
    # The backend's dialect: streamed, not stored, and a prompt-cache key that stays put
    # from call to call (a per-call one would never hit, nor replay from a cassette).
    assert (sent["model"], sent["stream"], sent["store"]) == ("gpt-5.6-sol", True, False)
    assert sent["prompt_cache_key"] == "jrp-prose"
    assert sent["instructions"].startswith("あなたは、研究ラインの「問い」について")


async def test_the_thinking_policy_maps_to_gpt56_sols_reasoning_effort(tmp_path: Path):
    effort: list[object] = []

    async def record(request: httpx2.Request) -> httpx2.Response:
        effort.append(json.loads(request.content).get("reasoning", {}).get("effort"))
        return await fake_codex("本文。", "本文。")(request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    writer = _sol(http, codex_login(tmp_path / "a.json"))
    for thinking in (False, True):
        await write_prose(
            writer.model(thinking=thinking),
            CTX,
            QUESTION,
            ["c"],
            feedback=None,
            meter=GenerationMeter(),
        )
    assert effort[0] == "none"  # JRP_PROSE_THINKING=off
    assert effort[1] != "none"  # always / rewrite: the model's own default (medium)


async def test_codex_credentials_go_to_the_codex_host_only(tmp_path: Path):
    seen: dict[str, dict[str, str]] = {}

    async def record(request: httpx2.Request) -> httpx2.Response:
        seen[str(request.url.host)] = dict(request.headers)
        if request.url.host == "chatgpt.com":
            return await fake_codex("本文。")(request)
        return httpx2.Response(200, json={})

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(record))
    writer = _sol(http, codex_login(tmp_path / "a.json"))
    await write_prose(
        writer.model(thinking=True), CTX, QUESTION, ["c"], feedback=None, meter=GenerationMeter()
    )
    await http.get("https://api.typesafe.ai/v1/systemone")  # the run's shared client
    assert seen["chatgpt.com"]["authorization"] == "Bearer replay"
    assert seen["chatgpt.com"]["chatgpt-account-id"] == "acct"
    assert "chatgpt-account-id" not in seen["api.typesafe.ai"]
    assert "authorization" not in seen["api.typesafe.ai"]


def _expired_jwt() -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1}).encode()).decode().rstrip("=")
    return f"e30.{payload}.sig"


async def test_an_expired_login_is_refreshed_once_and_saved_for_the_next_run(tmp_path: Path):
    """Refresh tokens are single-use: the rotated set must reach the file, or the next
    scheduled run would start from a spent one."""
    login = codex_login(tmp_path / "a.json", access_token=_expired_jwt())
    bearer: list[str] = []

    async def upstream(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "auth.openai.com":
            return httpx2.Response(200, json={"access_token": "a2", "refresh_token": "r2"})
        bearer.append(request.headers["authorization"])
        return await fake_codex("本文。")(request)

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
    writer = _sol(http, login)
    for _ in range(2):  # two sections of one run: the second reuses the refreshed set
        await write_prose(
            writer.model(thinking=True),
            CTX,
            QUESTION,
            ["c"],
            feedback=None,
            meter=GenerationMeter(),
        )
    assert bearer == ["Bearer a2", "Bearer a2"]
    assert read_credentials(login) == OpenAICodexCredentials(
        access_token="a2", refresh_token="r2", account_id="acct"
    )


async def test_a_codex_failure_is_a_template_not_a_crash(cassette: ClientFactory, tmp_path: Path):
    writer = _sol(cassette(fake_codex(None, status=400)), codex_login(tmp_path / "a.json"))
    result = await write_prose(
        writer.model(thinking=True), CTX, QUESTION, ["c"], feedback=None, meter=GenerationMeter()
    )
    assert result.prose is None and result.failure is not None


def test_one_writer_per_client(tmp_path: Path):
    """A second Codex provider on the same client would refresh the same single-use token."""
    http = httpx2.AsyncClient()
    login = codex_login(tmp_path / "a.json")
    _sol(http, login)
    with pytest.raises(Exception, match="already has auth"):
        _sol(http, login)


# --- what it costs ---------------------------------------------------------------------------


def test_subscription_tokens_are_counted_but_cost_nothing():
    meter = GenerationMeter()
    meter.input_tokens, meter.output_tokens = 1_000_000, 1_000_000
    budget = Budget({})
    assert budget.cost(jev_questions=0, meters={SOL: meter}) == 0.0
    qwen = parse_model("dashscope:qwen3.7-max")
    assert budget.cost(jev_questions=0, meters={qwen: meter}) == pytest.approx(10.0)
    assert generation_price(parse_model("dashscope:qwen3.8-max")) is None  # no price on record
