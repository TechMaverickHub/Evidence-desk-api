from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.auth.models import Role, User
from tests.conftest import auth_headers, ingest_request

PAYLOAD = ingest_request().model_dump()


def test_new_document_is_accepted_and_queued(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    headers = auth_headers(make_user(Role.EDITOR))

    response = client.post("/v1/documents/ingest", json=PAYLOAD, headers=headers)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    job = client.get(f"/v1/jobs/{body['job_id']}", headers=headers).json()
    assert (job["kind"], job["status"], job["attempts"]) == ("ingest", "queued", 0)


def test_identical_resubmission_returns_the_same_ids_without_a_new_job(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    headers = auth_headers(make_user(Role.EDITOR))

    first = client.post("/v1/documents/ingest", json=PAYLOAD, headers=headers)
    second = client.post("/v1/documents/ingest", json=PAYLOAD, headers=headers)

    assert (first.status_code, second.status_code) == (202, 200)
    assert first.json() == second.json()


def test_same_version_with_different_content_is_a_conflict(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    headers = auth_headers(make_user(Role.EDITOR))
    client.post("/v1/documents/ingest", json=PAYLOAD, headers=headers)

    response = client.post(
        "/v1/documents/ingest", json={**PAYLOAD, "content": "Changed text."}, headers=headers
    )

    assert response.status_code == 409


def test_same_slug_in_two_tenants_does_not_collide(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    editor_a, editor_b = make_user(Role.EDITOR), make_user(Role.EDITOR)

    response_a = client.post("/v1/documents/ingest", json=PAYLOAD, headers=auth_headers(editor_a))
    response_b = client.post("/v1/documents/ingest", json=PAYLOAD, headers=auth_headers(editor_b))

    assert (response_a.status_code, response_b.status_code) == (202, 202)
    assert response_a.json()["document_id"] != response_b.json()["document_id"]


def test_viewer_cannot_ingest(client: TestClient, make_user: Callable[..., User]) -> None:
    response = client.post(
        "/v1/documents/ingest", json=PAYLOAD, headers=auth_headers(make_user(Role.VIEWER))
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("override", "bad_field"),
    [
        ({"content": "   \n  "}, "content"),
        ({"slug": "Has Spaces"}, "slug"),
        ({"metadata": {f"k{i}": i for i in range(21)}}, "metadata"),
        ({"tenant_id": "00000000-0000-0000-0000-000000000000"}, "tenant_id"),
    ],
)
def test_invalid_payloads_are_rejected(
    client: TestClient, make_user: Callable[..., User], override: dict, bad_field: str
) -> None:
    response = client.post(
        "/v1/documents/ingest",
        json={**PAYLOAD, **override},
        headers=auth_headers(make_user(Role.EDITOR)),
    )

    assert response.status_code == 422
    assert bad_field in response.json()["field_errors"]
