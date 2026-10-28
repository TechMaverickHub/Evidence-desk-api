"""Split a Markdown document into overlapping token windows with exact character offsets.

Every chunk's text is `content[char_start:char_end]`. Evidence labels in the benchmark are
character spans, so offsets must never drift.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
_FENCE = re.compile(r"^[ \t]*(```|~~~)")
_WORD = re.compile(r"\S+")


class Tokenizer(Protocol):
    """Returns the (start, end) character offsets of each token in `text`, in order."""

    def token_offsets(self, text: str) -> list[tuple[int, int]]: ...


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    char_start: int
    char_end: int
    heading_path: str


@dataclass(frozen=True)
class _Section:
    char_start: int  # start of the heading line (the heading text is part of the chunk)
    body_start: int  # first character after the heading line
    char_end: int
    heading_path: str


@dataclass(frozen=True)
class TokenWindowChunker:
    """Heading-aware sliding windows of `max_tokens` model tokens, overlapping by `overlap_tokens`.

    Windows are measured with the embedding model's own tokenizer because word counts are
    unreliable: 250 words of Python measured ~1,000 tokens, far over bge-small's 512 limit.
    300 tokens leaves headroom for special tokens and, in task 008, for the query that a
    cross-encoder reads together with the passage.
    """

    tokenizer: Tokenizer
    max_tokens: int = 300
    overlap_tokens: int = 50

    def __post_init__(self) -> None:
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError("overlap_tokens must be >= 0 and smaller than max_tokens")

    @property
    def name(self) -> str:
        return f"tokens-{self.max_tokens}-overlap-{self.overlap_tokens}"

    def chunk(self, content: str) -> list[Chunk]:
        chunks: list[Chunk] = []
        for section in _split_sections(content):
            for start, end in self._windows(content, section):
                chunks.append(
                    Chunk(len(chunks), content[start:end], start, end, section.heading_path)
                )
        return chunks

    def _windows(self, content: str, section: _Section) -> Iterator[tuple[int, int]]:
        # A section with no words after its heading line has nothing worth indexing.
        if not _WORD.search(content, section.body_start, section.char_end):
            return
        section_text = content[section.char_start : section.char_end]
        tokens = self.tokenizer.token_offsets(section_text)
        step = self.max_tokens - self.overlap_tokens
        for first in range(0, len(tokens), step):
            window = tokens[first : first + self.max_tokens]
            # Token offsets are relative to the section; shift them back into the document.
            yield section.char_start + window[0][0], section.char_start + window[-1][1]
            if first + self.max_tokens >= len(tokens):
                return


def _split_sections(content: str) -> Iterator[_Section]:
    """Yield one section per Markdown heading, plus any text before the first heading."""
    headings: list[str] = []  # current heading titles, indexed by level - 1
    section_start, body_start, heading_path = 0, 0, ""
    in_fence = False
    offset = 0
    for line in content.splitlines(keepends=True):
        line_start, offset = offset, offset + len(line)
        if _FENCE.match(line):
            in_fence = not in_fence
        # A "#" inside a code block is a comment, not a heading.
        match = None if in_fence else _HEADING.match(line.rstrip("\r\n"))
        if match is None:
            continue
        yield _Section(section_start, body_start, line_start, heading_path)
        level = len(match.group(1))
        headings = headings[: level - 1] + [match.group(2)]
        section_start, body_start, heading_path = line_start, offset, " > ".join(headings)
    yield _Section(section_start, body_start, len(content), heading_path)
