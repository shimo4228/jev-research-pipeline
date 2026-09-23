"""A parallel line-run: bounded in flight, rate-capped, and byte-for-byte the run a
sequential one would have been (judge's timing 2026-09-23: 3 lines took 15-20 min)."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest

from jev_research_pipeline.jev.core import RequestPacer
from jev_research_pipeline.pipeline.concurrency import jev_concurrency, prose_concurrency
from jev_research_pipeline.pipeline.runner import run_pipeline

from . import builders as b
from .conftest import Handler
from .fakes import fake_world
from .test_e2e import env as env  # the fixture, re-exported


def _is_jev(request: httpx2.Request) -> bool:
    return request.url.host == "api.typesafe.ai"


class InFlight:
    """Counts requests open at once to one kind of upstream (Jev by default); each one is
    held for a moment so they overlap."""

    def __init__(self, counts: Callable[[httpx2.Request], bool] | None = None) -> None:
        self.counts = counts or _is_jev
        self.now = 0
        self.peak = 0
        self.total = 0
        self.world = fake_world()

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if not self.counts(request):
            return await self.world(request)
        self.now += 1
        self.total += 1
        self.peak = max(self.peak, self.now)
        try:
            await asyncio.sleep(0.01)
            return await self.world(request)
        finally:
            self.now -= 1


def _client(handler: Handler) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


@pytest.mark.parametrize("limit", [1, 3])
async def test_jev_requests_in_flight_never_exceed_the_limit(env: dict[str, str], limit: int):
    env["JRP_JEV_CONCURRENCY"] = str(limit)
    counter = InFlight()
    await run_pipeline(env, now=b.T0, http=_client(counter), pacing=False)
    assert counter.total > limit
    assert counter.peak == limit


def _store_bytes(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*.jsonld"))}


async def test_parallel_run_writes_what_a_sequential_run_writes(
    env: dict[str, str], tmp_path: Path
):
    outputs: list[tuple[str, dict[str, bytes], list[str]]] = []
    for limit in ("1", "12"):
        run_env = {
            **env,
            "JRP_JEV_CONCURRENCY": limit,
            "JRP_PROSE_CONCURRENCY": limit if limit == "1" else "3",
            "JRP_STORE_DIR": str(tmp_path / f"store-{limit}"),
            "JRP_VAULT_DIR": str(tmp_path / f"vault-{limit}"),
        }
        Path(run_env["JRP_VAULT_DIR"]).mkdir()
        (outcome,) = await run_pipeline(run_env, now=b.T0, http=_client(InFlight()), pacing=False)
        outputs.append(
            (
                outcome.note.read_text(encoding="utf-8"),
                _store_bytes(Path(run_env["JRP_STORE_DIR"])),
                outcome.operations,
            )
        )
    (seq_note, seq_store, seq_ops), (par_note, par_store, par_ops) = outputs
    assert par_note == seq_note
    assert par_store == seq_store
    assert par_ops == seq_ops


async def test_pacer_holds_the_window():
    """The 1,201st request of a minute waits for the first one to leave the window."""
    clock = [0.0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock[0] += seconds

    pacer = RequestPacer(3, clock=lambda: clock[0], sleep=sleep)
    for t in (0.0, 10.0, 20.0):
        clock[0] = t
        await pacer.admit()
    assert slept == []
    clock[0] = 30.0
    await pacer.admit()  # the one at t=0 leaves the window at t=60
    assert slept == [30.0]
    clock[0] = 75.0
    await pacer.admit()  # t=10 and t=20 have left; nothing to wait for
    assert slept == [30.0]


async def test_pacer_serializes_concurrent_callers():
    clock = [0.0]

    async def sleep(seconds: float) -> None:
        clock[0] += seconds

    pacer = RequestPacer(2, clock=lambda: clock[0], sleep=sleep)
    await asyncio.gather(*(pacer.admit() for _ in range(5)))
    # 5 requests at 2 per minute: the last one cannot go before two full windows passed.
    assert clock[0] == 120.0


@pytest.mark.parametrize(
    ("raw", "jev", "prose"),
    [(None, 12, 3), ("4", 4, 4), ("0", 12, 3), ("-2", 12, 3), ("many", 12, 3)],
)
def test_concurrency_env_falls_back_on_anything_but_a_positive_int(
    raw: str | None, jev: int, prose: int
):
    env = {} if raw is None else {"JRP_JEV_CONCURRENCY": raw, "JRP_PROSE_CONCURRENCY": raw}
    assert jev_concurrency(env) == jev
    assert prose_concurrency(env) == prose


def _four_questions(env: dict[str, str]) -> None:
    """Four open questions on the e2e line, so four question-days want prose at once."""
    body = "".join(
        f"## 問い {n} は何で決まるのか\n- slug: q{n}\n- version: 1\n- status: open\n"
        f"- brief: 記憶機構の違い {n} が下流の精度をどれだけ動かすか。\n\n"
        for n in range(4)
    )
    Path(env["JRP_QUESTIONS_DIR"], "akc.md").write_text(
        f"<!-- jrp:questions:akc -->\n\n{body}", encoding="utf-8"
    )


def _is_prose(request: httpx2.Request) -> bool:
    return (
        request.url.host == "dashscope-intl.aliyuncs.com"
        and json.loads(request.content)["model"] == "qwen3.8-max"
    )


async def test_prose_for_several_questions_runs_side_by_side_within_its_limit(
    env: dict[str, str],
):
    _four_questions(env)
    env["JRP_PROSE_CONCURRENCY"] = "2"
    counter = InFlight(_is_prose)
    (outcome,) = await run_pipeline(env, now=b.T0, http=_client(counter), pacing=False)
    assert outcome.note.read_text(encoding="utf-8").count("jrp:qday:") == 4
    assert counter.total >= 4
    assert counter.peak == 2


async def test_several_question_days_in_parallel_write_the_sequential_note(
    env: dict[str, str], tmp_path: Path
):
    _four_questions(env)
    notes: list[tuple[str, dict[str, bytes]]] = []
    for limit in ("1", "3"):
        run_env = {
            **env,
            "JRP_JEV_CONCURRENCY": limit,
            "JRP_PROSE_CONCURRENCY": limit,
            "JRP_STORE_DIR": str(tmp_path / f"store-{limit}"),
            "JRP_VAULT_DIR": str(tmp_path / f"vault-{limit}"),
        }
        Path(run_env["JRP_VAULT_DIR"]).mkdir()
        (outcome,) = await run_pipeline(
            run_env, now=b.T0, http=_client(InFlight(_is_prose)), pacing=False
        )
        notes.append(
            (outcome.note.read_text(encoding="utf-8"), _store_bytes(Path(run_env["JRP_STORE_DIR"])))
        )
    assert notes[0] == notes[1]


async def test_prefilter_starts_before_the_last_net_is_fetched(env: dict[str, str]):
    """The firehose's sources are prefiltered while the keyword net is still being
    fetched, instead of the whole run waiting for the slowest (paced) net first."""
    order: list[str] = []
    world = fake_world()

    async def record(request: httpx2.Request) -> httpx2.Response:
        body = request.content.decode() if request.url.host == "api.typesafe.ai" else ""
        order.append("prefilter" if "q0_on_topic" in body else request.url.host or "")
        if request.url.host == "export.arxiv.org":
            await asyncio.sleep(0.05)  # a keyword request that takes its time (pacing, network)
        return await world(request)

    await run_pipeline(env, now=b.T0, http=_client(record), pacing=False)
    first_prefilter = order.index("prefilter")
    last_keyword_fetch = max(i for i, host in enumerate(order) if host == "export.arxiv.org")
    assert first_prefilter < last_keyword_fetch
