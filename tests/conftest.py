"""Shared fixtures. Tests run against TEST_DATABASE_URL, never the dev database.

Each test gets a session inside an outer transaction that is rolled back afterwards, so
tests never see each other's data and need no cleanup code.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.orm import Session

from app.auth.models import Role, Tenant, User
from app.core.config import get_settings
from app.core.db import get_engine, get_session, get_sessionmaker
from app.core.security import create_access_token, hash_password
from app.documents import service as documents_service
from app.documents.schemas import IngestDocumentRequest
from app.generation.deps import get_llm_client
from app.ingestion.chunking import TokenWindowChunker
from app.ingestion.cli import read_manifest
from app.ingestion.pipeline import process_document
from app.main import create_app
from app.retrieval.deps import get_query_embedder, get_reranker_provider
from tests.fakes import FakeEmbedder, FakeReranker, WhitespaceTokenizer
from tests.telemetry_plugin import SPAN_EXPORTER

TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    """Spans finished during the test (cleared before it starts)."""
    SPAN_EXPORTER.clear()
    yield SPAN_EXPORTER


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    test_database_url = get_settings().test_database_url
    if not test_database_url:
        pytest.exit("TEST_DATABASE_URL is not set; see .env.example", returncode=2)
    # Repoint the app at the test database, then drop cached objects built from the old URL.
    os.environ["DATABASE_URL"] = test_database_url
    # Never load the real embedding model in the default test run (torch import is slow).
    os.environ["PRELOAD_EMBEDDING_MODEL"] = "false"
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    # migrations/env.py reads DATABASE_URL from settings, so this migrates the test DB.
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def db_session() -> Iterator[Session]:
    connection = get_engine().connect()
    outer_transaction = connection.begin()
    # "create_savepoint" turns every commit/rollback inside the code under test into a
    # savepoint operation, so the outer transaction can still undo everything.
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.fixture
def app(db_session: Session) -> FastAPI:
    # A fresh app per test keeps dependency_overrides and test-only routes isolated.
    application = create_app()
    application.dependency_overrides[get_session] = lambda: db_session
    # A lambda, not the class: FastAPI would read the class's __init__ args as request fields.
    application.dependency_overrides[get_query_embedder] = lambda: FakeEmbedder()
    # The provider is called only for rerank requests; it returns a fake, never the model.
    application.dependency_overrides[get_reranker_provider] = lambda: FakeReranker
    # No LLM unless a test scripts one: a real GROQ_API_KEY in .env must never be used.
    application.dependency_overrides[get_llm_client] = lambda: None
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def test_password_hash() -> str:
    # argon2 is deliberately slow; hash the shared test password once per session.
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def make_tenant(db_session: Session) -> Callable[..., Tenant]:
    def _make_tenant(name: str | None = None) -> Tenant:
        tenant = Tenant(name=name or f"tenant-{uuid.uuid4().hex[:8]}")
        db_session.add(tenant)
        db_session.flush()
        return tenant

    return _make_tenant


@pytest.fixture
def make_user(
    db_session: Session, make_tenant: Callable[..., Tenant], test_password_hash: str
) -> Callable[..., User]:
    def _make_user(
        role: Role = Role.VIEWER, tenant: Tenant | None = None, is_active: bool = True
    ) -> User:
        user = User(
            tenant_id=(tenant or make_tenant()).id,
            email=f"user-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=test_password_hash,
            role=role,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.flush()
        return user

    return _make_user


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.tenant_id, user.role)
    return {"Authorization": f"Bearer {token}"}


def ingest_request(**overrides: object) -> IngestDocumentRequest:
    """A valid ingest payload; override any field per test."""
    fields: dict[str, object] = {
        "source": "fastapi-docs",
        "slug": "fastapi/dependencies",
        "version": "0.115",
        "title": "Dependencies",
        "content": "# Dependencies\n\nUse Depends to declare a dependency in a path operation.\n",
    }
    fields.update(overrides)
    return IngestDocumentRequest.model_validate(fields)


FIXTURE_MANIFEST = Path(__file__).parent / "fixtures" / "corpus" / "manifest.yaml"


@pytest.fixture
def load_fixture_corpus(db_session: Session) -> Callable[[Tenant], None]:
    """Ingest and chunk the fixture corpus with the configured chunker name and FakeEmbedder."""
    settings = get_settings()
    # Same max/overlap as the settings, so the chunker name matches what search reads.
    chunker = TokenWindowChunker(
        WhitespaceTokenizer(), settings.chunk_max_tokens, settings.chunk_overlap_tokens
    )

    def _load(tenant: Tenant) -> None:
        for request in read_manifest(FIXTURE_MANIFEST):
            result = documents_service.ingest_document(db_session, tenant.id, request)
            document = documents_service.get_document(db_session, tenant.id, result.document_id)
            process_document(db_session, document, chunker, FakeEmbedder())
        db_session.flush()

    return _load
