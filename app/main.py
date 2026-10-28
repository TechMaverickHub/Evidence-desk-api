"""FastAPI application factory: wires settings, logging, error handlers and routers."""

from fastapi import APIRouter, FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, log_requests
from app.health.router import router as health_router


def create_app() -> FastAPI:
    configure_logging(get_settings().log_level)

    app = FastAPI(
        title="EvidenceDesk API",
        version="0.1.0",
        description="Evaluation-driven engineering knowledge assistant.",
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=log_requests)
    register_exception_handlers(app)

    # Every feature router is mounted under /v1; new features add one line here.
    api_v1 = APIRouter(prefix="/v1")
    api_v1.include_router(health_router)
    app.include_router(api_v1)
    return app


app = create_app()
