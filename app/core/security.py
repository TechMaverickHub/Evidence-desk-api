"""Password hashing and JWT access tokens. No database access lives here."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.errors import NotAuthenticatedError

# HS256 is pinned on decode so tokens signed with `none` or another algorithm are rejected.
JWT_ALGORITHM = "HS256"

# argon2id with pwdlib's recommended parameters.
_password_hash = PasswordHash.recommended()


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def create_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    issued_at = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> TokenClaims:
    """Verify signature and expiry; any problem with the token is a 401."""
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret_key,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "tenant_id", "role", "exp"]},
        )
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tenant_id"]),
            role=payload["role"],
        )
    except (jwt.InvalidTokenError, ValueError) as exc:
        # ValueError covers claims that are present but are not valid UUIDs.
        raise NotAuthenticatedError() from exc
