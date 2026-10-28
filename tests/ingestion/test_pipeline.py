from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.documents import service as documents_service
from app.documents.models import Document, DocumentChunk, DocumentStatus
from app.ingestion.chunking import TokenWindowChunker
from app.ingestion.pipeline import IngestionError, process_document
from tests.conftest import ingest_request
from tests.fakes import FakeEmbedder, WhitespaceTokenizer

LONG_CONTENT = "# Guide\n\n" + " ".join(f"word{i}" for i in range(120)) + "\n\n## Next\n\nMore.\n"
CHUNKER = TokenWindowChunker(WhitespaceTokenizer(), max_tokens=50, overlap_tokens=10)


def _document(session: Session, tenant: Tenant, content: str = LONG_CONTENT) -> Document:
    result = documents_service.ingest_document(session, tenant.id, ingest_request(content=content))
    return documents_service.get_document(session, tenant.id, result.document_id)


def _chunks(session: Session, document: Document) -> list[DocumentChunk]:
    query = select(DocumentChunk).where(DocumentChunk.document_id == document.id)
    return list(session.scalars(query.order_by(DocumentChunk.ordinal)))


def test_chunks_are_stored_with_exact_offsets_and_owner_tenant(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    document = _document(db_session, tenant)

    count = process_document(db_session, document, CHUNKER, FakeEmbedder())

    chunks = _chunks(db_session, document)
    assert count == len(chunks) > 1
    assert document.status == DocumentStatus.INGESTED
    for chunk in chunks:
        assert document.content[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.tenant_id == tenant.id
        assert chunk.chunker == "tokens-50-overlap-10"
        assert chunk.embedding_model == "fake-embedder"
        assert len(chunk.embedding) == 384


def test_reprocessing_replaces_chunks_instead_of_duplicating(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    document = _document(db_session, make_tenant())

    first = process_document(db_session, document, CHUNKER, FakeEmbedder())
    second = process_document(db_session, document, CHUNKER, FakeEmbedder())

    assert first == second == len(_chunks(db_session, document))


def test_document_without_indexable_text_is_rejected(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    document = _document(db_session, make_tenant(), content="# Only\n\n## Headings\n")

    with pytest.raises(IngestionError, match="no indexable text"):
        process_document(db_session, document, CHUNKER, FakeEmbedder())
