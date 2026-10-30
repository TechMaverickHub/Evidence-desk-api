"""Decide which labelled evidence a retrieved chunk counts as.

Labels are character spans in documents, not chunk ids, so they stay valid when the chunk
size or overlap changes. A chunk "matches" a span when both are in the same document version
and they overlap enough (see `overlaps`).
"""

from collections.abc import Sequence
from dataclasses import dataclass

# A chunk must cover at least this fraction of the shorter of (chunk, span). Recorded with
# every evaluation run, because results depend on it.
MIN_OVERLAP_FRACTION = 0.5


@dataclass(frozen=True)
class Span:
    """A character range in one document version: a labelled span or a retrieved chunk."""

    slug: str
    version: str
    char_start: int
    char_end: int

    @property
    def length(self) -> int:
        return self.char_end - self.char_start


@dataclass(frozen=True)
class EvidenceItem:
    """One labelled fact. Its spans are alternatives: matching any one satisfies it."""

    grade: int
    spans: tuple[Span, ...]


def overlaps(chunk: Span, span: Span, min_fraction: float = MIN_OVERLAP_FRACTION) -> bool:
    """True when the chunk covers at least `min_fraction` of the shorter of the two ranges.

    Using the shorter length means a short span must be mostly inside the chunk, while a
    span longer than the chunk counts when the chunk is mostly evidence. A chunk that only
    grazes a span at a window boundary does not count.
    """
    if (chunk.slug, chunk.version) != (span.slug, span.version):
        return False
    overlap = min(chunk.char_end, span.char_end) - max(chunk.char_start, span.char_start)
    return overlap > 0 and overlap >= min_fraction * min(chunk.length, span.length)


def match_evidence(
    ranked_chunks: Sequence[Span],
    evidence: Sequence[EvidenceItem],
    min_fraction: float = MIN_OVERLAP_FRACTION,
) -> list[frozenset[int]]:
    """For each ranked chunk, the indexes of the evidence items it matches (rank order kept)."""
    return [
        frozenset(
            index
            for index, item in enumerate(evidence)
            if any(overlaps(chunk, span, min_fraction) for span in item.spans)
        )
        for chunk in ranked_chunks
    ]
