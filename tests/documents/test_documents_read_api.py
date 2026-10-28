"""Reads must never cross tenants: another tenant's IDs behave exactly like missing ones."""

import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.models import Role, Tenant, User
from app.documents import service as documents_service
from app.ingestion.chunking import TokenWindowChunker
from app.worker import build_handlers, process_next_job
from tests.conftest import auth_headers, ingest_request
from tests.fakes import FakeEmbedder, WhitespaceTokenizer


def _ingest(
    session: Session, tenant: Tenant, **overrides: object
) -> documents_service.IngestResult:
    return documents_service.ingest_document(session, tenant.id, ingest_request(**overrides))


def test_list_shows_only_own_documents_with_filters(
    client: TestClient,
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    make_user: Callable[..., User],
) -> None:
    tenant_a, tenant_b = make_tenant(), make_tenant()
    _ingest(db_session, tenant_a, slug="a/one", version="1")
    _ingest(db_session, tenant_a, slug="a/two", version="2")
    _ingest(db_session, tenant_b, slug="b/one", version="1")
    headers_a = auth_headers(make_user(tenant=tenant_a))

    everything = client.get("/v1/documents", headers=headers_a).json()
    version_two = client.get("/v1/documents?version=2", headers=headers_a).json()

    assert sorted(item["slug"] for item in everything["items"]) == ["a/one", "a/two"]
    assert everything["total"] == 2
    assert [item["slug"] for item in version_two["items"]] == ["a/two"]
    assert "content" not in everything["items"][0]


def test_detail_reports_chunk_count_after_processing(
    client: TestClient,
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    make_user: Callable[..., User],
) -> None:
    tenant = make_tenant()
    result = _ingest(db_session, tenant, metadata={"license": "MIT"})
    chunker = TokenWindowChunker(WhitespaceTokenizer(), max_tokens=5, overlap_tokens=1)
    process_next_job(db_session, build_handlers(chunker, FakeEmbedder()))

    response = client.get(
        f"/v1/documents/{result.document_id}", headers=auth_headers(make_user(tenant=tenant))
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ingested"
    assert body["chunk_count"] > 1
    assert body["metadata"] == {"license": "MIT"}


def test_other_tenants_document_and_job_are_not_found(
    client: TestClient,
    db_session: Session,
    make_tenant: Callable[..., Tenant],
    make_user: Callable[..., User],
) -> None:
    owner_tenant = make_tenant()
    result = _ingest(db_session, owner_tenant)
    outsider = auth_headers(make_user(Role.ADMIN))
    owner = auth_headers(make_user(tenant=owner_tenant))

    for path in (f"/v1/documents/{result.document_id}", f"/v1/jobs/{result.job_id}"):
        assert client.get(path, headers=owner).status_code == 200
        response = client.get(path, headers=outsider)
        missing = client.get(path.rsplit("/", 1)[0] + f"/{uuid.uuid4()}", headers=outsider)
        assert response.status_code == missing.status_code == 404
        assert response.json() == missing.json()


def test_list_limit_is_capped(client: TestClient, make_user: Callable[..., User]) -> None:
    response = client.get("/v1/documents?limit=101", headers=auth_headers(make_user()))

    assert response.status_code == 422
