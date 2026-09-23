"""Several sources against one question in one Jev request (judge's ask 2026-09-23: fewer
round trips), without giving up what one request per source guaranteed: a Judgment per
source with its own distributions, found again by a re-run, and a bad source that sinks
only itself."""

import json
from pathlib import Path

import httpx2
import pytest

from jev_research_pipeline.jev import JevClient, JevFailure, Judged, question_screening
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.jev.core import (
    BATCH_MAX_ITEMS,
    BATCH_STATE_TOKENS,
    JevState,
    batches,
    output_of,
)
from jev_research_pipeline.model import SourceItem
from jev_research_pipeline.pipeline.run import StoredJev
from jev_research_pipeline.store import input_sha256

from . import builders as b
from .conftest import ClientFactory, Handler
from .fakes import fake_jev

CTX = LineContext(line=b.line(), vocabulary=("agent memory",))
ASK = question_screening.ASK
POISON = "POISON"


def _source(n: int, text: str = "") -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url=f"https://arxiv.org/abs/2609.0{n:04d}",
        title=f"Paper {n}",
        text=text or f"An abstract about agent memory number {n}, long enough to screen. " * 4,
        fetched_at=b.T0,
    )


def _items(sources: list[SourceItem]) -> list[tuple[tuple[str, ...], JevState]]:
    return question_screening.items(CTX, sources, b.question(), ["既知の claim"])


class Counting:
    """Wraps a fake upstream and keeps each request's question names. Used through
    `_live()`, not a cassette: on replay a cassette never reaches the upstream, and these
    tests are about how many requests the client makes, not about their wire format."""

    def __init__(self, inner: Handler) -> None:
        self.inner = inner
        self.requests: list[list[str]] = []

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(list(json.loads(request.content)["questions"]))
        return await self.inner(request)


def _live(handler: Handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


async def test_three_sources_go_in_one_request_and_come_back_as_three_judgments(
    cassette: ClientFactory, cassette_path: Path
):
    upstream = fake_jev({"on_topic": 0.97, "s1.on_topic": 0.1})
    jev = JevClient(cassette(upstream), api_key="replay")
    sources = [_source(i) for i in range(3)]
    items = _items(sources)

    results = await jev.judge_batch(ASK, items, subject="source", now=b.T0)

    recorded = json.loads(cassette_path.read_text(encoding="utf-8"))
    assert len(recorded) == 1  # one round trip for three sources
    assert jev.questions_asked == 3 * len(ASK.output.model_fields)
    assert all(isinstance(r, Judged) for r in results)
    judged = [r for r in results if isinstance(r, Judged)]
    # Each slot's own distribution, not its neighbour's.
    assert [j.output.on_topic for j in judged] == [0.97, 0.1, 0.97]
    batch = ASK.batched("source")
    for j, (subjects, state) in zip(judged, items, strict=True):
        assert j.judgment.subjects == subjects
        assert j.judgment.state_sha256 == input_sha256(state)  # the single-request state
        assert j.judgment.bundle_sha256 == batch.sha256
        assert question_screening.decision(j).policy == "question_screening@v1_batch"
        assert output_of(ASK.output, j.judgment) == j.output  # a stored answer replays


async def test_every_question_names_its_own_slot(cassette: ClientFactory, cassette_path: Path):
    jev = JevClient(cassette(fake_jev()), api_key="replay")
    await jev.judge_batch(ASK, _items([_source(0), _source(1)]), subject="source", now=b.T0)
    (entry,) = json.loads(cassette_path.read_text(encoding="utf-8")).values()
    body = json.loads(entry["request_body"])
    state = json.loads(body["state"])  # the prompt text, JSON-encoded by JevClient
    assert set(state) == {"sources", "question", "line", "evidence_set"}
    assert set(state["sources"]) == {"s0", "s1"}
    asked = body["questions"]["s1.on_topic"]["instructions"]
    assert "`sources.s1`" in asked["question"] and "`source`" not in asked["question"]
    assert "`source`" not in asked["instructions"]


async def test_a_batch_of_one_is_the_plain_request(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev()), api_key="replay")
    (result,) = await jev.judge_batch(ASK, _items([_source(0)]), subject="source", now=b.T0)
    assert isinstance(result, Judged)
    assert result.judgment.bundle_sha256 == ASK.sha256
    assert question_screening.decision(result).policy == "question_screening@v1"


