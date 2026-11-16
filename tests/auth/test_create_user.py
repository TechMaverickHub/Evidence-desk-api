from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import cli
from app.auth.models import Role, Tenant, User
from app.auth.repository import get_user_by_email
from tests.conftest import auth_headers

NEW_USER = {"email": "New.Person@Example.com", "password": "a-strong-password", "role": "editor"}


def test_admin_creates_user_in_their_own_tenant(
    client: TestClient, db_session: Session, make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)

    response = client.post("/v1/auth/users", json=NEW_USER, headers=auth_headers(admin))

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == str(admin.tenant_id)
    assert body["email"] == "new.person@example.com"
    assert "password_hash" not in body
    stored = get_user_by_email(db_session, "new.person@example.com")
    assert stored is not None
    assert stored.password_hash.startswith("$argon2id$")


def test_created_user_can_log_in(client: TestClient, make_user: Callable[..., User]) -> None:
    client.post("/v1/auth/users", json=NEW_USER, headers=auth_headers(make_user(Role.ADMIN)))

    response = client.post(
        "/v1/auth/token",
        data={"username": NEW_USER["email"], "password": NEW_USER["password"]},
    )

    assert response.status_code == 200


@pytest.mark.parametrize("role", [Role.VIEWER, Role.EDITOR])
def test_non_admins_cannot_create_users(
    client: TestClient, make_user: Callable[..., User], role: Role
) -> None:
    response = client.post("/v1/auth/users", json=NEW_USER, headers=auth_headers(make_user(role)))

    assert response.status_code == 403
    assert response.json()["error_code"] == "FORBIDDEN"


def test_tenant_id_in_body_is_rejected(
    client: TestClient, make_tenant: Callable[..., Tenant], make_user: Callable[..., User]
) -> None:
    admin = make_user(Role.ADMIN)
    other_tenant = make_tenant()

    response = client.post(
        "/v1/auth/users",
        json={**NEW_USER, "tenant_id": str(other_tenant.id)},
        headers=auth_headers(admin),
    )

    assert response.status_code == 422
    assert "tenant_id" in response.json()["field_errors"]


def test_duplicate_email_in_any_case_is_a_conflict(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    headers = auth_headers(make_user(Role.ADMIN))
    client.post("/v1/auth/users", json=NEW_USER, headers=headers)

    response = client.post(
        "/v1/auth/users",
        json={**NEW_USER, "email": NEW_USER["email"].upper()},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "CONFLICT"


def test_short_password_is_rejected(client: TestClient, make_user: Callable[..., User]) -> None:
    response = client.post(
        "/v1/auth/users",
        json={**NEW_USER, "password": "short"},
        headers=auth_headers(make_user(Role.ADMIN)),
    )

    assert response.status_code == 422
    assert "password" in response.json()["field_errors"]


def test_cli_creates_tenant_with_admin(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "a-strong-password")
    # Run the CLI inside this test's rolled-back session instead of a real one.
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: lambda: db_session)

    exit_code = cli.main(
        ["create-tenant", "--name", "acme", "--admin-email", "Admin@Acme.example.com"]
    )

    assert exit_code == 0
    admin = get_user_by_email(db_session, "admin@acme.example.com")
    assert admin is not None
    assert admin.role == Role.ADMIN


def _no_prompt(prompt: str) -> str:
    raise AssertionError("--password-env must not prompt")


def test_cli_reads_the_admin_password_from_the_named_env_variable(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    monkeypatch.setattr(cli.getpass, "getpass", _no_prompt)
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: lambda: db_session)
    monkeypatch.setenv("GATE_ADMIN_PASSWORD", "a-strong-password")

    exit_code = cli.main(
        [
            "create-tenant",
            "--name",
            "ci",
            "--admin-email",
            "ci@example.com",
            "--password-env",
            "GATE_ADMIN_PASSWORD",
        ]
    )

    assert exit_code == 0
    assert get_user_by_email(db_session, "ci@example.com") is not None


@pytest.mark.parametrize("value", [None, "", "short"])
def test_cli_rejects_a_missing_or_weak_env_password(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, value: str | None
) -> None:
    monkeypatch.setattr(cli.getpass, "getpass", _no_prompt)
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: lambda: db_session)
    monkeypatch.delenv("GATE_ADMIN_PASSWORD", raising=False)
    if value is not None:
        monkeypatch.setenv("GATE_ADMIN_PASSWORD", value)

    args = ["create-tenant", "--name", "ci", "--admin-email", "ci@example.com"]

    assert cli.main([*args, "--password-env", "GATE_ADMIN_PASSWORD"]) == 1
    assert get_user_by_email(db_session, "ci@example.com") is None
