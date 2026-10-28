from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.db import check_database


def test_health_reports_ok_when_database_is_reachable(client: TestClient) -> None:
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_database_is_unreachable(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[check_database] = lambda: False

    response = client.get("/v1/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}
