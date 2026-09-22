"""OpenTelemetry wiring (author decision 2026-09-23): the live-debugging channel.

Not a hand-rolled tracer and not a cloud account: the Qwen calls are traced by
pydantic-ai's own instrumentation, the Jev calls and the run's stages by explicit spans
here, and export is configured only through the standard `OTEL_*` env vars. The store and
the report's operations section stay the source of truth for the research meters.

setup_telemetry() is called once by the CLI:
- no OTEL_EXPORTER_OTLP_ENDPOINT → the SDK is never initialized. The API's no-op tracer
  stays in place, so every span below costs nothing. (An initialized SDK with no endpoint
  would quietly buffer failed exports to localhost:4318.)
- endpoint set → opentelemetry.instrumentation.auto_instrumentation.initialize() reads
  every OTEL_* var (exporter, protocol, service name, sampler) and loads the httpx2
  instrumentation; pydantic-ai is instrumented process-wide without message content.

Local viewer (search-first 2026-09-23, README has the three env lines):
    brew tap ctrlspice/otel-desktop-viewer && brew install --cask otel-desktop-viewer
"""

import os
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Final

from opentelemetry import trace
from opentelemetry.trace import Span
from opentelemetry.util.types import AttributeValue

SERVICE_NAME: Final = "jev-research-pipeline"
ENDPOINT_ENV: Final = "OTEL_EXPORTER_OTLP_ENDPOINT"
PROTOCOL_ENV: Final = "OTEL_EXPORTER_OTLP_PROTOCOL"
DEFAULT_PROTOCOL: Final = "http/protobuf"
"""Python's SDK defaults OTLP to grpc; the local viewers speak http/protobuf on :4318."""

tracer: Final = trace.get_tracer(SERVICE_NAME)


def setup_telemetry(env: Mapping[str, str] | None = None) -> bool:
    """True when traces are exported. Safe to call once per process; never raises."""
    # initialize() reads os.environ, so a caller-supplied mapping is merged into it first:
    # otherwise the endpoint could be "set" for the check and missing for the exporter.
    for key, value in (env or {}).items():
        if key.startswith("OTEL_"):
            os.environ.setdefault(key, value)
    if not os.environ.get(ENDPOINT_ENV):
        return False
    os.environ.setdefault(PROTOCOL_ENV, DEFAULT_PROTOCOL)
    os.environ.setdefault("OTEL_SERVICE_NAME", SERVICE_NAME)
    # No stubs ship for the auto-instrumentation entry point; it is one call, in one place.
    from opentelemetry.instrumentation.auto_instrumentation import (  # pyright: ignore[reportMissingTypeStubs]
        initialize,
    )
    from pydantic_ai import Agent
    from pydantic_ai.models.instrumented import InstrumentationSettings

    initialize()
    # include_content=False: prompts carry third-party claim text; traces are for timing
    # and failures, the store keeps the content.
    Agent.instrument_all(InstrumentationSettings(include_content=False))
    return True


@contextmanager
def span(name: str, **attributes: AttributeValue) -> Generator[Span]:
    """One pipeline stage or one judgment. Attributes are prefixed `jrp.`."""
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(f"jrp.{key}", value)
        yield current
