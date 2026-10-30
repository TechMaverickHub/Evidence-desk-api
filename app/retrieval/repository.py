"""Vector search over chunks. Every query is scoped by tenant, chunker and embedding model."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.models import Document, DocumentChunk


@dataclass(frozen=True)
class SearchHit:
    chunk_id: uuid.UUID
    text: str
    char_start: int
    char_end: int
    heading_path: str
    document_id: uuid.UUID
    source: str
    slug: str
    version: str
    title: str
    score: float


def dense_search(
    session: Session,
    tenant_id: uuid.UUID,
    query_vector: Sequence[float],
    *,
    chunker: str,
    embedding_model: str,
    k: int,
    source: str | None = None,
    version: str | None = None,
) -> list[SearchHit]:
    """Exact k-nearest-neighbour search by cosine distance (no approximate index).

    Exact search keeps evaluation free of ANN recall error, and an index scanned before the
    tenant filter could return fewer than k rows for a small tenant. See task 004.
    """
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    query = (
        # Explicit columns: never load document content or chunk vectors into the result.
        select(
            DocumentChunk.id,
            DocumentChunk.text,
            DocumentChunk.char_start,
            DocumentChunk.char_end,
            DocumentChunk.heading_path,
            Document.id,
            Document.source,
            Document.slug,
            Document.version,
            Document.title,
            distance,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.chunker == chunker,
            DocumentChunk.embedding_model == embedding_model,
        )
        # Chunk id breaks ties so the same query always returns the same order.
        .order_by(distance, DocumentChunk.id)
        .limit(k)
    )
    if source is not None:
        query = query.where(Document.source == source)
    if version is not None:
        query = query.where(Document.version == version)

    # Vectors are unit length, so 1 - cosine distance is the cosine similarity.
    return [SearchHit(*row[:-1], score=1.0 - row[-1]) for row in session.execute(query)]
