"""Installs the in-memory tracer provider before anything imports the app.

`app.main` creates the app at import (uvicorn needs `app.main:app`), and that installs a
default global provider. OpenTelemetry allows one global provider per process, so the test
provider must be first. Loaded via `-p tests.telemetry_plugin` in pyproject.toml, which
pytest imports before any conftest.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

SPAN_EXPORTER = InMemorySpanExporter()
PROVIDER = TracerProvider()
PROVIDER.add_span_processor(SimpleSpanProcessor(SPAN_EXPORTER))
trace.set_tracer_provider(PROVIDER)
