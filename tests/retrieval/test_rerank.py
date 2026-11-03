"""Second-stage reranking: ordering rules, candidate depth, and the /v1/search contract."""

import uuid
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.models import Tenant, User
from app.retrieval import service
from app.retrieval.deps import get_reranker_provider
from app.retrieval.repository import SearchHit
from app.retrieval.reranking import rerank_hits
from app.retrieval.service import SearchOptions
from tests.conftest import auth_headers
from tests.fakes import FakeEmbedder, FakeReranker
from tests.retrieval.test_keyword_search import _add_chunk


def _hit(text: str) -> SearchHit:
    return SearchHit(
        chunk_id=uuid.uuid4(),
        text=text,
        char_start=0,
        char_end=len(text),
        heading_path="",
        document_id=uuid.uuid4(),
        source="s",
        slug="doc",
        version="1",
        title="t",
        score=0.5,
        dense_rank=None,
    )


# --- rerank_hits -----------------------------------------------------------------------------


def test_hits_are_reordered_by_rerank_score_and_cut_to_k() -> None:
    hits = [_hit("a"), _hit("b"), _hit("c")]
    reranker = FakeReranker(scores={"a": 0.1, "b": 2.0, "c": 1.0})

    reranked = rerank_hits(reranker, "q", hits, k=2)

    assert [hit.text for hit in reranked] == ["b", "c"]
    assert [hit.first_stage_rank for hit in reranked] == [2, 3]
    assert [hit.rerank_score for hit in reranked] == [2.0, 1.0]
    assert [hit.score for hit in reranked] == [2.0, 1.0]


def test_equal_rerank_scores_keep_the_first_stage_order() -> None:
    hits = [_hit("a"), _hit("b"), _hit("c")]

    reranked = rerank_hits(FakeReranker(scores={"a": 1, "b": 5, "c": 1}), "q", hits, k=3)

    assert [hit.text for hit in reranked] == ["b", "a", "c"]


def test_no_candidates_means_no_model_call() -> None:
    reranker = FakeReranker()

    assert rerank_hits(reranker, "q", [], k=5) == []
    assert reranker.calls == []


# --- Through the service ---------------------------------------------------------------------


def test_the_reranker_scores_rerank_depth_candidates_then_returns_k(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    for text in ("alpha", "beta", "gamma", "delta", "epsilon"):
        _add_chunk(db_session, tenant, text)
    reranker = FakeReranker(scores={"gamma": 9.0})
    options = SearchOptions(k=2, rerank=True, rerank_depth=3)

    outcome = service.search(db_session, tenant.id, FakeEmbedder(), "q", options, reranker)

    ((_, passages),) = reranker.calls
    assert len(passages) == 3
    assert len(outcome.hits) == 2
    assert set(outcome.latency_ms) == {"embed_query", "dense", "rerank", "total"}
    assert all(hit.dense_rank is not None for hit in outcome.hits)
    # Expected: the scored passages by rerank score, first-stage order breaking ties.
    scores = reranker.score("q", passages)
    expected = sorted(range(3), key=lambda i: (-scores[i], i))[:2]
    assert [hit.text for hit in outcome.hits] == [passages[i] for i in expected]


def test_rerank_without_a_reranker_is_a_programming_error(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    with pytest.raises(ValueError, match="no reranker"):
        service.search(
            db_session, make_tenant().id, FakeEmbedder(), "q", SearchOptions(rerank=True)
        )


# --- /v1/search -----------------------------------------------------------------------------


def test_rerank_requests_report_scores_ranks_and_the_model(
    client: TestClient,
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    make_user: Callable[..., User],
) -> None:
    tenant = make_tenant()
    for text in ("graceful shutdown timeout", "worker processes", "keep alive"):
        _add_chunk(db_session, tenant, text)
    headers = auth_headers(make_user(tenant=tenant))

    body = client.post(
        "/v1/search",
        json={"query": "graceful shutdown", "k": 2, "rerank": True},
        headers=headers,
    ).json()

    assert body["diagnostics"]["reranker_model"] == "fake-reranker"
    assert "rerank" in body["diagnostics"]["latency_ms"]
    first = body["results"][0]
    assert first["text"] == "graceful shutdown timeout"
    assert first["rerank_score"] == 2.0
    assert first["first_stage_rank"] is not None


def test_searches_without_rerank_never_load_the_reranker(
    app: FastAPI,
    client: TestClient,
    make_user: Callable[..., User],
) -> None:
    loads: list[str] = []

    def spy() -> FakeReranker:
        loads.append("loaded")
        return FakeReranker()

    app.dependency_overrides[get_reranker_provider] = lambda: spy

    response = client.post(
        "/v1/search", json={"query": "anything"}, headers=auth_headers(make_user())
    )

    assert response.status_code == 200
    assert response.json()["diagnostics"]["reranker_model"] is None
    assert loads == []
