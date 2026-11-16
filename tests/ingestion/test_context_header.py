"""Contextual-header chunker variants: naming, model input, offsets, and search parity."""

from collections.abc import Callable, Sequence

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.documents import service as documents_service
from app.documents.models import DocumentChunk
from app.ingestion.chunking import (
    TokenWindowChunker,
    chunker_name,
    contextual_header,
    has_context_header,
    model_input,
)
from app.ingestion.pipeline import process_document
from app.retrieval import service
from app.retrieval.service import SearchOptions
from tests.conftest import ingest_request
from tests.fakes import FakeEmbedder, FakeReranker, WhitespaceTokenizer

CONTENT = "# Middleware\n\n## CORS\n\nmax_age defaults to 600 seconds for preflight caching.\n"


class RecordingEmbedder(FakeEmbedder):
    """FakeEmbedder that keeps the passage texts it was asked to embed."""

    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.inputs += list(texts)
        return super().embed_documents(texts)


def test_names_say_whether_a_variant_carries_a_header() -> None:
    assert chunker_name(150, 30) == "tokens-150-overlap-30"
    assert chunker_name(300, 50, context_header=True) == "tokens-300-overlap-50-ctx"
    assert not has_context_header("tokens-150-overlap-30")
    assert has_context_header("tokens-300-overlap-50-ctx")
    with pytest.raises(ValueError, match="Not a chunker name"):
        has_context_header("words-300")


def test_the_header_names_the_page_version_and_section() -> None:
    header = contextual_header("CORS", "fastapi-docs", "0.162.0", "Middleware > CORS")

    assert header == "CORS (fastapi-docs 0.162.0) > Middleware > CORS"
    assert contextual_header("T", "s", "1", "") == "T (s 1)"
    assert model_input("text", header) == f"{header}\n\ntext"
    assert model_input("text", None) == "text"


def _ingest(session: Session, tenant: Tenant, chunker: TokenWindowChunker, embedder) -> None:
    request = ingest_request(slug="fastapi/cors", version="0.162.0", title="CORS", content=CONTENT)
    result = documents_service.ingest_document(session, tenant.id, request)
    document = documents_service.get_document(session, tenant.id, result.document_id)
    process_document(session, document, chunker, embedder)


def test_header_variants_embed_the_header_but_store_exact_chunk_text(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    embedder = RecordingEmbedder()
    chunker = TokenWindowChunker(WhitespaceTokenizer(), 300, 50, context_header=True)

    _ingest(db_session, tenant, chunker, embedder)

    chunks = db_session.scalars(
        select(DocumentChunk).where(DocumentChunk.tenant_id == tenant.id)
    ).all()
    assert {chunk.chunker for chunk in chunks} == {"tokens-300-overlap-50-ctx"}
    for chunk in chunks:
        assert chunk.text == CONTENT[chunk.char_start : chunk.char_end]
        assert "fastapi-docs" not in chunk.text
    assert all(text.startswith("CORS (fastapi-docs 0.162.0)") for text in embedder.inputs)


def test_search_reads_the_chosen_variant_and_reranks_what_was_embedded(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant()
    plain = TokenWindowChunker(WhitespaceTokenizer(), 300, 50)
    with_header = TokenWindowChunker(WhitespaceTokenizer(), 300, 50, context_header=True)
    embedder = RecordingEmbedder()
    _ingest(db_session, tenant, plain, embedder)
    request = ingest_request(slug="fastapi/cors", version="0.162.0", content=CONTENT)
    document_id = documents_service.ingest_document(db_session, tenant.id, request).document_id
    process_document(
        db_session, documents_service.get_document(db_session, tenant.id, document_id),
        with_header, embedder,
    )  # fmt: skip
    reranker = FakeReranker()
    options = SearchOptions(k=5, rerank=True, chunker="tokens-300-overlap-50-ctx")

    outcome = service.search(db_session, tenant.id, FakeEmbedder(), "max_age", options, reranker)

    assert outcome.chunker == "tokens-300-overlap-50-ctx"
    ((_, passages),) = reranker.calls
    assert passages
    assert all(text.startswith("CORS (fastapi-docs 0.162.0) > ") for text in passages)
    assert all("fastapi-docs" not in hit.text for hit in outcome.hits)
    plain_outcome = service.search(
        db_session, tenant.id, FakeEmbedder(), "max_age", SearchOptions(k=5)
    )
    assert plain_outcome.chunker == "tokens-300-overlap-50"
    assert {hit.chunk_id for hit in plain_outcome.hits}.isdisjoint(
        {hit.chunk_id for hit in outcome.hits}
    )
