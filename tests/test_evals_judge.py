"""The intake eval's judge (evals.judge) and freeze (evals.freeze): a stored prefilter answer
is replayed by its run @id, a missing one is asked once under the USD cap and kept in the
bench, the noise floor re-asks identical states; a frozen request is sent once and kept
without its headers. Jev answers come from synthetic cassettes; the freeze's upstream is a
fake transport."""

import json
from dataclasses import replace
from pathlib import Path
from typing import override

import httpx2
import pytest

from jev_research_pipeline.cassette import Cassette, FreezeTransport
from jev_research_pipeline.evals import freeze
from jev_research_pipeline.evals.intake import LineSetup
from jev_research_pipeline.evals.judge import (
    BudgetExceeded,
    Judge,
    Spend,
    judgments_partition,
    measure_jitter,
    read_jitter,
)
from jev_research_pipeline.jev import LineContext, question_prefilter
from jev_research_pipeline.jev.core import JEV_MODEL
from jev_research_pipeline.model import GraphNodeType, Judgment, NoulAnswer, SourceItem, StageRecord
from jev_research_pipeline.pipeline import nets
from jev_research_pipeline.store import Partition, input_sha256

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_jev

LONG = "An abstract long enough to clear the body floor of the screen. " * 5


def setup() -> LineSetup:
    q = b.question()
    return LineSetup(
        slug="akc",
        ctx=LineContext(line=b.line(), vocabulary=("agent memory",)),
        questions=(q,),
        queries={},
        nets=nets.NetConfig(),
        firehose_query="agent memory",
    )


def source(n: int) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url=f"https://arxiv.org/abs/2610.{n:05d}",
        title=f"Paper {n}",
        text=LONG,
        fetched_at=b.T0,
    )


def stored(s: SourceItem, p: float) -> Judgment:
    """The Judgment a run made for this source under setup()'s questions."""
    ask = question_prefilter.ask(1)
    state = question_prefilter.state(setup().ctx, s, setup().questions)
    return Judgment.new(
        function="question_prefilter",
        subjects=(s.id,),
        model=JEV_MODEL,
        state_sha256=input_sha256(state),
        bundle_sha256=ask.sha256,
        answers=(NoulAnswer(key="q0_on_topic", p_yes=p),),
        judged_at=b.T0,
    )


class NoNetwork(httpx2.AsyncBaseTransport):
    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"sent {request.url}")


def judge(
    tmp_path: Path,
    known: dict[str, GraphNodeType],
    *,
    http: httpx2.AsyncClient | None,
    cap: float = 0.5,
) -> Judge:
    return Judge(
        setup(), known, tmp_path, Spend(cap=cap), http=http, api_key="replay" if http else None
    )


async def test_a_stored_answer_is_replayed_and_a_missing_one_stays_unjudged_without_a_key(
    tmp_path: Path,
):
    hit, miss = source(1), source(2)
    j = stored(hit, 0.8)
    verdicts = await judge(tmp_path, {j.id: j}, http=None).verdicts([hit, miss], now=b.T0)
    assert set(verdicts) == {hit.id}
    assert verdicts[hit.id].passes and not verdicts[hit.id].fresh
    assert verdicts[hit.id].margin == pytest.approx(0.3)


async def test_over_the_cap_nothing_is_sent(tmp_path: Path):
    async with httpx2.AsyncClient(transport=NoNetwork()) as http:
        j = judge(tmp_path, {}, http=http, cap=0.0)
        with pytest.raises(BudgetExceeded, match="上限"):
            await j.verdicts([source(1)], now=b.T0)
    assert j.spend.requests == 0


