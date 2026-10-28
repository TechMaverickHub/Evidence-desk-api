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

    def __init__(self, fail_on: str | None = None) -> None:
        # Raise when a text contains `fail_on`, to test mid-document failures.
        self._fail_on = fail_on

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        if self._fail_on and self._fail_on in text:
            raise RuntimeError("fake embedder failure")
        seed = hashlib.sha256(text.encode()).digest()
        raw = [seed[i % len(seed)] - 127.5 + i % 7 for i in range(self.dimension)]
        norm = math.sqrt(sum(value * value for value in raw))
        return [value / norm for value in raw]
