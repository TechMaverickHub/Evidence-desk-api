"""Offsets and boundaries: every later evaluation depends on these being exact."""

import pytest

from app.ingestion.chunking import TokenWindowChunker
from tests.fakes import WhitespaceTokenizer

DOC = """Intro text before any heading.

# Tutorial

Install FastAPI with pip.

## Dependencies

Use Depends to declare a dependency.

```python
# this is a comment, not a heading
def get_db():
    ...
```

More text after the code block.

## Empty section

# Reference

Path operations are described here.
"""


def _chunker(max_tokens: int = 300, overlap_tokens: int = 50) -> TokenWindowChunker:
    # The whitespace tokenizer makes one token per word, so sizes below are word counts.
    return TokenWindowChunker(WhitespaceTokenizer(), max_tokens, overlap_tokens)


def _words(count: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(count))


def test_every_chunk_is_an_exact_slice_of_the_content() -> None:
    long_doc = DOC + "\n## Long\n\n" + _words(700) + "\n"

    chunks = _chunker(50, 10).chunk(long_doc)

    assert chunks
    for chunk in chunks:
        assert long_doc[chunk.char_start : chunk.char_end] == chunk.text


def test_sections_follow_headings_and_ignore_code_comments() -> None:
    chunks = _chunker().chunk(DOC)

    assert [chunk.heading_path for chunk in chunks] == [
        "",
        "Tutorial",
        "Tutorial > Dependencies",
        "Reference",
    ]
    assert "# this is a comment" in chunks[2].text
    assert chunks[1].text.startswith("# Tutorial")


def test_heading_only_section_produces_no_chunk() -> None:
    chunks = _chunker().chunk(DOC)

    assert all("Empty section" not in chunk.heading_path for chunk in chunks)


def test_windows_respect_size_and_overlap() -> None:
    content = _words(260)

    chunks = _chunker(100, 20).chunk(content)

    word_lists = [chunk.text.split() for chunk in chunks]
    assert [len(words) for words in word_lists] == [100, 100, 100]
    for previous, current in zip(word_lists, word_lists[1:], strict=False):
        assert previous[-20:] == current[:20]
    assert word_lists[-1][-1] == "w259"


def test_ordinals_are_sequential_across_sections() -> None:
    chunks = _chunker(3, 1).chunk(DOC)

    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


def test_document_of_only_headings_yields_no_chunks() -> None:
    assert _chunker().chunk("# One\n\n## Two\n") == []


def test_chunker_name_records_its_parameters() -> None:
    assert _chunker().name == "tokens-300-overlap-50"


@pytest.mark.parametrize(("max_tokens", "overlap_tokens"), [(10, 10), (10, -1)])
def test_invalid_window_settings_are_rejected(max_tokens: int, overlap_tokens: int) -> None:
    with pytest.raises(ValueError, match="overlap_tokens"):
        _chunker(max_tokens, overlap_tokens)
