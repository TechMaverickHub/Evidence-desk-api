"""Evaluation fixtures: the mini benchmark and the fixture corpus texts.

The fixture corpus loaded into a tenant (`load_fixture_corpus`) is in tests/conftest.py,
because ingestion tests use it too.
"""

from pathlib import Path

import pytest

from app.evaluation.dataset import Dataset, build_dataset, read_corpus_texts

FIXTURES = Path(__file__).parents[1] / "fixtures"
MANIFEST = FIXTURES / "corpus" / "manifest.yaml"
MINI = FIXTURES / "datasets" / "mini.yaml"


@pytest.fixture
def mini_dataset() -> Dataset:
    return build_dataset(MINI, MANIFEST, "mini", "s")


@pytest.fixture
def corpus_texts() -> dict[tuple[str, str], str]:
    return read_corpus_texts(MANIFEST)
