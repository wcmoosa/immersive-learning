"""Database engine and session wiring.

A single SQLite file drives the demo. The location is configurable via
``DATABASE_URL`` so tests can point at a throwaway file or in-memory database
while the container defaults to a path under ``/app/data``.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/app.db")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# ``check_same_thread`` is disabled because FastAPI serves requests from a
# thread pool; SQLite is fine for a single-container demo.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    """FastAPI dependency yielding a scoped database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
