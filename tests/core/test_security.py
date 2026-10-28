"""Token forgery and password storage are the highest-risk parts of auth."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.errors import NotAuthenticatedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "role": "viewer",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return claims


def _sign(claims: dict[str, object]) -> str:
    return jwt.encode(claims, get_settings().jwt_secret_key, algorithm="HS256")


def test_password_hash_is_argon2id_and_verifies() -> None:
    password_hash = hash_password("a-long-test-password")

    assert password_hash.startswith("$argon2id$")
    assert verify_password("a-long-test-password", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_token_round_trip_preserves_identity() -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()

    claims = decode_access_token(create_access_token(user_id, tenant_id, "editor"))

    assert (claims.user_id, claims.tenant_id, claims.role) == (user_id, tenant_id, "editor")


@pytest.mark.parametrize(
    "forged_token",
    [
        pytest.param(jwt.encode(_claims(), "x" * 40, algorithm="HS256"), id="other-key"),
        pytest.param(jwt.encode(_claims(), key=None, algorithm="none"), id="alg-none"),
        pytest.param("not.a.jwt", id="malformed"),
    ],
)
def test_forged_tokens_are_rejected(forged_token: str) -> None:
    with pytest.raises(NotAuthenticatedError):
        decode_access_token(forged_token)


def test_expired_token_is_rejected() -> None:
    expired = _sign(_claims(exp=datetime.now(UTC) - timedelta(seconds=1)))

    with pytest.raises(NotAuthenticatedError):
        decode_access_token(expired)


def test_tampered_payload_is_rejected() -> None:
    header, _payload, signature = create_access_token(uuid.uuid4(), uuid.uuid4(), "viewer").split(
        "."
    )
    # Swap in a payload that claims admin, keeping the original signature.
    escalated = json.dumps({**_claims(role="admin"), "iat": 0, "exp": 9999999999}).encode()
    escalated_payload = base64.urlsafe_b64encode(escalated).rstrip(b"=").decode()

    with pytest.raises(NotAuthenticatedError):
        decode_access_token(f"{header}.{escalated_payload}.{signature}")


def test_non_uuid_subject_is_rejected() -> None:
    with pytest.raises(NotAuthenticatedError):
        decode_access_token(_sign(_claims(sub="admin")))
