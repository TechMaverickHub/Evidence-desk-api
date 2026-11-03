"""Test doubles that honour the same contracts as the real gateways (no model downloads)."""

import hashlib
import math
import re
from collections.abc import Sequence

_WORD = re.compile(r"\S+")


class WhitespaceTokenizer:
    """One token per whitespace-separated word, so tests can reason in words."""

    def token_offsets(self, text: str) -> list[tuple[int, int]]:
        return [match.span() for match in _WORD.finditer(text)]


class FakeEmbedder:
    """Deterministic unit-length vectors derived from a hash of each text."""

    model_name = "fake-embedder"
    dimension = 384

    def __init__(
        self, fail_on: str | None = None, query_vectors: dict[str, list[float]] | None = None
    ) -> None:
        # Raise when a text contains `fail_on`, to test mid-document failures.
        self._fail_on = fail_on
        # Lets search tests pin a query to a hand-made vector with known similarities.
        self._query_vectors = query_vectors or {}

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._query_vectors.get(text) or self._embed(text)

    def _embed(self, text: str) -> list[float]:
        if self._fail_on and self._fail_on in text:
            raise RuntimeError("fake embedder failure")
        seed = hashlib.sha256(text.encode()).digest()
        raw = [seed[i % len(seed)] - 127.5 + i % 7 for i in range(self.dimension)]
        norm = math.sqrt(sum(value * value for value in raw))
        return [value / norm for value in raw]


class FakeReranker:
    """Scores a passage by how many of the query's words it contains; records every call."""

    model_name = "fake-reranker"

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        # Pin exact scores per passage text when a test needs a known order.
        self._scores = scores or {}
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        words = set(query.lower().split())
        return [
            self._scores.get(text, float(len(words & set(text.lower().split()))))
            for text in passages
        ]
