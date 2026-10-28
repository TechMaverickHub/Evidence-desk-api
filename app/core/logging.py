"""Structured JSON logging and the per-request logging middleware."""

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime

from fastapi import Request, Response

# Holds the current request's id so every log line in that request can include it,
# without passing it through every function call.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Client-supplied ids are echoed into logs, so accept only short, safe strings
# to prevent log injection.
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")

logger = logging.getLogger("app.request")


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Extra structured data goes in `extra={"fields": {...}}`."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Our middleware already logs every request; silence uvicorn's duplicate access log.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _resolve_request_id(request: Request) -> str:
    candidate = request.headers.get("X-Request-ID", "")
    if SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Assign a request id, time the request, and log one line when it finishes."""
    request_id = _resolve_request_id(request)
    request_id_var.set(request_id)
    request.state.request_id = request_id
    started = time.perf_counter()
    # Assume failure until a response comes back: if call_next raises, the
    # `finally` block still logs the request as a 500 before the error propagates.
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        logger.info(
            "request",
            extra={
                "fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            },
        )
