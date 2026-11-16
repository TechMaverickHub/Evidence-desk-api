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


# Chunker variants whose model input carries a contextual header (task 010).
CONTEXT_SUFFIX = "-ctx"
_CHUNKER_NAME = re.compile(r"^tokens-(\d+)-overlap-(\d+)(-ctx)?$")


def chunker_name(max_tokens: int, overlap_tokens: int, context_header: bool = False) -> str:
    """Stored on every chunk; search uses it to read only chunks of one strategy."""
    suffix = CONTEXT_SUFFIX if context_header else ""
    return f"tokens-{max_tokens}-overlap-{overlap_tokens}{suffix}"


def has_context_header(name: str) -> bool:
    """Whether a chunker's chunks were embedded with a contextual header. The name alone
    decides it, so search can give the reranker the same input the embedder saw."""
    match = _CHUNKER_NAME.match(name)
    if match is None:
        raise ValueError(f"Not a chunker name: {name!r}")
    return match.group(3) is not None


def contextual_header(title: str, source: str, version: str, heading_path: str) -> str:
    """Where a chunk comes from: document title, source and version, then its heading path.
    Chunks are embedded without their surroundings, so this restores what the reader of a
    chunk would otherwise not know (which page, which version, which section)."""
    header = f"{title} ({source} {version})"
    return f"{header} > {heading_path}" if heading_path else header


def model_input(text: str, header: str | None) -> str:
    """The text a model sees for a chunk. The stored chunk text never includes the header,
    so character offsets (and the evidence labels built on them) stay exact."""
    return f"{header}\n\n{text}" if header else text


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
    # Embed each chunk with a contextual header (see `contextual_header`); windows are the same.
    context_header: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError("overlap_tokens must be >= 0 and smaller than max_tokens")

    @property
    def name(self) -> str:
        return chunker_name(self.max_tokens, self.overlap_tokens, self.context_header)

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
