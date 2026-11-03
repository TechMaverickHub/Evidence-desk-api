"""End-to-end sanity check with the real model. Opt in with `uv run pytest -m model`."""

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.ingestion import cli
from app.retrieval import service
from app.worker import process_next_job

pytestmark = pytest.mark.model

FIXTURE_MANIFEST = Path(__file__).parents[1] / "fixtures" / "corpus" / "manifest.yaml"


def test_paraphrased_question_finds_the_incident(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    # Imported here so the default test run never loads torch.
    from app.retrieval.deps import get_query_embedder
    from app.worker import build_default_handlers

    tenant = make_tenant()
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: lambda: db_session)
    cli.load_corpus(tenant.name, FIXTURE_MANIFEST)
    handlers = build_default_handlers()
    while process_next_job(db_session, handlers):
        pass

    outcome = service.search(
        db_session,
        tenant.id,
        get_query_embedder(),
        "Why did the load balancer return 502 after a deploy?",
        service.SearchOptions(k=3),
    )

    assert outcome.hits[0].slug == "incidents/0001"


def test_the_cross_encoder_prefers_the_relevant_passage() -> None:
    from app.retrieval.deps import get_reranker

    reranker = get_reranker()

    relevant, unrelated = reranker.score(
        "How long does Uvicorn keep an idle connection open?",
        [
            "--timeout-keep-alive: close Keep-Alive connections if no new data is received "
            "within this timeout. Default: 5 seconds.",
            "Pydantic models validate the types of their fields.",
        ],
    )

    assert relevant > unrelated
