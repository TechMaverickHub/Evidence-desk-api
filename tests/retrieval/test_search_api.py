"""The /v1/search contract: response shape, roles and validation.

Ranking and isolation are covered against the query itself in test_dense_search.py; these
tests go through the API with the worker-produced chunks of the fake embedder.
"""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.models import Tenant, User
from app.core.config import get_settings
from app.documents import service as documents_service
from app.ingestion.chunking import TokenWindowChunker
from app.worker import build_handlers, process_next_job
from tests.conftest import auth_headers, ingest_request
from tests.fakes import FakeEmbedder, WhitespaceTokenizer


@pytest.fixture
def ingested_tenant(db_session: Session, make_tenant: Callable[..., Tenant]) -> Tenant:
    """A tenant with two documents chunked under the configured chunker name."""
    tenant = make_tenant()
    content = "# Caching\n\n" + " ".join(f"word{i}" for i in range(40)) + "\n"
    for slug in ("fastapi/dependencies", "fastapi/caching"):
        documents_service.ingest_document(
            db_session, tenant.id, ingest_request(slug=slug, content=content)
        )
    settings = get_settings()
    # Real chunk sizes so the chunker name matches what search reads; fake tokenizer and vectors.
    chunker = TokenWindowChunker(
        WhitespaceTokenizer(), settings.chunk_max_tokens, settings.chunk_overlap_tokens
    )
    while process_next_job(db_session, build_handlers(chunker, FakeEmbedder())):
        pass
    return tenant


def test_search_returns_ranked_results_with_diagnostics(
    client: TestClient, ingested_tenant: Tenant, make_user: Callable[..., User]
) -> None:
    headers = auth_headers(make_user(tenant=ingested_tenant))

    response = client.post(
        "/v1/search", json={"query": "dependency caching", "k": 1}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    (result,) = body["results"]
    assert result["rank"] == 1
    assert result["document"]["slug"] in {"fastapi/dependencies", "fastapi/caching"}
    assert result["text"].startswith("# Caching")
    diagnostics = body["diagnostics"]
    assert diagnostics["chunker"] == "tokens-300-overlap-50"
    assert diagnostics["embedding_model"] == "fake-embedder"
    assert diagnostics["mode"] == "dense"
    assert set(diagnostics["latency_ms"]) == {"embed_query", "retrieve", "total"}
    assert all(value >= 0 for value in diagnostics["latency_ms"].values())


def test_ranks_are_sequential_and_scores_descending(
    client: TestClient, ingested_tenant: Tenant, make_user: Callable[..., User]
) -> None:
    headers = auth_headers(make_user(tenant=ingested_tenant))

    results = client.post("/v1/search", json={"query": "caching"}, headers=headers).json()[
        "results"
    ]

    assert [result["rank"] for result in results] == list(range(1, len(results) + 1))
    scores = [result["score"] for result in results]
    assert scores == sorted(scores, reverse=True)


def test_tenant_without_documents_gets_an_empty_list(
    client: TestClient, ingested_tenant: Tenant, make_user: Callable[..., User]
) -> None:
    # make_user() without a tenant creates a fresh, empty tenant.
    response = client.post(
        "/v1/search", json={"query": "caching"}, headers=auth_headers(make_user())
    )

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_search_requires_authentication(client: TestClient) -> None:
    assert client.post("/v1/search", json={"query": "caching"}).status_code == 401


@pytest.mark.parametrize(
    ("payload", "bad_field"),
    [
        ({"query": "   "}, "query"),
        ({"query": "x" * 1001}, "query"),
        ({"query": "caching", "k": 0}, "k"),
        ({"query": "caching", "k": 51}, "k"),
        ({"query": "caching", "mode": "hybrid"}, "mode"),
        ({"query": "caching", "tenant_id": "00000000-0000-0000-0000-000000000000"}, "tenant_id"),
        ({"query": "caching", "filters": {"tenant_id": "x"}}, "filters.tenant_id"),
    ],
)
def test_invalid_requests_are_rejected(
    client: TestClient, make_user: Callable[..., User], payload: dict, bad_field: str
) -> None:
    response = client.post("/v1/search", json=payload, headers=auth_headers(make_user()))

    assert response.status_code == 422
    assert bad_field in response.json()["field_errors"]
