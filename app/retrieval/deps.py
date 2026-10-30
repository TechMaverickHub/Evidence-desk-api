"""The API's query embedder: built once per process and shared by all requests."""

from functools import lru_cache

from app.core.config import get_settings
from app.ingestion.embedding import Embedder


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
