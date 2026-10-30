"""Benchmark dataset: a human-written YAML source is built into a byte-stable JSONL file.

Authors write short quotes; the builder turns each quote into the exact character span of
its paragraph in the corpus, assigns dev/test splits, and refuses to build anything
ambiguous. Runs consume the JSONL, identified by its SHA-256.
"""

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.evaluation.relevance import EvidenceItem, Span
from app.ingestion.cli import CorpusError, read_manifest

FORMAT = "evidencedesk-dataset/1"
DEFAULT_DEV_FRACTION = 0.6

QueryType = Literal[
    "factual",
    "multi_passage",
    "exact_identifier",
    "paraphrase",
    "version_specific",
    "ambiguous",
    "unanswerable",
]


class DatasetError(Exception):
    """Every problem found in a dataset source, reported together."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("\n".join(f"- {problem}" for problem in self.problems))


# --- Source format (written by people) -------------------------------------------------


class SourceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    version: str
    quote: str = Field(min_length=1)
    # Label only the quoted text instead of the whole paragraph around it.
    quote_only: bool = False


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade: int = Field(ge=1, le=3, description="1 related, 2 partially answers, 3 answers")
    spans: list[SourceSpan] = Field(min_length=1)


class SourceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^q-\d{4}$")
    query_type: QueryType
    question: str = Field(min_length=1)
    reference_answer: str | None = None
    reviewed: bool = False
    evidence: list[SourceEvidence] = Field(default_factory=list)


class SourceDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[SourceQuestion] = Field(min_length=1)


# --- Built format (consumed by evaluation runs) ----------------------------------------


class BuiltSpan(BaseModel):
    slug: str
    version: str
    char_start: int
    char_end: int
    quote: str


class BuiltEvidence(BaseModel):
    grade: int
    spans: list[BuiltSpan]


class BuiltQuestion(BaseModel):
    id: str
    split: Literal["dev", "test"]
    query_type: QueryType
    question: str
    reference_answer: str | None
    answerable: bool
    evidence: list[BuiltEvidence]

    def evidence_items(self) -> list[EvidenceItem]:
        """The labels in the form `relevance.match_evidence` expects."""
        return [
            EvidenceItem(
                item.grade,
                tuple(Span(s.slug, s.version, s.char_start, s.char_end) for s in item.spans),
            )
            for item in self.evidence
        ]


class DatasetHeader(BaseModel):
    format: str = FORMAT
    name: str
    seed: str
    dev_fraction: float
    questions: int


@dataclass(frozen=True)
class Dataset:
    header: DatasetHeader
    questions: list[BuiltQuestion]
    sha256: str


# --- Building ---------------------------------------------------------------------------


def build_dataset(
    source_path: Path,
    manifest_path: Path,
    name: str,
    seed: str,
    dev_fraction: float = DEFAULT_DEV_FRACTION,
) -> Dataset:
    source = _read_source(source_path)
    documents = _read_corpus(manifest_path)
    problems = _check_questions(source.questions)
    built = []
    for question in source.questions:
        evidence = _resolve_evidence(question, documents, problems)
        built.append(
            BuiltQuestion(
                id=question.id,
                split=assign_split(question, seed, dev_fraction),
                query_type=question.query_type,
                question=question.question,
                reference_answer=question.reference_answer,
                answerable=bool(question.evidence),
                evidence=evidence,
            )
        )
    if problems:
        raise DatasetError(problems)
    header = DatasetHeader(name=name, seed=seed, dev_fraction=dev_fraction, questions=len(built))
    return Dataset(header, built, sha256=hashlib.sha256(_serialise(header, built)).hexdigest())


def assign_split(question: SourceQuestion, seed: str, dev_fraction: float) -> str:
    """Deterministic split by source page, so questions about one page (in any version)
    never land on both sides; unanswerable questions are grouped by their own id."""
    group_key = question.evidence[0].spans[0].slug if question.evidence else question.id
    digest = hashlib.sha256(f"{seed}:{group_key}".encode()).hexdigest()
    return "dev" if int(digest[:8], 16) / 0x1_0000_0000 < dev_fraction else "test"


def paragraph_span(content: str, start: int, end: int) -> tuple[int, int]:
    """Expand [start, end) to the enclosing paragraph (text between blank lines)."""
    previous_break = content.rfind("\n\n", 0, start)
    paragraph_start = 0 if previous_break == -1 else previous_break + 2
    next_break = content.find("\n\n", end)
    paragraph_end = len(content) if next_break == -1 else next_break
    return paragraph_start, len(content[:paragraph_end].rstrip())


def _read_source(path: Path) -> SourceDataset:
    try:
        return SourceDataset.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise DatasetError([f"Invalid source {path}: {exc}"]) from exc


def _read_corpus(manifest_path: Path) -> dict[tuple[str, str], str]:
    # Same reader as the corpus loader, so offsets refer to exactly the ingested text.
    try:
        requests = read_manifest(manifest_path)
    except CorpusError as exc:
        raise DatasetError([str(exc)]) from exc
    return {(request.slug, request.version): request.content for request in requests}


def _check_questions(questions: Sequence[SourceQuestion]) -> list[str]:
    problems = [
        f"duplicate id {question_id}"
        for question_id, count in Counter(question.id for question in questions).items()
        if count > 1
    ]
    for question in questions:
        if not question.reviewed:
            problems.append(f"{question.id}: not reviewed")
        is_unanswerable = question.query_type == "unanswerable"
        if is_unanswerable == bool(question.evidence):
            problems.append(
                f"{question.id}: unanswerable questions, and only those, have no evidence"
            )
    return problems


def _resolve_evidence(
    question: SourceQuestion, documents: dict[tuple[str, str], str], problems: list[str]
) -> list[BuiltEvidence]:
    resolved = []
    for item in question.evidence:
        spans = [_resolve_span(question.id, span, documents, problems) for span in item.spans]
        resolved.append(BuiltEvidence(grade=item.grade, spans=[s for s in spans if s]))
    return resolved


def _resolve_span(
    question_id: str,
    span: SourceSpan,
    documents: dict[tuple[str, str], str],
    problems: list[str],
) -> BuiltSpan | None:
    content = documents.get((span.slug, span.version))
    if content is None:
        problems.append(f"{question_id}: no document {span.slug}@{span.version} in the manifest")
        return None
    # Literal matching (no regex), and it must be unique, so a label can't land on the
    # wrong occurrence; a longer quote fixes a non-unique one.
    occurrences = content.count(span.quote)
    if occurrences != 1:
        problems.append(
            f"{question_id}: quote found {occurrences} times in {span.slug}@{span.version}: "
            f"{span.quote!r}"
        )
        return None
    start = content.index(span.quote)
    end = start + len(span.quote)
    if not span.quote_only:
        start, end = paragraph_span(content, start, end)
    return BuiltSpan(
        slug=span.slug, version=span.version, char_start=start, char_end=end, quote=span.quote
    )


# --- Files ------------------------------------------------------------------------------


def write_dataset(dataset: Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_serialise(dataset.header, dataset.questions))


def load_dataset(path: Path) -> Dataset:
    raw = path.read_bytes()
    header_line, *question_lines = raw.decode("utf-8").splitlines()
    header = DatasetHeader.model_validate_json(header_line)
    if header.format != FORMAT:
        raise DatasetError([f"{path}: unsupported format {header.format!r}"])
    questions = [BuiltQuestion.model_validate_json(line) for line in question_lines]
    return Dataset(header, questions, sha256=hashlib.sha256(raw).hexdigest())


def _serialise(header: DatasetHeader, questions: Sequence[BuiltQuestion]) -> bytes:
    # First line is the header; one question per line; "\n" endings on every OS, so the
    # same build always has the same SHA-256.
    lines = [header.model_dump_json()] + [question.model_dump_json() for question in questions]
    return ("\n".join(lines) + "\n").encode("utf-8")
