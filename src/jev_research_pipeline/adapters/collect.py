"""One fetch as an idempotent stage: (adapter, query, run date) → source @ids.

The run date is part of the input: the same query re-run the same day is skipped, but
tomorrow's rotation fetches again (research sources change daily). Failures are not
recorded as done, so the next run retries them.
"""

from collections.abc import Mapping

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline.model import Line, SourceItem
from jev_research_pipeline.store import Partition, StageCache, input_sha256

from .base import Adapter, FetchOutcome


async def collect(
    adapter: Adapter,
    client: httpx2.AsyncClient,
    partition: Partition,
    line: Line,
    query: str,
    *,
    now: AwareDatetime,
    env: Mapping[str, str],
) -> FetchOutcome:
    stage = f"fetch_{adapter.net}_{adapter.kind}"
    key = input_sha256(
        {
            "adapter": adapter.kind,
            "net": adapter.net,
            "query": query,
            "run_date": now.date().isoformat(),
        }
    )
    cache = StageCache(partition)
    done = cache.lookup(stage, key)
    if done is not None:
        nodes = partition.load()
        sources = tuple(n for i in done if isinstance(n := nodes[i], SourceItem))
        return FetchOutcome(
            adapter=adapter.kind, query=query, sources=sources, failure=None, cached=True
        )
    outcome = await adapter.fetch(client, line, query, now=now, env=env)
    if outcome.failure is None:
        partition.put(_keep_first_net(outcome.sources, partition))
        cache.record(stage, key, tuple(s.id for s in outcome.sources), now)
    return outcome


def _keep_first_net(sources: tuple[SourceItem, ...], partition: Partition) -> list[SourceItem]:
    """A source is identified by (line, url), so two nets that return the same paper write
    the same node. The net that found it *first* is the one the meters should credit — a
    firehose find re-fetched tomorrow by a keyword query is still a firehose find."""
    if not sources:
        return []
    stored = partition.load()
    return [
        s.model_copy(update={"net": known.net})
        if isinstance(known := stored.get(s.id), SourceItem) and known.net != s.net
        else s
        for s in sources
    ]
