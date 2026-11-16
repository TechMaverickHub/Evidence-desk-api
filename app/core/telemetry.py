"""OpenTelemetry setup: one tracer provider per process, and the tracer our spans use.

FastAPI 0.162 creates request spans itself when given a provider; our code adds a span per
pipeline stage (search stages, LLM calls, worker jobs). Spans carry counts, sizes, model
names and token counts, never question, passage or answer text.
"""

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExporter

from app.core.config import get_settings

# A proxy until a provider is installed, so modules can create it at import time.
tracer = trace.get_tracer("evidencedesk")


def configure_telemetry(service_name: str) -> TracerProvider:
    """Install the global provider once per process; later calls return the installed one.

    OpenTelemetry allows a single global provider, so tests install theirs (with an
    in-memory exporter) first and this keeps it.
    """
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        return current
    name = os.environ.get("OTEL_SERVICE_NAME") or service_name
    provider = TracerProvider(resource=Resource.create({"service.name": name}))
    exporter = _exporter(get_settings().telemetry_exporter)
    if exporter is not None:
        # Batched and in the background, so exporting never slows a request down.
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def _exporter(kind: str) -> SpanExporter | None:
    if kind == "console":
        return ConsoleSpanExporter()
    if kind == "otlp":
        # Imported here: only deployments that export pay for loading it. Endpoint and
        # headers come from the standard OTEL_EXPORTER_OTLP_* environment variables.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter()
    return None  # "none": spans exist (cheap) but go nowhere
