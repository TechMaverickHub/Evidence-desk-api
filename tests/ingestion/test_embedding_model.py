"""Checks against the real model. Opt in with `uv run pytest -m model` (downloads ~130 MB once)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

import fastapi
import pytest

from app.core.config import get_settings
from app.ingestion.chunking import TokenWindowChunker

if TYPE_CHECKING:
    from app.ingestion.local_models import SentenceTransformerEmbedder

pytestmark = pytest.mark.model


# local_models is imported inside fixtures: importing torch takes ~40 s on this machine,
# and test collection would pay that cost even when these tests are deselected.
@pytest.fixture(scope="module")
def embedder() -> SentenceTransformerEmbedder:
    from app.ingestion.local_models import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder(get_settings().embedding_model_name, batch_size=8)


def test_vectors_are_384_dimensional_and_unit_length(embedder: SentenceTransformerEmbedder) -> None:
    vectors = embedder.embed_documents(["FastAPI dependencies", "PostgreSQL GIN index"])

    assert embedder.dimension == 384
    assert [len(vector) for vector in vectors] == [384, 384]
    for vector in vectors:
        assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-4)


def test_default_chunks_of_code_heavy_text_fit_the_model(
    embedder: SentenceTransformerEmbedder,
) -> None:
    # Python source is the worst case seen: word-based windows overflowed 512 tokens on it.
    from app.ingestion.local_models import HuggingFaceTokenizer

    source = (Path(fastapi.__file__).parent / "routing.py").read_text(encoding="utf-8")
    chunker = TokenWindowChunker(HuggingFaceTokenizer(get_settings().embedding_model_name))

    chunks = chunker.chunk(source)

    assert all(source[chunk.char_start : chunk.char_end] == chunk.text for chunk in chunks)
    assert max(embedder.count_tokens(chunk.text) for chunk in chunks) <= embedder.max_tokens
