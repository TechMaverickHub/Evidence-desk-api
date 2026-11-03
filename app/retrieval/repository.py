"""Chunk retrieval queries: dense (vector) and keyword (full-text).

Both are scoped identically by tenant, chunker, embedding model and optional filters, so
the two retrievers always search the same set of chunks.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, Text, cast, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.orm import Session

from app.documents.models import TEXT_SEARCH_CONFIG, Document, DocumentChunk


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
    # Meaning depends on the retriever: cosine similarity, ts_rank_cd, or RRF score.
    score: float
    # 1-based position in each retriever's own ranking; None when it didn't return the chunk.
    dense_rank: int | None = None
    keyword_rank: int | None = None


@dataclass(frozen=True)
class SearchScope:
    tenant_id: uuid.UUID
    chunker: str
    embedding_model: str
    source: str | None = None
    version: str | None = None


def dense_search(
    session: Session, scope: SearchScope, query_vector: Sequence[float], k: int
) -> list[SearchHit]:
    """Exact k-nearest-neighbour search by cosine distance (no approximate index).

    Exact search keeps evaluation free of ANN recall error, and an index scanned before the
    tenant filter could return fewer than k rows for a small tenant. See task 004.
    """
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    query = (
        _scoped(select(*_HIT_COLUMNS, distance), scope)
        # Chunk id breaks ties so the same query always returns the same order.
        .order_by(distance, DocumentChunk.id)
        .limit(k)
    )
    # Vectors are unit length, so 1 - cosine distance is the cosine similarity.
    return [
        SearchHit(*row[:-1], score=1.0 - row[-1], dense_rank=rank)
        for rank, row in enumerate(session.execute(query), start=1)
    ]


def keyword_search(
    session: Session, scope: SearchScope, query_text: str, k: int
) -> list[SearchHit]:
    """Full-text search with the query's terms ORed, ranked by ts_rank_cd.

    ORed because plainto_tsquery ANDs every term, and a whole question rarely has all its
    words in one chunk (0 matches for typical benchmark questions; task 007).
    """
    or_query = any_term_query(session, query_text)
    if or_query is None:
        return []
    tsquery = cast(or_query, TSQUERY)
    rank = func.ts_rank_cd(DocumentChunk.tsv, tsquery)
    query = (
        _scoped(select(*_HIT_COLUMNS, rank), scope)
        .where(DocumentChunk.tsv.op("@@")(tsquery))
        .order_by(rank.desc(), DocumentChunk.id)
        .limit(k)
    )
    return [
        SearchHit(*row[:-1], score=row[-1], keyword_rank=position)
        for position, row in enumerate(session.execute(query), start=1)
    ]


def any_term_query(session: Session, query_text: str) -> str | None:
    """The query as an OR of its lexemes, or None when it has none (only stop words).

    The rewrite works on plainto_tsquery's own output: the user text is a bound parameter,
    and ' & ' only ever appears between quoted lexemes, never inside one.
    """
    and_query = func.plainto_tsquery(TEXT_SEARCH_CONFIG, query_text)
    rewritten = session.scalar(select(func.replace(cast(and_query, Text), " & ", " | ")))
    return rewritten or None


def _scoped(query: Select, scope: SearchScope) -> Select:
    query = query.join(Document, Document.id == DocumentChunk.document_id).where(
        DocumentChunk.tenant_id == scope.tenant_id,
        DocumentChunk.chunker == scope.chunker,
        DocumentChunk.embedding_model == scope.embedding_model,
    )
    if scope.source is not None:
        query = query.where(Document.source == scope.source)
    if scope.version is not None:
        query = query.where(Document.version == scope.version)
    return query


# Explicit columns: never load document content, chunk vectors or tsv into a result.
_HIT_COLUMNS = (
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
)
