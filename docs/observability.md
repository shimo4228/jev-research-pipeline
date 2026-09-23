# Observability

Traces are OpenTelemetry. With `OTEL_EXPORTER_OTLP_ENDPOINT` unset the SDK is never initialised and
every span is a no-op, so the default run emits nothing. The store and the note's operations block
remain the source of truth for the research numbers; traces are for watching a run.

## Local viewer (no Docker)

```bash
brew tap ctrlspice/otel-desktop-viewer
brew trust ctrlspice/otel-desktop-viewer      # Homebrew refuses untrusted taps by default
brew install --cask otel-desktop-viewer
otel-desktop-viewer                           # UI at http://localhost:8000, OTLP on 4318
```

Add three lines to `~/.config/jrp/env`:

```bash
export OTEL_SERVICE_NAME="jev-research-pipeline"
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
```

Any OTLP backend works; only the standard `OTEL_*` variables are read.

## Spans

- `jrp.line` and `jrp.stage.*`: time per line and per stage.
- `jev.<function>`: one span per Jev request, with question count, number of subjects, model id
  and outcome as attributes.
- The two Qwen sites, through Pydantic AI's built-in instrumentation (prompt text is not sent).
- HTTP requests, through the httpx instrumentation. A cassette-replayed test run shows stage and
  Jev spans but no HTTP spans, because the cassette transport replaces the instrumented one.
