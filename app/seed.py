"""Seed / reset CLI for the demo database.

Usage (inside the container or a 3.12 venv)::

    python -m app.seed ensure   # create tables + demo accounts only if empty
    python -m app.seed seed     # create tables + demo accounts (idempotent)
    python -m app.seed reset     # drop everything and re-seed a clean demo state

``reset`` is what a presenter runs between rehearsals to restore clean state.
The content pack is validated at seed time so a malformed pack fails loudly
before the demo (see U2).
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import inspect

from app.db import Base, DATABASE_URL, SessionLocal, engine
from app.models import User

# Pre-seeded demo accounts. Shared, obvious credentials — this is a throwaway
# showcase with no real data (plan U1: no registration, no SSO).
DEMO_STUDENTS = [
    ("thabo", "Thabo Mokoena"),
    ("aisha", "Aisha Patel"),
    ("student", "Demo Student"),
]
LECTURERS = [
    ("lecturer", "Dr. Naledi Khumalo"),
]
DEMO_PASSWORD = "demo"


def _ensure_data_dir() -> None:
    if DATABASE_URL.startswith("sqlite:///"):
        path = DATABASE_URL.replace("sqlite:///", "", 1)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)


def _validate_content_pack() -> None:
    """Fail loudly at seed time if the scenario pack is malformed (U2)."""
    from app.content import load_content_pack

    pack = load_content_pack()
    print(f"  content pack '{pack.title}' OK — {len(pack.shares)} shares, {pack.total_rounds} rounds")


def seed_users(session) -> int:
    created = 0
    for username, display in DEMO_STUDENTS:
        if session.query(User).filter(User.username == username).first() is None:
            session.add(User(username=username, password=DEMO_PASSWORD, role="student", display_name=display))
            created += 1
    for username, display in LECTURERS:
        if session.query(User).filter(User.username == username).first() is None:
            session.add(User(username=username, password=DEMO_PASSWORD, role="lecturer", display_name=display))
            created += 1
    session.commit()
    return created


def create_all() -> None:
    _ensure_data_dir()
    Base.metadata.create_all(engine)


def cmd_seed() -> None:
    create_all()
    _validate_content_pack()
    with SessionLocal() as session:
        created = seed_users(session)
    print(f"Seed complete — {created} new account(s).")


def cmd_reset() -> None:
    _ensure_data_dir()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    _validate_content_pack()
    with SessionLocal() as session:
        created = seed_users(session)
    # Optional demo cohort (fake completed runs) is added in U8.
    try:
        from app.seed_demo import seed_demo_runs  # type: ignore

        seed_demo_runs(SessionLocal)
        print("  demo cohort seeded.")
    except ImportError:
        pass
    print(f"Reset complete — clean demo state, {created} account(s).")


def cmd_ensure() -> None:
    """Seed only if the database looks empty (used by the container entrypoint)."""
    create_all()
    inspector = inspect(engine)
    with SessionLocal() as session:
        has_users = inspector.has_table("users") and session.query(User).first() is not None
    if has_users:
        print("Database already seeded — leaving it as is.")
        return
    _validate_content_pack()
    with SessionLocal() as session:
        created = seed_users(session)
    try:
        from app.seed_demo import seed_demo_runs  # type: ignore

        seed_demo_runs(SessionLocal)
    except ImportError:
        pass
    print(f"Database initialised — {created} account(s).")


COMMANDS = {"seed": cmd_seed, "reset": cmd_reset, "ensure": cmd_ensure}


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "seed"
    if cmd not in COMMANDS:
        print(f"Unknown command '{cmd}'. Use one of: {', '.join(COMMANDS)}")
        return 2
    COMMANDS[cmd]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
