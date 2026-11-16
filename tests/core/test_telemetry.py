"""Telemetry setup, log correlation and cost arithmetic (task 012)."""

import json
import logging
from collections.abc import Callable, Iterator

import pytest
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.core.config import Settings, get_settings
from app.core.logging import JsonFormatter
from app.core.telemetry import _exporter, configure_telemetry, tracer
from app.documents import service as documents_service
from app.generation.costs import add_costs, cost_at, estimate_cost
from app.ingestion.chunking import TokenWindowChunker
from app.worker import build_handlers, process_next_job
from tests.conftest import ingest_request
from tests.fakes import FakeEmbedder, WhitespaceTokenizer
from tests.telemetry_plugin import PROVIDER


def test_configure_keeps_an_already_installed_provider() -> None:
    assert configure_telemetry("evidencedesk-api") is PROVIDER


def test_exporter_choice_follows_the_setting() -> None:
    assert _exporter("none") is None
    assert isinstance(_exporter("console"), ConsoleSpanExporter)
    assert isinstance(_exporter("otlp"), OTLPSpanExporter)


def test_an_unknown_exporter_is_rejected_at_settings_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEMETRY_EXPORTER", "jaeger")

    with pytest.raises(ValidationError):
        Settings()


def _formatted(message: str) -> dict:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, message, None, None)
    return json.loads(JsonFormatter().format(record))


def test_log_lines_inside_a_span_carry_its_trace_id() -> None:
    with tracer.start_as_current_span("unit") as span:
        inside = _formatted("inside")
        context = span.get_span_context()

    assert inside["trace_id"] == f"{context.trace_id:032x}"
    assert inside["span_id"] == f"{context.span_id:016x}"
    assert "trace_id" not in _formatted("outside")


@pytest.fixture
def prices(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    def _set(value: str) -> None:
        monkeypatch.setenv("LLM_PRICES", value)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


def test_cost_is_tokens_times_price_per_million(prices: Callable[[str], None]) -> None:
    prices('{"m": [1.0, 2.0]}')

    # 100 input x $1/M + 20 output x $2/M = $0.00014
    assert estimate_cost("m", 100, 20) == pytest.approx(0.00014)
    assert cost_at((1.0, 2.0), 1_000_000, 0) == pytest.approx(1.0)
    assert estimate_cost("unpriced", 100, 20) is None


def test_a_total_cost_is_unknown_once_any_part_is() -> None:
    assert add_costs(0.0, 0.5) == 0.5
    assert add_costs(0.5, None) is None
    assert add_costs(None, 0.5) is None


def test_each_worker_job_is_a_span_with_its_outcome(
    db_session: Session, make_tenant: Callable[..., Tenant], spans: InMemorySpanExporter
) -> None:
    documents_service.ingest_document(db_session, make_tenant().id, ingest_request())
    settings = get_settings()
    chunker = TokenWindowChunker(
        WhitespaceTokenizer(), settings.chunk_max_tokens, settings.chunk_overlap_tokens
    )

    assert process_next_job(db_session, build_handlers(chunker, FakeEmbedder()))

    (job,) = [span for span in spans.get_finished_spans() if span.name == "job"]
    assert job.attributes["job.kind"] == "ingest"
    assert job.attributes["job.outcome"] == "succeeded"
