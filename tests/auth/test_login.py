from collections.abc import Callable

import httpx2
from fastapi.testclient import TestClient

from app.auth.models import User
from tests.conftest import TEST_PASSWORD


def _login(client: TestClient, email: str, password: str) -> httpx2.Response:
    return client.post("/v1/auth/token", data={"username": email, "password": password})


def test_valid_credentials_return_a_working_token(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    user = make_user()

    # Upper-cased to prove login is case-insensitive on email.
    response = _login(client, user.email.upper(), TEST_PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["id"] == str(user.id)


def test_failed_logins_do_not_reveal_whether_the_account_exists(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    user = make_user()
    inactive_user = make_user(is_active=False)

    wrong_password = _login(client, user.email, "wrong-password-123")
    unknown_email = _login(client, "nobody@example.com", TEST_PASSWORD)
    inactive = _login(client, inactive_user.email, TEST_PASSWORD)

    for response in (wrong_password, unknown_email, inactive):
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
    assert wrong_password.json() == unknown_email.json() == inactive.json()
