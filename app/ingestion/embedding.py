"""The embedder contract. Implementations live in `local_models.py` (real) and the tests (fake)."""

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """Turns passages into unit-length vectors, one per input, in input order."""

    model_name: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
