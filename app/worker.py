"""Background worker: claim a job, run its handler, record the outcome.

Usage: uv run python -m app.worker [--once]
"""

import argparse
import logging
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging
from app.evaluation.service import QueryEmbedderFactory, run_evaluation_job
from app.ingestion.chunking import TokenWindowChunker
from app.ingestion.embedding import Embedder
from app.ingestion.pipeline import mark_document_failed, run_ingest_job
from app.jobs import repository as jobs_repository
from app.jobs.models import Job, JobKind, JobStatus
from app.retrieval.deps import get_reranker
from app.retrieval.reranking import Reranker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobHandler:
    # Does the work. It may commit it; otherwise the worker's success commit includes it.
    run: Callable[[Session, Job], None]
    # Runs after the work was rolled back, to record domain-level failure state.
    on_failure: Callable[[Session, Job], None]


def build_handlers(
    chunker: TokenWindowChunker,
    embedder: Embedder,
    query_embedder_for: QueryEmbedderFactory | None = None,
    load_reranker: Callable[[], Reranker] | None = None,
) -> dict[str, JobHandler]:
    """One entry per job kind; new kinds are added here.

    `query_embedder_for` gives evaluation runs an embedder with their query instruction.
    Without it (tests with a fake embedder) the passage embedder is used as is.
    `load_reranker` is called only by runs whose config reranks.
    """
    return {
        JobKind.INGEST: JobHandler(
            run=partial(run_ingest_job, chunker=chunker, embedder=embedder),
            on_failure=mark_document_failed,
        ),
        JobKind.EVALUATE: JobHandler(
            run=partial(
                run_evaluation_job,
                query_embedder_for=query_embedder_for or (lambda _instruction: embedder),
                load_reranker=load_reranker,
            ),
            # Results are written only on success, so a failed run has nothing to undo;
            # the job's status and error are the run's failure state.
            on_failure=lambda _session, _job: None,
        ),
    }


def process_next_job(session: Session, handlers: dict[str, JobHandler]) -> bool:
    """Process one queued job. Returns False when the queue is empty."""
    job = jobs_repository.claim_next_job(session)
    if job is None:
        return False
    # Commit the claim first, so the job shows as running while it is processed.
    session.commit()

    handler = handlers.get(job.kind)
    try:
        if handler is None:
            raise LookupError(f"No handler for job kind '{job.kind}'")
        handler.run(session, job)
    except Exception as exc:  # noqa: BLE001 - the worker must survive any job failure
        logger.exception("job failed", extra={"fields": {"job_id": str(job.id)}})
        session.rollback()
        _record_failure(session, job, handler, exc)
        return True

    jobs_repository.mark_job_finished(session, job.id, JobStatus.SUCCEEDED)
    session.commit()
    return True


def run_worker(handlers: dict[str, JobHandler], poll_seconds: float, once: bool) -> None:
    stop = _stop_on_signal()
    logger.info("worker started", extra={"fields": {"once": once}})
    while not stop.is_set():
        with get_sessionmaker()() as session:
            processed = process_next_job(session, handlers)
        if processed:
            continue
        if once:
            break
        stop.wait(poll_seconds)
    logger.info("worker stopped")


def build_default_handlers() -> dict[str, JobHandler]:
    """Real chunker and embedder. Imported lazily: loading torch takes tens of seconds."""
    from app.ingestion.local_models import HuggingFaceTokenizer, SentenceTransformerEmbedder

    settings = get_settings()
    chunker = TokenWindowChunker(
        HuggingFaceTokenizer(settings.embedding_model_name),
        settings.chunk_max_tokens,
        settings.chunk_overlap_tokens,
    )
    # Passages only: the worker never embeds queries, so no query instruction is needed.
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model_name, settings.embedding_batch_size
    )
    # get_reranker is cached and lazy: the cross-encoder loads on the first run that reranks.
    return build_handlers(
        chunker, embedder, query_embedder_for=embedder.for_queries, load_reranker=get_reranker
    )


def _record_failure(
    session: Session, job: Job, handler: JobHandler | None, error: Exception
) -> None:
    if handler is not None:
        handler.on_failure(session, job)
    jobs_repository.mark_job_finished(session, job.id, JobStatus.FAILED, f"{error}")
    session.commit()


def _stop_on_signal() -> threading.Event:
    """Set an event on Ctrl+C / SIGTERM so the current job finishes before exiting."""
    stop = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        logger.info("stop requested", extra={"fields": {"signal": signum}})
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return stop


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--once", action="store_true", help="Drain the queue, then exit")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    run_worker(build_default_handlers(), settings.worker_poll_seconds, args.once)


if __name__ == "__main__":
    main()
