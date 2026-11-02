"""Database reads for evaluation runs: what a tenant has ingested, and the server version."""

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from app.documents.models import Document, DocumentChunk, DocumentStatus


@dataclass(frozen=True)
class StoredDocument:
    slug: str
    version: str
    content_hash: str
    status: DocumentStatus
    # Chunks of the run's chunker and embedding model only; other strategies don't count.
    chunk_count: int


def list_stored_documents(
    session: Session, tenant_id: uuid.UUID, *, chunker: str, embedding_model: str
) -> list[StoredDocument]:
    chunk_join = and_(
        DocumentChunk.document_id == Document.id,
        DocumentChunk.chunker == chunker,
        DocumentChunk.embedding_model == embedding_model,
    )
    query = (
        select(
            Document.slug,
            Document.version,
            Document.content_hash,
            Document.status,
            func.count(DocumentChunk.id),
        )
        .outerjoin(DocumentChunk, chunk_join)
        .where(Document.tenant_id == tenant_id)
        .group_by(Document.id)
    )
    return [StoredDocument(*row) for row in session.execute(query)]


def postgres_version(session: Session) -> str:
    return session.scalar(text("SHOW server_version"))
