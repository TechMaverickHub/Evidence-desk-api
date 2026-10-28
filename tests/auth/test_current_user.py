import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.models import Tenant, User
from app.core.security import create_access_token
from tests.conftest import auth_headers


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_missing_token_is_401_with_bearer_challenge(client: TestClient) -> None:
    response = client.get("/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error_code"] == "NOT_AUTHENTICATED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_user_deactivated_after_login_is_rejected(
    client: TestClient, db_session: Session, make_user: Callable[..., User]
) -> None:
    user = make_user()
    headers = auth_headers(user)
    user.is_active = False
    db_session.flush()

    assert client.get("/v1/auth/me", headers=headers).status_code == 401


def test_token_for_unknown_user_is_rejected(
    client: TestClient, make_tenant: Callable[..., Tenant]
) -> None:
    token = create_access_token(uuid.uuid4(), make_tenant().id, "admin")

    assert client.get("/v1/auth/me", headers=_bearer(token)).status_code == 401


def test_token_claiming_another_tenant_is_rejected(
    client: TestClient, make_tenant: Callable[..., Tenant], make_user: Callable[..., User]
) -> None:
    user = make_user()
    # Validly signed, but the tenant claim does not match the user's real tenant.
    token = create_access_token(user.id, make_tenant().id, user.role)

    assert client.get("/v1/auth/me", headers=_bearer(token)).status_code == 401


def test_me_returns_only_the_callers_own_tenant(
    client: TestClient, make_tenant: Callable[..., Tenant], make_user: Callable[..., User]
) -> None:
    tenant_a, tenant_b = make_tenant("tenant-a"), make_tenant("tenant-b")
    user_a, user_b = make_user(tenant=tenant_a), make_user(tenant=tenant_b)

    me_a = client.get("/v1/auth/me", headers=auth_headers(user_a)).json()
    me_b = client.get("/v1/auth/me", headers=auth_headers(user_b)).json()

    assert me_a["tenant"] == {"id": str(tenant_a.id), "name": "tenant-a"}
    assert me_b["tenant"] == {"id": str(tenant_b.id), "name": "tenant-b"}
