"""Demo cohort seeding tests (U8)."""

from __future__ import annotations

from app import scoring
from app.db import SessionLocal
from app.models import STATUS_COMPLETED, Run, User
from app.seed_demo import seed_demo_runs


def test_seed_demo_creates_a_completed_cohort():
    seed_demo_runs(SessionLocal)
    with SessionLocal() as s:
        rows = scoring.leaderboard(s)
        assert len(rows) == 5  # five fictional analysts
        # Every seeded run is completed with a composite score and full history.
        completed = s.query(Run).filter(Run.status == STATUS_COMPLETED).all()
        assert len(completed) == 5
        for run in completed:
            assert run.composite_score is not None
            assert run.final_value is not None
            assert len(run.decisions) == 4
            assert len(run.reflections) == 4
            assert len(run.feedback) == 4


def test_seed_demo_is_idempotent():
    seed_demo_runs(SessionLocal)
    seed_demo_runs(SessionLocal)  # second call must not duplicate
    with SessionLocal() as s:
        students = s.query(User).filter(User.role == "student").count()
        # 3 login demo students + 5 fictional cohort personas.
        assert students == 8
        assert len(scoring.leaderboard(s)) == 5


def test_seeded_runs_span_a_range_of_scores():
    seed_demo_runs(SessionLocal)
    with SessionLocal() as s:
        rows = scoring.leaderboard(s)
        composites = [r["composite"] for r in rows]
        # A varied cohort makes the leaderboard interesting — not all identical.
        assert max(composites) - min(composites) > 10
