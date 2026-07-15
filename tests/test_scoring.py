"""Composite scoring tests (U6)."""

from __future__ import annotations

import pytest

from app import scoring
from app.content import load_content_pack
from app.db import SessionLocal
from app.models import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    FeedbackRecord,
    Reflection,
    Run,
    RoundDecision,
    User,
)

PACK = load_content_pack()

EVEN = {"KGM": 15, "UFG": 15, "KFR": 15, "VLA": 15, "CFL": 15, "SUN": 15, "CASH": 10}
ALL_UP = {"directions": {s.id: "up" for s in PACK.shares}, "rationale": "growth everywhere"}


# --- Individual components ---------------------------------------------------

def test_diversification_high_for_even_split_zero_for_concentration():
    high, _ = scoring.diversification_score(EVEN, PACK)
    low, _ = scoring.diversification_score({"KGM": 100}, PACK)
    assert high > 90
    assert low == 0.0


def test_mandate_score_names_breach():
    score, why = scoring.mandate_score({"KGM": 100}, PACK)
    assert score < 100
    assert "mandate" in why.lower()
    assert "kalahari" in why.lower() or "cash" in why.lower()


def test_consistency_full_when_even_split_matches_all_up_calls():
    score, _ = scoring.consistency_score(ALL_UP, EVEN, PACK)
    assert score == pytest.approx(100.0)


def test_reflection_score_is_deterministic_and_rewards_length():
    empty, why = scoring.reflection_score("")
    assert empty == 10.0 and "brief" in why.lower()
    long_text = "I chose to diversify because rates are rising and I wanted to protect capital."
    a, _ = scoring.reflection_score(long_text)
    b, _ = scoring.reflection_score(long_text)
    assert a == b and a > empty


def test_outcome_scaling_matches_benchmark_at_midscale_and_clamps():
    mid, _ = scoring.outcome_score(0.05, 0.05)
    assert mid == pytest.approx(50.0)
    assert scoring.outcome_score(0.20, 0.05)[0] == 100.0   # extreme over -> clamp
    assert scoring.outcome_score(-0.20, 0.05)[0] == 0.0     # extreme under -> clamp


# --- Aggregation -------------------------------------------------------------

def test_decision_quality_max_for_ideal_run():
    rounds = [{"allocation": EVEN, "forecast": ALL_UP} for _ in range(4)]
    score, why = scoring.decision_quality(rounds, PACK)
    assert score > 90
    assert "diversification" in why.lower()


def test_decision_quality_penalises_all_in_one_share():
    rounds = [{"allocation": {"KGM": 100}, "forecast": ALL_UP} for _ in range(4)]
    score, _ = scoring.decision_quality(rounds, PACK)
    assert score < 30


def test_composite_weighting():
    assert scoring.composite_score(100, 100, 100) == pytest.approx(100.0)
    assert scoring.composite_score(0, 0, 0) == pytest.approx(0.0)
    assert scoring.composite_score(100, 0, 50) == pytest.approx(60.0)  # .4*100 + .2*0 + .4*50


# --- finalize_run integration ------------------------------------------------

def _make_completed_run(session, username, allocation, reflection_text, indicative=70.0,
                        final_value=1_100_000.0, benchmark_value=1_030_000.0):
    user = session.query(User).filter(User.username == username).one()
    run = Run(
        user_id=user.id, status=STATUS_COMPLETED, current_round=4, current_step="summary",
        client_trust=60.0, final_value=final_value, benchmark_value=benchmark_value,
    )
    session.add(run)
    session.flush()
    for r in range(1, 5):
        session.add(RoundDecision(run_id=run.id, round_number=r, allocation=allocation, forecast=ALL_UP,
                                  portfolio_value=final_value, benchmark_value=benchmark_value))
        session.add(Reflection(run_id=run.id, round_number=r, text=reflection_text, indicative_rating=indicative))
    session.commit()
    return run


def test_finalize_sets_composite_and_breakdown():
    with SessionLocal() as s:
        run = _make_completed_run(s, "student", EVEN, "A solid, thoughtful reflection about diversification.")
        scoring.finalize_run(s, run, PACK)
        s.commit()
        assert run.composite_score is not None
        keys = {c["key"] for c in run.composite_breakdown["components"]}
        assert keys == {"decision", "reflection", "outcome"}
        # per-reflection deterministic quality was persisted
        refls = s.query(Reflection).filter(Reflection.run_id == run.id).all()
        assert all(r.quality_score is not None for r in refls)


def test_composite_ignores_llm_indicative_rating():
    """Two identical runs differing only in the LLM indicative rating score the same."""
    with SessionLocal() as s:
        r1 = _make_completed_run(s, "student", EVEN, "Same reflection text here about my plan.", indicative=10.0)
        scoring.finalize_run(s, r1, PACK)
        r2 = _make_completed_run(s, "thabo", EVEN, "Same reflection text here about my plan.", indicative=95.0)
        scoring.finalize_run(s, r2, PACK)
        s.commit()
        assert r1.composite_score == pytest.approx(r2.composite_score)


# --- Leaderboard -------------------------------------------------------------

def test_leaderboard_orders_by_composite_and_excludes_incomplete():
    with SessionLocal() as s:
        low = _make_completed_run(s, "student", {"KGM": 100}, "brief", final_value=980_000.0)
        high = _make_completed_run(s, "thabo", EVEN, "A thoughtful and engaged reflection about the market.")
        scoring.finalize_run(s, low, PACK)
        scoring.finalize_run(s, high, PACK)
        # An in-progress run must not appear.
        aisha = s.query(User).filter(User.username == "aisha").one()
        s.add(Run(user_id=aisha.id, status=STATUS_IN_PROGRESS, current_round=2))
        s.commit()

        rows = scoring.leaderboard(s)
        assert len(rows) == 2
        assert rows[0]["composite"] >= rows[1]["composite"]
        assert rows[0]["name"] == "Thabo Mokoena"  # the diversified run wins
