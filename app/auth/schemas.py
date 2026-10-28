"""Request and response models for the auth endpoints. No password hash ever leaves here."""

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.models import Role

# The upper bound stops oversized inputs from making argon2 hashing a DoS vector.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the access token expires.")


class CreateUserRequest(BaseModel):
    # extra="forbid": a client sending tenant_id gets a 422 instead of it being silently
    # ignored, which makes the tenant boundary explicit.
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    role: Role


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    tenant_id: uuid.UUID


class TenantSummary(BaseModel):
    id: uuid.UUID
    name: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    tenant: TenantSummary
