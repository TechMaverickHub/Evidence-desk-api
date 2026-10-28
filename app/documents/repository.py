"""Database queries for documents and chunks. Every query is scoped by tenant_id."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.documents.models import Document, DocumentChunk, DocumentStatus


def get_document_in_tenant(
    session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> Document | None:
    return session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )


def get_document_by_slug(
    session: Session, tenant_id: uuid.UUID, slug: str, version: str
) -> Document | None:
    return session.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id, Document.slug == slug, Document.version == version
        )
    )


def list_documents(
    session: Session,
    tenant_id: uuid.UUID,
    source: str | None,
    version: str | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Document], int]:
    """Return one page of documents and the total count matching the filters."""
    conditions = [Document.tenant_id == tenant_id]
    if source is not None:
        conditions.append(Document.source == source)
    if version is not None:
        conditions.append(Document.version == version)

    total = session.scalar(select(func.count()).select_from(Document).where(*conditions)) or 0
    page = session.scalars(
        select(Document)
        .where(*conditions)
        .order_by(Document.created_at, Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return page, total


def count_chunks(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> int:
    query = select(func.count()).where(
        DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == document_id
    )
    return session.scalar(query) or 0


def add_document(
    session: Session,
    tenant_id: uuid.UUID,
    fields: dict[str, Any],
    content_hash: str,
) -> Document:
    document = Document(
        tenant_id=tenant_id, content_hash=content_hash, status=DocumentStatus.PENDING, **fields
    )
    session.add(document)
    session.flush()
    return document


def replace_chunks(
    session: Session, document: Document, chunker: str, chunks: Sequence[DocumentChunk]
) -> None:
    """Swap one chunker's chunks for a document, so re-processing never duplicates them."""
    session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.tenant_id == document.tenant_id,
            DocumentChunk.document_id == document.id,
            DocumentChunk.chunker == chunker,
        )
    )
    session.add_all(chunks)
    session.flush()
