"""The API's query embedder and reranker: each built once per process, shared by requests."""

from collections.abc import Callable
from functools import lru_cache

from app.core.config import get_settings
from app.ingestion.embedding import Embedder
from app.retrieval.reranking import Reranker


@lru_cache
def get_query_embedder() -> Embedder:
    """FastAPI dependency. Tests override it with a fake, so they never load torch."""
    # Imported here: importing torch takes tens of seconds, and only real searches need it.
    from app.ingestion.local_models import SentenceTransformerEmbedder

    settings = get_settings()
    return SentenceTransformerEmbedder(
        settings.embedding_model_name,
        settings.embedding_batch_size,
        query_instruction=settings.embedding_query_instruction,
    )


@lru_cache
def get_reranker() -> Reranker:
    """Built on first use: only `rerank: true` searches resolve this. Tests override it."""
    from app.ingestion.local_models import CrossEncoderReranker

    settings = get_settings()
    return CrossEncoderReranker(settings.reranker_model_name, settings.reranker_batch_size)


def get_reranker_provider() -> Callable[[], Reranker]:
    """FastAPI dependency. Returns the loader rather than the model, so a search that
    doesn't rerank never loads it (a plain Depends(get_reranker) would, on every request)."""
    return get_reranker