async def test_a_missing_answer_is_asked_once_and_kept_in_the_bench(
    tmp_path: Path, cassette: ClientFactory
):
    s = source(3)
    j = judge(tmp_path, {}, http=cassette(fake_jev({"q0_on_topic": 0.7})))
    verdicts = await j.verdicts([s], now=b.T0)
    assert verdicts[s.id].passes and verdicts[s.id].fresh
    assert (j.spend.requests, j.spend.input_tokens) == (1, 100)
    kept = judgments_partition(tmp_path, "akc").load()
    assert [n.subjects for n in kept.values() if isinstance(n, Judgment)] == [(s.id,)]
    again = judge(tmp_path, dict(kept), http=None)  # the next eval finds it in the bench
    assert (await again.verdicts([s], now=b.T0))[s.id].passes


async def test_the_noise_floor_re_asks_identical_states_and_appends_rows(
    tmp_path: Path, cassette: ClientFactory
):
    sources = [source(10), source(11)]
    known: dict[str, GraphNodeType] = {}
    for s, p in zip(sources, (0.8, 0.45), strict=True):
        j = stored(s, p)
        known[j.id] = j
    jg = judge(tmp_path, known, http=cassette(fake_jev({"q0_on_topic": 0.55})))
    rows = await measure_jitter(jg, sources, n=5, seed="akc", now=b.T0)
    assert sorted((r.p_stored, r.p_again) for r in rows) == [(0.45, 0.55), (0.8, 0.55)]
    assert sum(r.flipped for r in rows) == 1
    assert read_jitter(tmp_path) == rows
    assert sorted(r.delta for r in rows) == [pytest.approx(0.1), pytest.approx(0.25)]


# ------------------------------------------------------------------------------ freeze

HF_DAILY = [{"paper": {"id": "2610.00001", "title": "A paper", "summary": LONG}}]


async def test_the_freeze_transport_sends_a_request_once_and_keeps_no_header(tmp_path: Path):
    calls: list[httpx2.Request] = []

    async def upstream(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200, json=HF_DAILY)

    path = tmp_path / "cassette.json"
    transport = FreezeTransport(Cassette(path), upstream=httpx2.MockTransport(upstream))
    async with httpx2.AsyncClient(transport=transport) as client:
        for _ in range(2):
            got = await client.get(
                "https://huggingface.co/api/daily_papers",
                headers={"Authorization": "Bearer secret"},
            )
            assert got.json() == HF_DAILY
    assert (len(calls), transport.sent) == (1, 1)
    assert "secret" not in path.read_text(encoding="utf-8")


async def test_a_freeze_fetches_through_collect_once_and_stops_on_rate_limits(tmp_path: Path):
    calls: list[str] = []

    async def upstream(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        if "daily_papers" in str(request.url):
            return httpx2.Response(200, json=HF_DAILY)
        return httpx2.Response(429, json={"message": "slow down"})

    planned, skipped = freeze.requests(
        nets.NetConfig(), [("hf_papers", "agent memory"), ("web_search", "x y z")], now=b.T0, env={}
    )
    assert [r.net for r in planned] == ["firehose", "firehose", "keyword"]
    assert skipped and "TAVILY_API_KEY" in skipped[0]
    planned = [replace_pacing(r) for r in planned]
    part = Partition(tmp_path / "snap" / "akc.jsonld")
    cassette = tmp_path / "snap" / "cassette.json"
    done = await freeze.freeze(
        planned,
        part,
        b.line(),
        cassette=cassette,
        now=b.T0,
        env={},
        upstream=httpx2.MockTransport(upstream),
    )
    assert done.results == 1
    assert done.stopped  # arXiv's listing and HF search both answered 429
    assert any(isinstance(n, StageRecord) for n in part.load().values())
    sent = len(calls)
    again = await freeze.freeze(
        planned[:1],
        part,
        b.line(),
        cassette=cassette,
        now=b.T0,
        env={},
        upstream=httpx2.MockTransport(upstream),
    )
    assert (again.sent, len(calls)) == (0, sent)  # collect's StageRecord answers it
    assert json.loads(cassette.read_text(encoding="utf-8"))


def replace_pacing(request: freeze.Request) -> freeze.Request:
    return replace(request, adapter=replace(request.adapter, min_interval_s=0.0))
