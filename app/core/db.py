"""Database engine, sessions and the declarative base for all models."""

import logging
from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache

from sqlalchemy import DateTime, Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Keeps the health check fast when Postgres is down, instead of waiting on the OS TCP timeout.
CONNECT_TIMEOUT_SECONDS = 3


class Base(DeclarativeBase):
    """Base class for every SQLAlchemy model; Alembic autogenerates from its metadata."""

    # Every `Mapped[datetime]` column is TIMESTAMPTZ, so stored times are unambiguous.
    type_annotation_map = {datetime: DateTime(timezone=True)}


# Engine and sessionmaker are created lazily (not at import time) so tests can point
# DATABASE_URL at the test database before the first connection is made.
@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request. Services own the transaction."""
    with get_sessionmaker()() as session:
        yield session


def check_database() -> bool:
    """FastAPI dependency for the health check: True if Postgres answers `SELECT 1`."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        logger.warning("Database health check failed", exc_info=True)
        return False
    return True
