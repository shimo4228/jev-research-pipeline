"""Freeze a snapshot: each request of the configurations under comparison, sent once, live,
and kept (plan intake-eval, claim 1).

The requests are today's firehose (HF daily, then the arXiv listing, as nets.plan builds
them) and every authored keyword query of the baseline and of the candidate, each once —
not the rotated budget of one run: a frozen set holds what any configuration could send.
They go through adapters.collect itself, into a store-shaped snapshot partition
`<bench>/snapshots/<date>/<slug>.jsonld` (SourceItem + StageRecord), over a FreezeTransport
on `<bench>/snapshots/<date>/cassette.json`. So a second freeze of the same day sends nothing
(collect's StageRecord and the cassette both hold the request), and the snapshot can be
rebuilt offline from the cassette. The cassette keeps no header: the GitHub and Tavily keys
never reach it, and a secret query parameter is dropped from its keys (cassette.SECRET_PARAMS).

Recommendation, citation and exploration are not frozen here: their requests are seeded by
the store's accepted papers, and their history in the store (evals.intake) already holds what
they returned under the seeds of each day.

A rate limit stops that adapter for the rest of the freeze, and a second adapter's stops the
freeze: a burst of 429s on a shared pool is a policy signal, not a transient error (rule
debugging.md). The lines say so, and the caller exits non-zero.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline.adapters import Adapter, collect, firehose
from jev_research_pipeline.cassette import Cassette, FreezeTransport
from jev_research_pipeline.model import AdapterKind, Line
from jev_research_pipeline.pipeline import nets
from jev_research_pipeline.pipeline.run import make_adapter
from jev_research_pipeline.store import Partition

FREEZE_TIMEOUT_S: Final = 30.0
MAX_LIMITED: Final = 2
"""Adapters a rate limit may stop before the freeze stops."""


def snapshot_dir(bench: Path, day: date) -> Path:
    return bench / "snapshots" / day.isoformat()


def snapshot_partition(bench: Path, day: date, slug: str) -> Partition:
    return Partition(snapshot_dir(bench, day) / f"{slug}.jsonld")


@dataclass(frozen=True)
class Request:
    net: str
    adapter: Adapter
    query: str


@dataclass
class Frozen:
    """What one freeze did, for the printed lines."""

    sent: int = 0
    """Requests that went upstream (the rest were already in the cassette or the snapshot)."""
    results: int = 0
    credits: int = 0
    lines: list[str] = field(default_factory=list[str])
    limited: list[str] = field(default_factory=list[str])
    """`<net>/<adapter>` sources a rate limit stopped."""

    @property
    def stopped(self) -> bool:
        return len(self.limited) >= MAX_LIMITED


def requests(
    config: nets.NetConfig,
    queries: Sequence[tuple[AdapterKind, str]],
    *,
    now: AwareDatetime,
    env: Mapping[str, str],
) -> tuple[list[Request], list[str]]:
    """Today's firehose (when the line has it) and each query once; and the lines for the
    queries whose adapter needs a key the env does not have."""
    plan = nets.plan(
        config,
        hf_date=firehose.hf_date(now),
        keyword_queries=[],
        positives=[],
        negatives=[],
        cited=[],
        topics=[],
    )
    out = [Request(r.net, r.adapter, r.query) for r in plan if r.net == "firehose"]
    skipped: list[str] = []
    for kind, text in dict.fromkeys(queries):
        adapter = make_adapter(kind, today=now.date())
        if adapter.required_env is not None and not env.get(adapter.required_env):
            skipped.append(f"  {kind}: {text} → {adapter.required_env} 未設定のため凍結しない")
            continue
        out.append(Request("keyword", adapter, text))
    return out, skipped


async def freeze(
    planned: Sequence[Request],
    partition: Partition,
    line: Line,
    *,
    cassette: Path,
    now: AwareDatetime,
    env: Mapping[str, str],
    upstream: httpx2.AsyncBaseTransport | None = None,
) -> Frozen:
    """Send what is not frozen yet, in order; `upstream` is the network (tests pass a fake)."""
    transport = FreezeTransport(
        Cassette(cassette), upstream=upstream or httpx2.AsyncHTTPTransport()
    )
    done = Frozen()
    async with httpx2.AsyncClient(transport=transport, timeout=FREEZE_TIMEOUT_S) as client:
        for request in planned:
            source = f"{request.net}/{request.adapter.kind}"
            if source in done.limited:
                done.lines.append(f"  {source}: {request.query} → 送らない (rate limit で停止中)")
                continue
            if done.stopped:
                break
            out = await collect(
                request.adapter, client, partition, line, request.query, now=now, env=env
            )
            if out.failure is not None:
                done.lines.append(
                    f"  {source}: {request.query} → 失敗 ({out.failure.reason}: "
                    f"{out.failure.detail})"
                )
                if nets.is_rate_limit(out.failure):
                    done.limited.append(source)
                continue
            done.results += len(out.sources)
            done.credits += out.credits
            state = "凍結済み" if out.cached else "取得"
            done.lines.append(f"  {source}: {request.query} → {len(out.sources)} 件 ({state})")
    done.sent = transport.sent
    if done.stopped:
        done.lines.append(
            f"  rate limit が {len(done.limited)} つの取得元で続いたので凍結を止めた "
            f"({', '.join(done.limited)})"
        )
    return done
