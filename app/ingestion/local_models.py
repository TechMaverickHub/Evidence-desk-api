"""Gateways to the local Hugging Face models: the embedding model and its tokenizer.

Kept apart from the rest of `app.ingestion` because importing sentence-transformers/torch
takes tens of seconds; only the worker and the corpus loader import this module.
"""

from collections.abc import Sequence

from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer


class SentenceTransformerEmbedder:
    """Local CPU embedding model (implements `Embedder`). Build one per process: loading is slow."""

    def __init__(self, model_name: str, batch_size: int) -> None:
        # trust_remote_code=False: never execute Python shipped inside a model repository.
        self._model = SentenceTransformer(model_name, device="cpu", trust_remote_code=False)
        self._batch_size = batch_size
        self.model_name = model_name
        self.dimension = self._model.get_embedding_dimension()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        # Normalised vectors make cosine similarity equal to the dot product.
        vectors = self._model.encode_document(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def count_tokens(self, text: str) -> int:
        """Token count as the model sees it, including special tokens."""
        return len(self._model.tokenizer(text)["input_ids"])

    @property
    def max_tokens(self) -> int:
        return self._model.max_seq_length


class HuggingFaceTokenizer:
    """The embedding model's tokenizer (implements chunking's `Tokenizer`), without weights."""

    def __init__(self, model_name: str) -> None:
        # A "fast" tokenizer is required: only those report character offsets.
        self._tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        encoding = self._tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            # Whole sections are tokenized at once; silence the "longer than 512" warning,
            # which is expected here because the chunker splits them afterwards.
            verbose=False,
        )
        return [tuple(offset) for offset in encoding["offset_mapping"]]
