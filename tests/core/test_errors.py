"""The error envelope is a contract every later endpoint relies on."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.errors import AppError


class ExampleNotFoundError(AppError):
    status_code = 404
    error_code = "NOT_FOUND"
    message = "Example not found."


class SearchRequest(BaseModel):
    query: str
    k: int = Field(default=10, le=50)


def _add_test_routes(app: FastAPI) -> None:
    @app.post("/test/search")
    def search(payload: SearchRequest) -> dict[str, int]:
        return {"k": payload.k}

    @app.get("/test/missing")
    def missing() -> None:
        raise ExampleNotFoundError()

    @app.get("/test/crash")
    def crash() -> None:
        raise RuntimeError("secret internal detail")


def test_validation_error_lists_field_errors(app: FastAPI, client: TestClient) -> None:
    _add_test_routes(app)

    response = client.post("/test/search", json={"query": "pgvector", "k": 500})

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert list(body["field_errors"]) == ["k"]


def test_app_error_subclass_renders_its_own_code(app: FastAPI, client: TestClient) -> None:
    _add_test_routes(app)

    response = client.get("/test/missing")

    assert response.status_code == 404
    assert response.json() == {"error_code": "NOT_FOUND", "message": "Example not found."}


def test_unknown_route_uses_the_envelope(client: TestClient) -> None:
    response = client.get("/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


def test_unhandled_error_hides_details_and_keeps_request_id(app: FastAPI) -> None:
    _add_test_routes(app)
    # raise_server_exceptions=False makes the client return the 500 response the
    # real server would send, instead of re-raising the exception in the test.
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/test/crash", headers={"X-Request-ID": "trace-123"})

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "INTERNAL_ERROR",
        "message": "An unexpected error occurred.",
    }
    assert "secret internal detail" not in response.text
    assert response.headers["X-Request-ID"] == "trace-123"
