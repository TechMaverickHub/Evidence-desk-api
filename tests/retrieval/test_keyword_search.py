"""Keyword (full-text) retrieval and hybrid fusion, against real Postgres FTS."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.documents import service as documents_service
from app.documents.models import DocumentChunk
from app.retrieval import service
from app.retrieval.repository import SearchScope, keyword_search
from app.retrieval.service import SearchOptions, configured_chunker
from tests.conftest import ingest_request
from tests.fakes import FakeEmbedder

MODEL = FakeEmbedder.model_name


def _add_chunk(
    session: Session,
    tenant: Tenant,
    text: str,
    *,
    chunker: str | None = None,
    model: str = MODEL,
) -> DocumentChunk:
    """One document per chunk, so slugs stay unique; the tsv is computed by Postgres."""
    slug = f"doc/{uuid.uuid4().hex[:8]}"
    result = documents_service.ingest_document(
        session, tenant.id, ingest_request(slug=slug, content=text)
    )
    chunk = DocumentChunk(
        document_id=result.document_id,
        tenant_id=tenant.id,
        chunker=chunker or configured_chunker(),
        ordinal=0,
        text=text,
        char_start=0,
        char_end=len(text),
        heading_path="",
        embedding=FakeEmbedder().embed_documents([text])[0],
        embedding_model=model,
    )
    session.add(chunk)
    session.flush()
    return chunk


def _keyword(session: Session, tenant: Tenant, query: str, k: int = 10) -> list:
    scope = SearchScope(tenant.id, chunker=configured_chunker(), embedding_model=MODEL)
    return keyword_search(session, scope, query, k)


def test_a_question_matches_chunks_holding_only_some_of_its_terms(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    best = _add_chunk(db_session, tenant, "Uvicorn keeps idle connections alive; default timeout")
    partial = _add_chunk(db_session, tenant, "Uvicorn runs several worker processes")
    _add_chunk(db_session, tenant, "Pydantic validates model fields")

    hits = _keyword(db_session, tenant, "What is Uvicorn's default keep-alive timeout?")

    assert [hit.chunk_id for hit in hits] == [best.id, partial.id]
    assert [hit.keyword_rank for hit in hits] == [1, 2]
    assert hits[0].score > hits[1].score > 0
    assert hits[0].dense_rank is None


def test_command_line_flags_are_searchable(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    flag = _add_chunk(db_session, tenant, "`--timeout-keep-alive <int>` closes idle connections")
    _add_chunk(db_session, tenant, "A timeout for slow clients")

    hits = _keyword(db_session, tenant, "--timeout-keep-alive")

    assert hits[0].chunk_id == flag.id


@pytest.mark.parametrize("query", ["what was it?", "{**} | !! <-> ()"])
def test_queries_without_searchable_terms_return_nothing(
    db_session: Session, make_tenant: Callable[..., Tenant], query: str
) -> None:
    tenant = make_tenant()
    _add_chunk(db_session, tenant, "What was it that failed?")

    assert _keyword(db_session, tenant, query) == []


def test_operator_characters_in_queries_are_plain_text(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    chunk = _add_chunk(db_session, tenant, "Pass x=1&y=2 in the mapping")

    hits = _keyword(db_session, tenant, "mapping {**x} & | ! x=1&y=2 '; drop table chunks;--")

    assert [hit.chunk_id for hit in hits] == [chunk.id]


def test_keyword_search_stays_in_its_tenant_chunker_and_model(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant, other = make_tenant(), make_tenant()
    mine = _add_chunk(db_session, tenant, "graceful shutdown timeout")
    _add_chunk(db_session, other, "graceful shutdown timeout")
    _add_chunk(db_session, tenant, "graceful shutdown timeout", chunker="other-chunker")
    _add_chunk(db_session, tenant, "graceful shutdown timeout", model="other-model")

    hits = _keyword(db_session, tenant, "graceful shutdown")

    assert [hit.chunk_id for hit in hits] == [mine.id]


# --- Hybrid through the service ------------------------------------------------------------


def test_hybrid_fuses_both_rankings_and_reports_each_rank(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    query = "graceful shutdown"
    semantic = _add_chunk(db_session, tenant, "stopping the server politely")
    lexical = _add_chunk(db_session, tenant, "graceful shutdown waits for requests")
    # Pin the query to the semantic chunk's vector: dense rank 1 without shared words.
    pinned = FakeEmbedder().embed_documents([semantic.text])[0]
    embedder = FakeEmbedder(query_vectors={query: pinned})

    outcome = service.search(
        db_session, tenant.id, embedder, query, SearchOptions(k=2, mode="hybrid")
    )

    by_id = {hit.chunk_id: hit for hit in outcome.hits}
    assert set(by_id) == {semantic.id, lexical.id}
    assert by_id[semantic.id].dense_rank == 1
    assert by_id[semantic.id].keyword_rank is None
    assert by_id[lexical.id].keyword_rank == 1
    assert set(outcome.latency_ms) == {"embed_query", "dense", "keyword", "fuse", "total"}


def test_hybrid_falls_back_to_dense_when_the_query_has_no_terms(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    for text in ("first chunk", "second chunk", "third chunk"):
        _add_chunk(db_session, tenant, text)
    embedder = FakeEmbedder()

    dense = service.search(db_session, tenant.id, embedder, "what was it?", SearchOptions(k=3))
    hybrid = service.search(
        db_session, tenant.id, embedder, "what was it?", SearchOptions(k=3, mode="hybrid")
    )

    assert [hit.chunk_id for hit in hybrid.hits] == [hit.chunk_id for hit in dense.hits]
    assert all(hit.keyword_rank is None for hit in hybrid.hits)
