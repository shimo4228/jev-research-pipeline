"""Cassette fixture shared by adapter / Jev / Qwen tests.

Three modes, one driver (the test itself):
- default: replay tests/cassettes/<test name>.json offline; a missing entry fails loudly.
- JRP_CASSETTE_SYNTHETIC=1: re-synthesize that file by recording a fake upstream
  (tests/fakes.py). Committed cassettes are produced this way.
- JRP_CASSETTE_RECORD=1: live recording (human-gated) into tests/cassettes/live/, which is
  gitignored — live third-party content never lands in a tracked file by accident, and
  the committed synthetic cassettes are never overwritten. Live cassettes feed
  drift/regression, not these unit tests.
"""

import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx2
import pytest

from jev_research_pipeline.cassette import RECORD_ENV, Cassette, CassetteTransport, cassette_client

CASSETTES = Path(__file__).parent / "cassettes"
SYNTHETIC_ENV = "JRP_CASSETTE_SYNTHETIC"

type Handler = Callable[[httpx2.Request], Coroutine[Any, Any, httpx2.Response]]
type ClientFactory = Callable[[Handler], httpx2.AsyncClient]


@pytest.fixture
def cassette(request: pytest.FixtureRequest) -> ClientFactory:
    """cassette(fake) -> client bound to this test's cassette file."""
    # "tests/test_x.py::test_name[param] (setup)" — FixtureRequest.node is untyped in pytest 9.
    current = os.environ["PYTEST_CURRENT_TEST"].split("::")[-1].split(" ")[0]
    name = current.replace("[", "__").replace("]", "").replace("/", "_")
    path = CASSETTES / f"{request.path.stem}__{name}.json"

    # Synthesis starts from an empty file once per test, even if the test makes several clients.
    if os.environ.get(SYNTHETIC_ENV) == "1":
        path.unlink(missing_ok=True)

    def make(fake: Handler) -> httpx2.AsyncClient:
        if os.environ.get(SYNTHETIC_ENV) == "1":
            transport = CassetteTransport(
                Cassette(path), record=True, upstream=httpx2.MockTransport(fake)
            )
            return httpx2.AsyncClient(transport=transport)
        if os.environ.get(RECORD_ENV) == "1":
            return cassette_client(CASSETTES / "live" / path.name)
        return cassette_client(path)

    return make
