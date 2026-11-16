"""Traces of real requests (task 012): shape, privacy, latency parity, cost, health noise."""

import json
from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.orm import Session

from app.auth.models import Tenant, User
from app.core.config import get_settings
from app.generation.deps import get_llm_client
from tests.conftest import auth_headers
from tests.fakes import ScriptedLLMClient
from tests.retrieval.test_keyword_search import _add_chunk

QUESTION = "Which zebra-violet setting controls preflight caching?"
PASSAGE = "zebra-violet max_age defaults to 600 seconds for preflight caching"


def _reply(citations: tuple = (1,)) -> str:
    return json.dumps({"status": "answered", "answer": "600 s.", "citations": list(citations)})


@pytest.fixture
def headers(
    db_session: Session, make_tenant: Callable[..., Tenant], make_user: Callable[..., User]
) -> dict:
    tenant = make_tenant()
    _add_chunk(db_session, tenant, PASSAGE)
    _add_chunk(db_session, tenant, "GZipMiddleware minimum_size is 500 bytes")
    return auth_headers(make_user(tenant=tenant))


@pytest.fixture
def priced(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("LLM_PRICES", '{"fake-llm": [1.0, 2.0]}')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _answer(app: FastAPI, client: TestClient, headers: dict, *replies: str) -> dict:
    llm = ScriptedLLMClient(*replies)
    app.dependency_overrides[get_llm_client] = lambda: llm
    response = client.post("/v1/answers", json={"question": QUESTION}, headers=headers)
    assert response.status_code == 200
    return response.json()


def test_one_answer_is_one_trace_with_every_stage(
    app: FastAPI, client: TestClient, headers: dict, spans: InMemorySpanExporter
) -> None:
    # A citation outside the passages forces the corrective retry: two LLM calls.
    _answer(app, client, headers, _reply((9,)), _reply())

    finished = spans.get_finished_spans()
    names = [span.name for span in finished]
    for expected in ("answer", "search", "search.embed_query", "search.dense", "search.rerank"):
        assert expected in names
    assert names.count("llm.call") == 2
    assert any(name.startswith("POST /v1/answers") for name in names)
    assert len({span.context.trace_id for span in finished}) == 1
    second_call = [span for span in finished if span.name == "llm.call"][1]
    assert second_call.attributes["llm.attempt"] == 2
    assert second_call.attributes["llm.prompt_tokens"] == 100


def test_no_question_or_passage_text_reaches_any_span(
    app: FastAPI, client: TestClient, headers: dict, spans: InMemorySpanExporter
) -> None:
    _answer(app, client, headers, _reply())

    for span in spans.get_finished_spans():
        dumped = span.to_json()
        assert "zebra-violet" not in dumped, span.name


def test_stage_spans_match_the_reported_latency_stages(
    client: TestClient, headers: dict, spans: InMemorySpanExporter
) -> None:
    body = client.post(
        "/v1/search", json={"query": "max_age", "mode": "hybrid", "rerank": True}, headers=headers
    ).json()

    names = [span.name for span in spans.get_finished_spans()]
    stages = {name.removeprefix("search.") for name in names if name.startswith("search.")}
    assert stages == set(body["diagnostics"]["latency_ms"]) - {"total"}


def test_answer_cost_uses_configured_prices(
    app: FastAPI, client: TestClient, headers: dict, priced: None
) -> None:
    body = _answer(app, client, headers, _reply())

    # One call: 100 prompt x $1/M + 20 completion x $2/M.
    assert body["usage"]["cost_usd"] == pytest.approx(0.00014)


def test_an_unpriced_model_reports_no_cost(app: FastAPI, client: TestClient, headers: dict) -> None:
    assert _answer(app, client, headers, _reply())["usage"]["cost_usd"] is None


def test_health_checks_are_not_traced(client: TestClient, spans: InMemorySpanExporter) -> None:
    assert client.get("/v1/health").status_code == 200

    assert spans.get_finished_spans() == ()
