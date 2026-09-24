"""Cassette fixture shared by adapter / Jev / prose-model tests.

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

from jev_research_pipeline.adapters.base import reset_pacing
from jev_research_pipeline.cassette import RECORD_ENV, Cassette, CassetteTransport, cassette_client

CASSETTES = Path(__file__).parent / "cassettes"
SYNTHETIC_ENV = "JRP_CASSETTE_SYNTHETIC"

type Handler = Callable[[httpx2.Request], Coroutine[Any, Any, httpx2.Response]]
type ClientFactory = Callable[[Handler], httpx2.AsyncClient]


def _cassette_path(request: pytest.FixtureRequest) -> Path:
    # "tests/test_x.py::test_name[param] (setup)" — FixtureRequest.node is untyped in pytest 9.
    current = os.environ["PYTEST_CURRENT_TEST"].split("::")[-1].split(" ")[0]
    name = current.replace("[", "__").replace("]", "").replace("/", "_")
    return CASSETTES / f"{request.path.stem}__{name}.json"


@pytest.fixture(autouse=True)
def _fresh_pacing() -> None:
    """Pacing is process-wide per source; one test's request must not delay the next."""
    reset_pacing()


@pytest.fixture
def cassette_path(request: pytest.FixtureRequest) -> Path:
    """This test's cassette file — for asserting on what went on the wire."""
    return _cassette_path(request)


@pytest.fixture
def cassette(request: pytest.FixtureRequest) -> ClientFactory:
    """cassette(fake) -> client bound to this test's cassette file."""
    path = _cassette_path(request)

    # Synthesis starts from an empty file once per test; every client the test makes
    # (e.g. one for Jev, one for the prose model) records into the same Cassette object.
    synthetic = os.environ.get(SYNTHETIC_ENV) == "1"
    if synthetic:
        path.unlink(missing_ok=True)
    shared = Cassette(path)

    def make(fake: Handler) -> httpx2.AsyncClient:
        if synthetic:
            transport = CassetteTransport(shared, record=True, upstream=httpx2.MockTransport(fake))
            return httpx2.AsyncClient(transport=transport)
        if os.environ.get(RECORD_ENV) == "1":
            return cassette_client(CASSETTES / "live" / path.name)
        return cassette_client(path)

    return make
