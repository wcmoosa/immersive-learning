"""Shared test fixtures.

The database URL is redirected to a throwaway temp file *before* the app
package is imported, so every test run gets a clean SQLite file that the ORM
models bind to.
"""

from __future__ import annotations

import os
import tempfile

# Must run before any `app.*` import so app.db picks up the test database.
_fd, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB_PATH.replace(os.sep, "/")
os.environ.setdefault("SESSION_SECRET", "test-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_users  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """Recreate all tables and seed demo accounts for each test."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_users(session)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def login(client: TestClient, username: str, password: str = "demo"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def _cleanup():
    if os.path.exists(_DB_PATH):
        try:
            os.remove(_DB_PATH)
        except OSError:
            pass


import atexit  # noqa: E402

atexit.register(_cleanup)
