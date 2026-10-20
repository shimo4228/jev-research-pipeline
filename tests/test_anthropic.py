"""The `anthropic` prose backend (generation.client): Claude on the Claude API with
ANTHROPIC_API_KEY, the backend a Claude Max plan's monthly API credits pay for."""

import json

import httpx2
import pytest

from jev_research_pipeline.generation import (
    GenerationMeter,
    MissingCredentials,
    ModelSpec,
    ProseAuth,
    Writer,
    parse_model,
    prose_auth,
    write_prose,
)
from jev_research_pipeline.generation.client import PROSE_MAX_TOKENS
from jev_research_pipeline.generation.prose import is_writer_limit
from jev_research_pipeline.pipeline.costs import Budget, generation_price

from .test_prose import CTX, QUESTION

OPUS = parse_model("anthropic:claude-opus-5-5")
MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _message(body: dict[str, object], text: str) -> dict[str, object]:
    return {
        "id": "msg_synthetic",
        "type": "message",
        "role": "assistant",
        "model": body["model"],
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 40},
    }


def _writer(handle: httpx2.MockTransport) -> Writer:
    http = httpx2.AsyncClient(transport=handle)
    return Writer(ProseAuth(spec=OPUS, api_key="sk-ant-test"), http)


async def _write(writer: Writer, *, thinking: bool, meter: GenerationMeter | None = None) -> str:
    result = await write_prose(
        writer.model(thinking=thinking),
        CTX,
        QUESTION,
        ["claim 1"],
        feedback=None,
        meter=meter or GenerationMeter(),
    )
    assert result.prose is not None, result.failure
    return result.prose


# --- which model and what reaching it takes ---------------------------------------------------


def test_the_anthropic_backend_is_named_like_the_others_and_billed_per_token():
    assert OPUS == ModelSpec(backend="anthropic", name="claude-opus-5-5")
    assert not OPUS.subscription
    assert generation_price(OPUS) == (4.0, 20.0)


def test_the_anthropic_backend_needs_its_key_only_when_it_writes():
    env = {"JRP_PROSE_MODEL": str(OPUS)}
    with pytest.raises(MissingCredentials, match="ANTHROPIC_API_KEY"):
        prose_auth(env)
    assert prose_auth({**env, "ANTHROPIC_API_KEY": "k"}) == ProseAuth(spec=OPUS, api_key="k")


def test_the_cost_line_prices_opus_at_api_rates():
    meter = GenerationMeter()
    meter.input_tokens, meter.output_tokens = 1_000_000, 100_000
    assert Budget({}).cost(jev_questions=0, meters={OPUS: meter}) == pytest.approx(6.0)


# --- the model on the wire ---------------------------------------------------------------------


async def test_prose_is_written_through_the_messages_api_with_the_key():
    sent: list[httpx2.Request] = []

    async def handle(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=_message(json.loads(request.content), "本文 [1]。"))

    meter = GenerationMeter()
    prose = await _write(_writer(httpx2.MockTransport(handle)), thinking=True, meter=meter)
    assert prose == "本文 [1]。"
    assert (meter.requests, meter.input_tokens, meter.output_tokens) == (1, 120, 40)
    (request,) = sent
    assert str(request.url).split("?")[0] == MESSAGES_URL  # the beta endpoint: ?beta=true
    assert request.headers["x-api-key"] == "sk-ant-test"
    body = json.loads(request.content)
    assert body["model"] == "claude-opus-5-5"
    assert "あなたは、研究ラインの「問い」について" in json.dumps(
        body["system"], ensure_ascii=False
    )


