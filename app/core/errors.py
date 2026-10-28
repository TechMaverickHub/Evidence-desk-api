"""Application errors and the handlers that render every non-2xx as one JSON envelope.

Envelope: {"error_code": str, "message": str, "field_errors"?: {field: [messages]}}
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

FieldErrors = dict[str, list[str]]


class ErrorResponse(BaseModel):
    """OpenAPI description of the envelope, used in routers' `responses=` declarations."""

    error_code: str
    message: str
    field_errors: FieldErrors | None = None


# Codes for errors raised by the framework itself (unknown route, wrong method, ...).
HTTP_STATUS_ERROR_CODES = {
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


class AppError(Exception):
    """Base for all expected errors. Subclasses override the class attributes.

    New error types are added as subclasses; the handler below needs no changes.
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."
    headers: dict[str, str] = {}

    def __init__(self, message: str | None = None, field_errors: FieldErrors | None = None):
        self.message = message or self.message
        self.field_errors = field_errors
        super().__init__(self.message)


class NotAuthenticatedError(AppError):
    status_code = 401
    error_code = "NOT_AUTHENTICATED"
    message = "Missing, invalid or expired access token."
    # Required by RFC 6750 on 401 responses for bearer-token APIs.
    headers = {"WWW-Authenticate": "Bearer"}


class InvalidCredentialsError(AppError):
    status_code = 401
    error_code = "INVALID_CREDENTIALS"
    # Deliberately vague: must not reveal whether the email exists.
    message = "Incorrect email or password."
    headers = {"WWW-Authenticate": "Bearer"}


class ForbiddenError(AppError):
    status_code = 403
    error_code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    # Also used for objects that exist in another tenant, so IDs cannot be probed.
    status_code = 404
    error_code = "NOT_FOUND"
    message = "Resource not found."


class ConflictError(AppError):
    status_code = 409
    error_code = "CONFLICT"
    message = "The resource already exists."


def error_response(
    status_code: int,
    error_code: str,
    message: str,
    field_errors: FieldErrors | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Single place that builds the error envelope, shared by every handler."""
    body: dict[str, object] = {"error_code": error_code, "message": message}
    if field_errors:
        body["field_errors"] = field_errors
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def _field_errors_from_validation(exc: RequestValidationError) -> FieldErrors:
    field_errors: FieldErrors = {}
    for error in exc.errors():
        # loc looks like ("body", "filters", "version"); drop the "body"/"query" prefix.
        location = [str(part) for part in error["loc"][1:]] or [str(error["loc"][0])]
        field_errors.setdefault(".".join(location), []).append(error["msg"])
    return field_errors


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return error_response(
        exc.status_code, exc.error_code, exc.message, exc.field_errors, exc.headers or None
    )


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(
        422, "VALIDATION_ERROR", "Request validation failed.", _field_errors_from_validation(exc)
    )


async def _handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    error_code = HTTP_STATUS_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
    return error_response(exc.status_code, error_code, str(exc.detail))


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Log the full traceback server-side, but never leak exception details to the client.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    response = error_response(500, AppError.error_code, AppError.message)
    # This handler runs outside the request-logging middleware, so add the header here too.
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
