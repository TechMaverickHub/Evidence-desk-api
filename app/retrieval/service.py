"""Search orchestration: embed the query, retrieve chunks, time each stage."""

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.chunking import chunker_name
from app.ingestion.embedding import Embedder
from app.retrieval import repository
from app.retrieval.repository import SearchHit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchOutcome:
    hits: list[SearchHit]
    chunker: str
    embedding_model: str
    # Stage name -> milliseconds; later tasks add stages (keyword, fusion, rerank).
    latency_ms: dict[str, float]


def search(
    session: Session,
    tenant_id: uuid.UUID,
    embedder: Embedder,
    query: str,
    k: int,
    source: str | None = None,
    version: str | None = None,
) -> SearchOutcome:
    settings = get_settings()
    chunker = chunker_name(settings.chunk_max_tokens, settings.chunk_overlap_tokens)
    started = time.perf_counter()

    query_vector = embedder.embed_query(query)
    embedded = time.perf_counter()
    hits = repository.dense_search(
        session,
        tenant_id,
        query_vector,
        chunker=chunker,
        # The embedder's own model name, so a query never meets another model's vectors.
        embedding_model=embedder.model_name,
        k=k,
        source=source,
        version=version,
    )
    retrieved = time.perf_counter()

    latency_ms = {
        "embed_query": _ms(started, embedded),
        "retrieve": _ms(embedded, retrieved),
        "total": _ms(started, retrieved),
    }
    # The query text is deliberately not logged.
    logger.info("search", extra={"fields": {"k": k, "results": len(hits), **latency_ms}})
    return SearchOutcome(hits, chunker, embedder.model_name, latency_ms)


def _ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 2)
