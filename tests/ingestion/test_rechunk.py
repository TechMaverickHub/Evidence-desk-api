"""rechunk: adds a chunker variant alongside existing chunks, resumably, in one tenant."""

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.documents.models import DocumentChunk
from app.ingestion.chunking import TokenWindowChunker
from app.ingestion.cli import rechunk_documents
from app.retrieval.service import configured_chunker
from tests.fakes import FakeEmbedder, WhitespaceTokenizer

VARIANT = TokenWindowChunker(WhitespaceTokenizer(), 150, 30)


def _count(session: Session, tenant: Tenant, chunker: str) -> int:
    return session.scalar(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.tenant_id == tenant.id, DocumentChunk.chunker == chunker
        )
    )


def test_a_variant_is_added_without_touching_existing_chunks(
    db_session: Session, make_tenant: Callable[..., Tenant], load_fixture_corpus: Callable
) -> None:
    tenant = make_tenant()
    load_fixture_corpus(tenant)
    before = _count(db_session, tenant, configured_chunker())

    result = rechunk_documents(db_session, tenant.id, VARIANT, FakeEmbedder())

    assert (result.processed, result.failed) == (2, [])
    assert _count(db_session, tenant, VARIANT.name) > 0
    assert _count(db_session, tenant, configured_chunker()) == before


def test_a_second_run_does_nothing_and_other_tenants_are_untouched(
    db_session: Session, make_tenant: Callable[..., Tenant], load_fixture_corpus: Callable
) -> None:
    tenant, other = make_tenant(), make_tenant()
    load_fixture_corpus(tenant)
    load_fixture_corpus(other)
    rechunk_documents(db_session, tenant.id, VARIANT, FakeEmbedder())
    first = _count(db_session, tenant, VARIANT.name)

    again = rechunk_documents(db_session, tenant.id, VARIANT, FakeEmbedder())

    assert again.processed == 0
    assert _count(db_session, tenant, VARIANT.name) == first
    assert _count(db_session, other, VARIANT.name) == 0