async def test_a_source_the_service_refuses_sinks_alone():
    """A request refused for what is in it (400) is split until the bad source stands
    alone; the other sources keep their answers."""
    jev_ok = fake_jev({"on_topic": 0.97})

    async def refuse_poison(request: httpx2.Request) -> httpx2.Response:
        if POISON in request.content.decode():
            return httpx2.Response(400, json={"error": {"message": "max_tokens_exceeded"}})
        return await jev_ok(request)

    counting = Counting(refuse_poison)
    jev = JevClient(_live(counting), api_key="replay")
    sources = [_source(i) for i in range(4)]
    sources[2] = _source(2, text=f"{POISON} " * 60)

    results = await jev.judge_batch(ASK, _items(sources), subject="source", now=b.T0)

    assert [type(r).__name__ for r in results] == ["Judged", "Judged", "JevFailure", "Judged"]
    failure = results[2]
    assert isinstance(failure, JevFailure) and failure.reason == "api_error"
    # [0..3] refused → [0,1] ok, [2,3] refused → [2] refused, [3] ok.
    assert [len(r) // len(ASK.output.model_fields) for r in counting.requests] == [4, 2, 2, 1, 1]


async def test_a_service_outage_is_not_split():
    counting = Counting(fake_jev(status=503))
    jev = JevClient(_live(counting), api_key="replay")
    results = await jev.judge_batch(
        ASK, _items([_source(i) for i in range(4)]), subject="source", now=b.T0
    )
    assert all(isinstance(r, JevFailure) and r.reason == "api_error" for r in results)
    # The SDK retries a 5xx twice; every attempt is the whole batch — halves would not help.
    assert [len(r) for r in counting.requests] == [4 * len(ASK.output.model_fields)] * 3


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_a_refusal_every_half_would_get_is_not_split(status: int):
    """A bad key, or a 400 that is not about size, fails every half alike."""
    counting = Counting(fake_jev(status=status))
    jev = JevClient(_live(counting), api_key="replay")
    results = await jev.judge_batch(
        ASK, _items([_source(i) for i in range(8)]), subject="source", now=b.T0
    )
    assert all(isinstance(r, JevFailure) for r in results)
    assert len(counting.requests) == 1


async def test_states_that_differ_outside_the_subject_are_a_wiring_error(
    cassette: ClientFactory,
):
    jev = JevClient(cassette(fake_jev()), api_key="replay")
    one = question_screening.items(CTX, [_source(0)], b.question(), [])
    other = question_screening.items(CTX, [_source(1)], b.question(), ["another evidence set"])
    with pytest.raises(ValueError, match="differ only under 'source'"):
        await jev.judge_batch(ASK, [*one, *other], subject="source", now=b.T0)


async def test_a_rerun_finds_batched_answers_and_asks_only_the_new_source():
    counting = Counting(fake_jev())
    jev = StoredJev(_live(counting), api_key="replay", known={})
    first = [_source(i) for i in range(3)]
    await jev.judge_batch(ASK, _items(first), subject="source", now=b.T0)
    assert len(jev.fresh) == 3

    again = await jev.judge_batch(ASK, _items([*first, _source(9)]), subject="source", now=b.T0)

    assert all(isinstance(r, Judged) for r in again)
    assert [len(r) for r in counting.requests] == [21, 7]  # the new source, alone
    assert len(jev.fresh) == 4


def test_batches_respect_the_item_cap_and_the_token_budget():
    small = _items([_source(i) for i in range(BATCH_MAX_ITEMS + 3)])
    assert [len(c) for c in batches([s for _, s in small], "source")] == [BATCH_MAX_ITEMS, 3]

    # ~3 bytes a token: each of these is about a third of the budget.
    big_text = "x" * (BATCH_STATE_TOKENS * 3 // 3)
    big = [
        {"question": "q", "source": {"excerpt": big_text}},
        {"question": "q", "source": {"excerpt": big_text}},
        {"question": "q", "source": {"excerpt": big_text}},
        {"question": "q", "source": {"excerpt": "short"}},
    ]
    cut = batches(big, "source")  # pyright: ignore[reportArgumentType]
    assert cut == [[0, 1], [2, 3]]
    assert batches([], "source") == []
