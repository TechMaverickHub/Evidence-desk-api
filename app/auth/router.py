"""HTTP endpoints for login, the current user, and user creation."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth import service
from app.auth.models import Role
from app.auth.schemas import (
    CreateUserRequest,
    MeResponse,
    TenantSummary,
    TokenResponse,
    UserResponse,
)
from app.core.config import get_settings
from app.core.deps import CurrentUser, CurrentUserDep, SessionDep, require_role
from app.core.errors import ErrorResponse

router = APIRouter(prefix="/auth", tags=["auth"])

UNAUTHORIZED = {401: {"model": ErrorResponse, "description": "Not authenticated"}}


@router.post(
    "/token",
    summary="Log in with email and password",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse, "description": "Invalid credentials"}},
)
def issue_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> TokenResponse:
    # OAuth2's password flow names the field "username"; here it carries the email.
    access_token = service.authenticate(session, form.username, form.password)
    expires_in = get_settings().access_token_expire_minutes * 60
    return TokenResponse(access_token=access_token, expires_in=expires_in)


@router.get(
    "/me", summary="Get the current user", response_model=MeResponse, responses=UNAUTHORIZED
)
def read_me(current_user: CurrentUserDep, session: SessionDep) -> MeResponse:
    tenant = service.get_tenant_of(session, current_user.tenant_id)
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        tenant=TenantSummary(id=tenant.id, name=tenant.name),
    )


@router.post(
    "/users",
    summary="Create a user in the caller's tenant",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    responses={
        **UNAUTHORIZED,
        403: {"model": ErrorResponse, "description": "Caller is not an admin"},
        409: {"model": ErrorResponse, "description": "Email already in use"},
    },
)
def create_user(
    payload: CreateUserRequest,
    admin: Annotated[CurrentUser, Depends(require_role(Role.ADMIN))],
    session: SessionDep,
) -> UserResponse:
    # The tenant always comes from the authenticated admin, never from the request.
    user = service.create_user(
        session, admin.tenant_id, payload.email, payload.password, payload.role
    )
    return UserResponse(id=user.id, email=user.email, role=user.role, tenant_id=user.tenant_id)
