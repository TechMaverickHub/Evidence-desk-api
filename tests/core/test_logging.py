from fastapi.testclient import TestClient


def test_safe_client_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/v1/health", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_unsafe_client_request_id_is_replaced(client: TestClient) -> None:
    # A newline would let a client forge extra log lines (log injection).
    response = client.get("/v1/health", headers={"X-Request-ID": "abc\ninjected"})

    assert response.headers["X-Request-ID"] != "abc\ninjected"
    assert len(response.headers["X-Request-ID"]) == 36  # a fresh UUID
