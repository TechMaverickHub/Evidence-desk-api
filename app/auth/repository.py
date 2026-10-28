"""Database queries for tenants and users. Never commits; services own transactions."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import Role, Tenant, User


def get_user_by_email(session: Session, email: str) -> User | None:
    # The one user lookup without tenant_id: emails are globally unique and login
    # happens before the tenant is known (see task 002, assumption 1).
    return session.scalar(select(User).where(User.email == email))


def get_user_in_tenant(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
    return session.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))


def get_tenant(session: Session, tenant_id: uuid.UUID) -> Tenant | None:
    return session.get(Tenant, tenant_id)


def add_tenant(session: Session, name: str) -> Tenant:
    tenant = Tenant(name=name)
    session.add(tenant)
    # Flush so unique violations surface here, where the service can translate them.
    session.flush()
    return tenant


def add_user(
    session: Session, tenant_id: uuid.UUID, email: str, password_hash: str, role: Role
) -> User:
    user = User(tenant_id=tenant_id, email=email, password_hash=password_hash, role=role)
    session.add(user)
    session.flush()
    return user
