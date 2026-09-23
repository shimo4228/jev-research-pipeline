"""How much of a line-run is in flight at once (judge's timing, 2026-09-23: 3 lines took
15-20 min because every (source, question) pair waited for the one before it).

JRP_JEV_CONCURRENCY    Jev requests in flight (default 12 — the vendor cookbook's fan-out)
JRP_PROSE_CONCURRENCY  Qwen calls in flight: the per-question prose ladder
                       (default 3; one prose call runs 40-300 s)

The Jev request rate is capped separately, in JevClient (1,200 rpm, docs.typesafe.ai
models, as-of 2026-09-23). A mis-set variable must not cost the run: anything that is not
a positive integer falls back to the default, like JRP_PROSE_TIMEOUT_S.
"""

from collections.abc import Mapping
from typing import Final

JEV_CONCURRENCY_ENV: Final = "JRP_JEV_CONCURRENCY"
JEV_CONCURRENCY: Final = 12
PROSE_CONCURRENCY_ENV: Final = "JRP_PROSE_CONCURRENCY"
PROSE_CONCURRENCY: Final = 3


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        value = int(env.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def jev_concurrency(env: Mapping[str, str]) -> int:
    return _positive_int(env, JEV_CONCURRENCY_ENV, JEV_CONCURRENCY)


def prose_concurrency(env: Mapping[str, str]) -> int:
    return _positive_int(env, PROSE_CONCURRENCY_ENV, PROSE_CONCURRENCY)
