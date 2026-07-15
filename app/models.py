"""SQLite ORM models for the Market Analyst Simulation.

The schema is intentionally small — one playthrough is a ``Run`` that owns four
``RoundDecision`` rows, four ``Reflection`` rows, and four ``FeedbackRecord``
rows. JSON columns hold the structured forecast, allocation, and computed
results so the deterministic engine can stay a pure function over plain dicts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Run lifecycle steps — the server-enforced state machine (see plan HTD).
STEP_BRIEFING = "briefing"
STEP_FORECAST = "forecast"
STEP_ALLOCATION = "allocation"
STEP_RESULTS = "results"
STEP_REFLECTION = "reflection"
STEP_SUMMARY = "summary"

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"

TOTAL_ROUNDS = 4


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Demo-only shared credentials — no hashing ceremony (see plan U1 approach).
    password: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # "student" | "lecturer"
    display_name: Mapped[str] = mapped_column(String(128))

    runs: Mapped[list["Run"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    status: Mapped[str] = mapped_column(String(16), default=STATUS_IN_PROGRESS)
    current_round: Mapped[int] = mapped_column(Integer, default=1)
    current_step: Mapped[str] = mapped_column(String(16), default=STEP_BRIEFING)

    client_trust: Mapped[float] = mapped_column(Float, default=50.0)

    # Analyst credentials earned so far (U9) — a list of badge records. Awarded
    # by deterministic rules only; the AI writes each citation, never the award.
    # Display-only: badges never enter ``composite_score``.
    badges: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Populated at final summary time.
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    user: Mapped["User"] = relationship(back_populates="runs")
    decisions: Mapped[list["RoundDecision"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RoundDecision.round_number"
    )
    reflections: Mapped[list["Reflection"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Reflection.round_number"
    )
    feedback: Mapped[list["FeedbackRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="FeedbackRecord.round_number"
    )


class RoundDecision(Base):
    __tablename__ = "round_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    round_number: Mapped[int] = mapped_column(Integer)

    forecast: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    allocation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    portfolio_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    trust_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    trust_after: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="decisions")


class Reflection(Base):
    __tablename__ = "reflections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    round_number: Mapped[int] = mapped_column(Integer)

    text: Mapped[str] = mapped_column(Text, default="")
    # The LLM/authored reflection question shown to the student (cached so it is
    # generated once, not on every page load — see the reflect flow).
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Deterministic engagement heuristic (enters composite).
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_why: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LLM indicative rating (display-only, never enters any score).
    indicative_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    indicative_why: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="reflections")


class FeedbackRecord(Base):
    __tablename__ = "feedback_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    round_number: Mapped[int] = mapped_column(Integer)

    text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="canned")  # "openai" | "canned"

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="feedback")
