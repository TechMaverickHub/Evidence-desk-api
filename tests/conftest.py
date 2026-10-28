"""Shared fixtures. Tests run against TEST_DATABASE_URL, never the dev database."""

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def use_test_database() -> None:
    test_database_url = get_settings().test_database_url
    if not test_database_url:
        pytest.exit("TEST_DATABASE_URL is not set; see .env.example", returncode=2)
    # Repoint the app at the test database, then drop cached objects built from the old URL.
    os.environ["DATABASE_URL"] = test_database_url
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture
def app() -> FastAPI:
    # A fresh app per test keeps dependency_overrides and test-only routes isolated.
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
