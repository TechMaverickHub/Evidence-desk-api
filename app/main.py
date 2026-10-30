"""FastAPI application factory: wires settings, logging, error handlers and routers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, log_requests
from app.documents.router import router as documents_router
from app.health.router import router as health_router
from app.jobs.router import router as jobs_router
from app.retrieval.deps import get_query_embedder
from app.retrieval.router import router as search_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Loading the embedding model takes about a minute on the dev machine; do it once at
    # startup rather than inside the first search request.
    if get_settings().preload_embedding_model:
        get_query_embedder()
    yield


def create_app() -> FastAPI:
    configure_logging(get_settings().log_level)

    app = FastAPI(
        title="EvidenceDesk API",
        version="0.1.0",
        description="Evaluation-driven engineering knowledge assistant.",
        lifespan=lifespan,
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=log_requests)
    register_exception_handlers(app)

    # Every feature router is mounted under /v1; new features add one line here.
    api_v1 = APIRouter(prefix="/v1")
    api_v1.include_router(health_router)
    api_v1.include_router(auth_router)
    api_v1.include_router(documents_router)
    api_v1.include_router(jobs_router)
    api_v1.include_router(search_router)
    app.include_router(api_v1)
    return app


app = create_app()
