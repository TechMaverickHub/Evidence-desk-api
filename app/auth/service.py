"""Auth business rules: logging in, creating users, creating a tenant with its admin."""

import logging
import uuid
from functools import lru_cache

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import repository
from app.auth.models import Role, Tenant, User
from app.core.errors import ConflictError, InvalidCredentialsError, NotAuthenticatedError
from app.core.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)


@lru_cache
def _dummy_password_hash() -> str:
    # Verified when the email is unknown, so a failed login takes the same time
    # whether or not the account exists (prevents user enumeration by timing).
    return hash_password("not-a-real-password")


def authenticate(session: Session, email: str, password: str) -> str:
    """Return an access token for valid credentials, else raise InvalidCredentialsError."""
    user = repository.get_user_by_email(session, email.lower())
    if user is None:
        verify_password(password, _dummy_password_hash())
        logger.info("login failed")
        raise InvalidCredentialsError()
    if not verify_password(password, user.password_hash) or not user.is_active:
        logger.info("login failed", extra={"fields": {"user_id": str(user.id)}})
        raise InvalidCredentialsError()

    logger.info("login succeeded", extra={"fields": {"user_id": str(user.id)}})
    return create_access_token(user.id, user.tenant_id, user.role)


def create_user(
    session: Session, tenant_id: uuid.UUID, email: str, password: str, role: Role
) -> User:
    """Create a user in `tenant_id`, which callers take from the authenticated admin."""
    try:
        user = _add_user(session, tenant_id, email, password, role)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("A user with this email already exists.") from exc
    return user


def create_tenant_with_admin(
    session: Session, tenant_name: str, admin_email: str, admin_password: str
) -> tuple[Tenant, User]:
    """Create a tenant and its first admin in one transaction (used by the CLI)."""
    try:
        tenant = repository.add_tenant(session, tenant_name)
        admin = _add_user(session, tenant.id, admin_email, admin_password, Role.ADMIN)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("A tenant with this name or a user with this email exists.") from exc
    return tenant, admin


def get_tenant_of(session: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = repository.get_tenant(session, tenant_id)
    if tenant is None:
        # Only reachable if the tenant row vanished after the user was loaded.
        raise NotAuthenticatedError()
    return tenant


def _add_user(
    session: Session, tenant_id: uuid.UUID, email: str, password: str, role: Role
) -> User:
    return repository.add_user(session, tenant_id, email.lower(), hash_password(password), role)
