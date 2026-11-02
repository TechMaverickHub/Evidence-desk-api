"""Evaluation fixtures: the tiny fixture corpus ingested into a tenant, as the runner expects it."""

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.core.config import get_settings
from app.documents import service as documents_service
from app.evaluation.dataset import Dataset, build_dataset, read_corpus_texts
from app.ingestion.chunking import TokenWindowChunker
from app.ingestion.cli import read_manifest
from app.ingestion.pipeline import process_document
from tests.fakes import FakeEmbedder, WhitespaceTokenizer

FIXTURES = Path(__file__).parents[1] / "fixtures"
MANIFEST = FIXTURES / "corpus" / "manifest.yaml"
MINI = FIXTURES / "datasets" / "mini.yaml"


@pytest.fixture
def mini_dataset() -> Dataset:
    return build_dataset(MINI, MANIFEST, "mini", "s")


@pytest.fixture
def corpus_texts() -> dict[tuple[str, str], str]:
    return read_corpus_texts(MANIFEST)


@pytest.fixture
def load_fixture_corpus(db_session: Session) -> Callable[[Tenant], None]:
    """Ingest and chunk the fixture corpus with the configured chunker name and FakeEmbedder."""
    settings = get_settings()
    # Same max/overlap as the settings, so the chunker name matches what search reads.
    chunker = TokenWindowChunker(
        WhitespaceTokenizer(), settings.chunk_max_tokens, settings.chunk_overlap_tokens
    )

    def _load(tenant: Tenant) -> None:
        for request in read_manifest(MANIFEST):
            result = documents_service.ingest_document(db_session, tenant.id, request)
            document = documents_service.get_document(db_session, tenant.id, result.document_id)
            process_document(db_session, document, chunker, FakeEmbedder())
        db_session.flush()

    return _load
