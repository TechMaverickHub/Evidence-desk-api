"""FastAPI dependencies shared by every feature module: DB session, caller identity, roles."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth import repository as auth_repository
from app.auth.models import Role
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotAuthenticatedError
from app.core.security import decode_access_token

# auto_error=False so a missing token goes through our own NotAuthenticatedError
# (error envelope + WWW-Authenticate header) instead of FastAPI's default response.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/token", auto_error=False)

SessionDep = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller. Feature modules depend on this, not on the User model."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    role: Role


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)], session: SessionDep
) -> CurrentUser:
    if not token:
        raise NotAuthenticatedError()
    claims = decode_access_token(token)
    # Tenant and role come from the database, not the token, so deactivation and role
    # changes take effect immediately rather than when the token expires.
    user = auth_repository.get_user_in_tenant(session, claims.tenant_id, claims.user_id)
    if user is None or not user.is_active:
        raise NotAuthenticatedError()
    return CurrentUser(id=user.id, tenant_id=user.tenant_id, email=user.email, role=user.role)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(required: Role) -> Callable[[CurrentUser], CurrentUser]:
    """Dependency factory: `Depends(require_role(Role.EDITOR))` allows editors and admins."""

    def check_role(current_user: CurrentUserDep) -> CurrentUser:
        if not current_user.role.includes(required):
            raise ForbiddenError()
        return current_user

    return check_role