async def test_the_thinking_policy_maps_to_adaptive_thinking_and_effort():
    """As claude -p sends it (captured 2026-10-20): thinking on = adaptive at medium effort,
    off = low effort (not no thinking), and room for thinking plus the text in max_tokens
    (pydantic-ai would send 4096)."""
    bodies: list[dict[str, object]] = []

    async def handle(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return httpx2.Response(200, json=_message(body, "本文。"))

    writer = _writer(httpx2.MockTransport(handle))
    for thinking in (False, True):
        await _write(writer, thinking=thinking)
    off, on = bodies
    assert off["thinking"] == on["thinking"] == {"type": "adaptive"}
    assert off["output_config"] == {"effort": "low"}
    assert on["output_config"] == {"effort": "medium"}
    assert off["max_tokens"] == on["max_tokens"] == PROSE_MAX_TOKENS
    assert on.get("stream") in (None, False)  # the call's 900 s timeout keeps it unstreamed


@pytest.mark.parametrize(
    ("status", "message", "named"),
    [
        (401, "invalid x-api-key", True),
        (
            400,
            "Your credit balance is too low to access the Anthropic API. "
            "Please go to Plans & Billing to upgrade or purchase credits.",
            True,
        ),
        (400, "You have reached your specified workspace API usage limits.", True),
        (402, "billing problem", True),
        (400, "max_tokens: field required", False),
    ],
    ids=["bad-key", "credits-spent", "spend-limit", "billing", "bad-request"],
)
async def test_a_refused_key_or_spent_credits_are_named_as_auth_failures(
    status: int, message: str, named: bool
):
    """Spent credits repeat on every draft until next month's arrive, like a refused key, so
    the run's notification names them (generation.client.auth_failure)."""

    async def handle(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status,
            json={"type": "error", "error": {"type": "invalid_request_error", "message": message}},
        )

    result = await write_prose(
        _writer(httpx2.MockTransport(handle)).model(thinking=True),
        CTX,
        QUESTION,
        ["claim 1"],
        feedback=None,
        meter=GenerationMeter(),
    )
    assert result.prose is None
    assert result.auth is named
    assert is_writer_limit(result.failure) is named


async def _answer(response: dict[str, object], meter: GenerationMeter | None = None):
    async def handle(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        return httpx2.Response(200, json={**_message(body, ""), **response})

    return await write_prose(
        _writer(httpx2.MockTransport(handle)).model(thinking=True),
        CTX,
        QUESTION,
        ["claim 1"],
        feedback=None,
        meter=meter or GenerationMeter(),
    )


async def test_an_answer_cut_at_max_tokens_is_a_failed_draft_not_prose():
    """Text that stops mid-sentence would otherwise be published (and a cut self-check
    would replace a whole draft): the ladder keeps the previous draft or the template."""
    result = await _answer(
        {"content": [{"type": "text", "text": "本文 [1]。次の研究は"}], "stop_reason": "max_tokens"}
    )
    assert (result.prose, result.failure) == (None, "truncated (max_tokens)")


async def test_an_answer_cut_while_thinking_has_the_same_failure_name():
    """pydantic-ai raises before any text when only thinking came back; the name stays one."""
    thinking = {"type": "thinking", "thinking": "…", "signature": "sig"}
    result = await _answer({"content": [thinking], "stop_reason": "max_tokens"})
    assert (result.prose, result.failure) == (None, "truncated (max_tokens)")


@pytest.mark.parametrize(
    "content",
    [[], [{"type": "text", "text": "本文の途中 [1]、そして"}]],
    ids=["before-output", "mid-answer"],
)
async def test_a_refusal_is_a_one_line_failure_naming_its_category(content: list[object]):
    """Opus 5.5's safety classifiers stop with stop_reason refusal; partial text before the
    stop is not a draft. The category reaches the notification, not the response's JSON."""
    meter = GenerationMeter()
    result = await _answer(
        {
            "content": content,
            "stop_reason": "refusal",
            "stop_details": {"type": "refusal", "category": "cyber", "explanation": "declined"},
            "usage": {"input_tokens": 12000, "output_tokens": 300},
        },
        meter,
    )
    assert (result.prose, result.failure, result.auth) == (None, "refusal (cyber)", False)
    # billed, so metered once: pydantic-ai records the tokens, refused() the request
    assert (meter.requests, meter.input_tokens, meter.output_tokens) == (1, 12000, 300)


async def test_a_rate_limit_is_a_writer_limit_the_bench_stops_on():
    async def handle(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            headers={"retry-after": "0"},
            json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
        )

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))
    writer = Writer(ProseAuth(spec=OPUS, api_key="sk-ant-test"), http, max_retries=0)
    result = await write_prose(
        writer.model(thinking=True),
        CTX,
        QUESTION,
        ["claim 1"],
        feedback=None,
        meter=GenerationMeter(),
    )
    assert result.prose is None
    assert result.failure is not None and "\n" not in result.failure
    assert is_writer_limit(result.failure)
    assert not result.auth
