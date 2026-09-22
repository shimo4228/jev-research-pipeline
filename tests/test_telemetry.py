"""OpenTelemetry: stage and Jev spans exist; no endpoint means no SDK (author decision)."""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from jev_research_pipeline.pipeline.runner import run_pipeline
from jev_research_pipeline.telemetry import ENDPOINT_ENV, setup_telemetry

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_world
from .test_e2e import env as env

EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def _provider() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
    trace.set_tracer_provider(provider)


def test_no_endpoint_means_no_sdk():
    assert setup_telemetry({}) is False
    assert setup_telemetry({ENDPOINT_ENV: ""}) is False


async def test_run_emits_stage_and_jev_spans(cassette: ClientFactory, env: dict[str, str]):
    EXPORTER.clear()
    await run_pipeline(env, now=b.T0, http=cassette(fake_world()), pacing=False)
    spans = EXPORTER.get_finished_spans()
    names = {s.name for s in spans}
    assert "jrp.line" in names
    assert {
        "jrp.stage.queries",
        "jrp.stage.fetch",
        "jrp.stage.claims",
        "jrp.stage.sections",
    } <= names
    jev = [s for s in spans if s.name.startswith("jev.")]
    assert jev, names
    attributes = jev[0].attributes or {}
    assert attributes["jrp.model"] == "jev-1.13.0"
    assert int(str(attributes["jrp.questions"])) >= 1
    assert attributes["jrp.outcome"] in {"judged", "timeout", "api_error", "bad_answer"}
    line = next(s for s in spans if s.name == "jrp.line")
    line_attributes = line.attributes or {}
    assert line_attributes["jrp.line"] == "akc"
    assert "jrp.cost_usd" in line_attributes


def test_httpx2_transport_is_instrumented():
    """The OTel httpx instrumentation covers httpx2 (0.65b0 ships HTTPX2ClientInstrumentor
    and an `httpx2` entry point, so initialize() loads it). It wraps httpx2's real
    transport, so live runs get client spans; a replayed run does not, because the
    cassette transport replaces the one that is wrapped."""
    import httpx2
    from opentelemetry.instrumentation.httpx import HTTPX2ClientInstrumentor

    instrumentor = HTTPX2ClientInstrumentor()
    assert any("httpx2" in dep for dep in instrumentor.instrumentation_dependencies())
    instrumentor.instrument()
    try:
        wrapped = httpx2.AsyncHTTPTransport.handle_async_request
        assert getattr(wrapped, "__wrapped__", None) is not None
    finally:
        instrumentor.uninstrument()
    assert getattr(httpx2.AsyncHTTPTransport.handle_async_request, "__wrapped__", None) is None


def test_setup_telemetry_never_raises(monkeypatch: pytest.MonkeyPatch):
    # A mistyped OTEL_* var must not kill an unattended run before the notify path exists.
    monkeypatch.setenv(ENDPOINT_ENV, "http://localhost:4318")
    monkeypatch.setattr(
        "opentelemetry.instrumentation.auto_instrumentation.initialize",
        lambda: (_ for _ in ()).throw(RuntimeError("bad OTEL_TRACES_EXPORTER")),
    )
    assert setup_telemetry({}) is False
