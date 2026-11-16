"""Load a versioned corpus from a manifest into one tenant.

Usage:
    uv run python -m app.ingestion.cli load-corpus --tenant acme
        --manifest corpus/manifest.yaml [--process]
    uv run python -m app.ingestion.cli rechunk --tenant acme --max-tokens 150
        --overlap-tokens 30 [--context-header]

Manifest format (paths are relative to the manifest file):

    documents:
      - path: fastapi/dependencies.md
        source: fastapi-docs
        slug: fastapi/dependencies
        version: "0.115"
        title: Dependencies
        license: MIT
"""

import argparse
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.auth.repository import get_tenant_by_name
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import ConflictError
from app.documents import repository as documents_repository
from app.documents import service as documents_service
from app.documents.schemas import IngestDocumentRequest
from app.documents.service import IngestResult
from app.ingestion.chunking import TokenWindowChunker
from app.ingestion.embedding import Embedder
from app.ingestion.pipeline import IngestionError, process_document


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    source: str
    slug: str
    version: str
    title: str
    license: str


class Manifest(BaseModel):
    documents: list[ManifestEntry] = Field(min_length=1)


class CorpusError(Exception):
    """A manifest or corpus file problem, reported to the operator without a traceback."""


def read_manifest(manifest_path: Path) -> list[IngestDocumentRequest]:
    """Parse the manifest and read every file into a validated ingest request."""
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest = Manifest.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CorpusError(f"Invalid manifest {manifest_path}: {exc}") from exc
    return [_to_request(manifest_path.parent, entry) for entry in manifest.documents]


def load_corpus(tenant_name: str, manifest_path: Path) -> tuple[int, int]:
    """Ingest every manifest entry. Returns (queued, unchanged) counts."""
    requests = read_manifest(manifest_path)
    with get_sessionmaker()() as session:
        tenant = get_tenant_by_name(session, tenant_name)
        if tenant is None:
            raise CorpusError(f"Unknown tenant '{tenant_name}'")
        results = [_ingest(session, tenant.id, request) for request in requests]
    queued = sum(result.is_new_job for result in results)
    return queued, len(results) - queued


def _to_request(base_dir: Path, entry: ManifestEntry) -> IngestDocumentRequest:
    try:
        content = (base_dir / entry.path).read_text(encoding="utf-8")
        return IngestDocumentRequest(
            source=entry.source,
            slug=entry.slug,
            version=entry.version,
            title=entry.title,
            content=content,
            metadata={"license": entry.license, "path": entry.path},
        )
    except (OSError, ValidationError) as exc:
        raise CorpusError(f"Cannot load {entry.path}: {exc}") from exc


def _ingest(session: Session, tenant_id: uuid.UUID, request: IngestDocumentRequest) -> IngestResult:
    try:
        return documents_service.ingest_document(session, tenant_id, request)
    except ConflictError as exc:
        raise CorpusError(f"{request.slug}@{request.version}: {exc.message}") from exc


def _process_queue() -> None:
    # Imported here: building the real handlers loads torch, which takes tens of seconds.
    from app.worker import build_default_handlers, run_worker

    run_worker(build_default_handlers(), get_settings().worker_poll_seconds, once=True)


@dataclass(frozen=True)
class RechunkResult:
    processed: int
    failed: list[str]


def rechunk_documents(
    session: Session, tenant_id: uuid.UUID, chunker: TokenWindowChunker, embedder: Embedder
) -> RechunkResult:
    """Chunk and embed every ingested document that lacks this chunker variant.

    The new chunks sit next to existing ones (chunks are keyed by chunker name), so variants
    can be compared on identical documents. Commits per document, so an interrupted run
    resumes where it stopped.
    """
    documents = documents_repository.list_documents_missing_chunker(
        session, tenant_id, chunker.name, embedder.model_name
    )
    processed, failed = 0, []
    for document in documents:
        label = f"{document.slug}@{document.version}"
        try:
            process_document(session, document, chunker, embedder)
        except IngestionError as exc:
            session.rollback()
            failed.append(f"{label}: {exc}")
            continue
        session.commit()
        processed += 1
    return RechunkResult(processed, failed)


def _rechunk(args: argparse.Namespace) -> int:
    # Imported here: loading the model and tokenizer imports torch (tens of seconds).
    from app.ingestion.local_models import HuggingFaceTokenizer, SentenceTransformerEmbedder

    settings = get_settings()
    chunker = TokenWindowChunker(
        HuggingFaceTokenizer(settings.embedding_model_name),
        args.max_tokens,
        args.overlap_tokens,
        args.context_header,
    )
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model_name, settings.embedding_batch_size
    )
    with get_sessionmaker()() as session:
        tenant = get_tenant_by_name(session, args.tenant)
        if tenant is None:
            print(f"Unknown tenant '{args.tenant}'", file=sys.stderr)
            return 1
        result = rechunk_documents(session, tenant.id, chunker, embedder)
    print(f"{chunker.name}: {result.processed} document(s) chunked, {len(result.failed)} failed.")
    for failure in result.failed:
        print(f"  {failure}", file=sys.stderr)
    return 0


def _load(args: argparse.Namespace) -> int:
    try:
        queued, unchanged = load_corpus(args.tenant, args.manifest)
    except CorpusError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Queued {queued} document(s); {unchanged} already present.")
    if args.process:
        _process_queue()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingestion.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load-corpus", help="Ingest every document in a manifest")
    load.add_argument("--tenant", required=True, help="Tenant name")
    load.add_argument("--manifest", required=True, type=Path, help="Path to manifest.yaml")
    load.add_argument("--process", action="store_true", help="Run the worker once afterwards")
    rechunk = commands.add_parser(
        "rechunk", help="Add a chunker variant to every ingested document (task 010)"
    )
    rechunk.add_argument("--tenant", required=True, help="Tenant name")
    rechunk.add_argument("--max-tokens", required=True, type=int)
    rechunk.add_argument("--overlap-tokens", required=True, type=int)
    rechunk.add_argument("--context-header", action="store_true", help="Embed with a header")
    args = parser.parse_args(argv)
    return _rechunk(args) if args.command == "rechunk" else _load(args)


if __name__ == "__main__":
    sys.exit(main())
