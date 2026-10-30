"""Ranking, filters and tenant isolation of the vector query, with hand-made vectors."""

import math
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.documents import service as documents_service
from app.documents.models import DocumentChunk
from app.retrieval.repository import dense_search
from tests.conftest import ingest_request

CHUNKER = "test-chunker"
MODEL = "fake-embedder"
DIMENSION = 384


def unit_vector(*leading: float) -> list[float]:
    """A unit-length vector whose first components are proportional to `leading`."""
    norm = math.sqrt(sum(value * value for value in leading))
    return [value / norm for value in leading] + [0.0] * (DIMENSION - len(leading))


QUERY = unit_vector(1.0, 0.0)


def _add_chunk(
    session: Session,
    tenant: Tenant,
    vector: list[float],
    *,
    slug: str = "fastapi/dependencies",
    version: str = "0.115",
    source: str = "fastapi-docs",
    chunker: str = CHUNKER,
    model: str = MODEL,
) -> DocumentChunk:
    request = ingest_request(slug=slug, version=version, source=source)
    result = documents_service.ingest_document(session, tenant.id, request)
    ordinal = session.query(DocumentChunk).filter_by(document_id=result.document_id).count()
    chunk = DocumentChunk(
        document_id=result.document_id,
        tenant_id=tenant.id,
        chunker=chunker,
        ordinal=ordinal,
        text=f"chunk {uuid.uuid4().hex[:6]}",
        char_start=0,
        char_end=10,
        heading_path="",
        embedding=vector,
        embedding_model=model,
    )
    session.add(chunk)
    session.flush()
    return chunk


def _search(session: Session, tenant: Tenant, k: int = 10, **filters: str) -> list:
    return dense_search(
        session, tenant.id, QUERY, chunker=CHUNKER, embedding_model=MODEL, k=k, **filters
    )


def test_results_are_ranked_by_cosine_similarity_with_exact_scores(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    far = _add_chunk(db_session, tenant, unit_vector(0.0, 1.0))  # similarity 0
    near = _add_chunk(db_session, tenant, unit_vector(3.0, 4.0))  # similarity 0.6
    same = _add_chunk(db_session, tenant, unit_vector(1.0, 0.0))  # similarity 1

    hits = _search(db_session, tenant)

    assert [hit.chunk_id for hit in hits] == [same.id, near.id, far.id]
    assert [hit.score for hit in hits] == pytest.approx([1.0, 0.6, 0.0], abs=1e-6)


def test_identical_vectors_are_ordered_by_chunk_id(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    chunks = [_add_chunk(db_session, tenant, QUERY) for _ in range(3)]

    first = [hit.chunk_id for hit in _search(db_session, tenant)]
    second = [hit.chunk_id for hit in _search(db_session, tenant)]

    assert first == second == sorted(chunk.id for chunk in chunks)


def test_other_tenants_chunks_are_never_returned(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant_a, tenant_b = make_tenant(), make_tenant()
    own = _add_chunk(db_session, tenant_a, unit_vector(0.0, 1.0))
    _add_chunk(db_session, tenant_b, QUERY)  # a perfect match, but in another tenant

    hits = _search(db_session, tenant_a, k=50)

    assert [hit.chunk_id for hit in hits] == [own.id]


def test_other_chunkers_and_models_are_excluded(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    kept = _add_chunk(db_session, tenant, unit_vector(0.0, 1.0))
    _add_chunk(db_session, tenant, QUERY, chunker="tokens-100-overlap-10")
    _add_chunk(db_session, tenant, QUERY, model="another-model")

    assert [hit.chunk_id for hit in _search(db_session, tenant)] == [kept.id]


def test_source_and_version_filters_narrow_results(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    old = _add_chunk(db_session, tenant, QUERY, version="0.110")
    new = _add_chunk(db_session, tenant, QUERY, version="0.115")
    incident = _add_chunk(db_session, tenant, QUERY, slug="incidents/1", source="incidents")

    assert {hit.chunk_id for hit in _search(db_session, tenant, version="0.110")} == {old.id}
    assert {hit.chunk_id for hit in _search(db_session, tenant, source="incidents")} == {
        incident.id
    }
    by_both = _search(db_session, tenant, source="fastapi-docs", version="0.115")
    assert {hit.chunk_id for hit in by_both} == {new.id}
    assert _search(db_session, tenant, source="unknown") == []


def test_k_limits_the_number_of_results(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    for _ in range(5):
        _add_chunk(db_session, tenant, QUERY)

    assert len(_search(db_session, tenant, k=3)) == 3


def test_hits_carry_document_identity(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    chunk = _add_chunk(db_session, tenant, QUERY)

    (hit,) = _search(db_session, tenant)

    assert (hit.document_id, hit.slug, hit.version, hit.source, hit.title) == (
        chunk.document_id,
        "fastapi/dependencies",
        "0.115",
        "fastapi-docs",
        "Dependencies",
    )
