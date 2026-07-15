"""Analyst credentials (U9) — rules, awarding, and the AI/score firewall."""

from __future__ import annotations

import pytest

from app import badges, engine
from app.content import BADGE_IDS, load_content_pack
from app.feedback import CannedFeedbackService
from app.models import Reflection, Run, RoundDecision

PACK = load_content_pack()

# An even, mandate-respecting spread: diversified, 10% cash, nothing concentrated.
SPREAD = {"KGM": 15, "UFG": 15, "KFR": 15, "VLA": 15, "CFL": 15, "SUN": 15, "CASH": 10}
# A reckless bet: 70% in one share, no cash — breaches both mandate rules.
CONCENTRATED = {"KGM": 70, "UFG": 30, "KFR": 0, "VLA": 0, "CFL": 0, "SUN": 0, "CASH": 0}


def _results(round_number: int, allocation: dict) -> dict:
    return engine.compute_round(PACK, round_number, allocation, 1_000_000.0, 1_000_000.0)


def _run(**kwargs) -> Run:
    return Run(user_id=1, badges=[], **kwargs)


# --- Catalog integrity -------------------------------------------------------


def test_catalog_matches_the_content_contract():
    """badges.CATALOG and content.BADGE_IDS must not drift apart."""
    assert {b.id for b in badges.CATALOG} == set(BADGE_IDS)


def test_every_badge_has_an_authored_citation():
    """The offline path must be able to cite any badge the rules can award."""
    for badge in badges.CATALOG:
        assert PACK.fallback.badge_citations[badge.id].strip()


# --- Round-scope rules -------------------------------------------------------


def test_market_beater_needs_the_mandate_kept_too():
    """Beating the market while breaching the mandate earns nothing."""
    # Round 3 is the gold spike: a 70% Kalahari bet beats the market handsomely.
    results = _results(3, CONCENTRATED)
    assert results["beat_benchmark"] is True
    assert results["mandate"]["kept"] is False

    run = _run()
    earned = badges.award_round_badges(
        run, round_number=3, allocation=CONCENTRATED, forecast={}, results=results, pack=PACK
    )
    assert "market_beater" not in {b["id"] for b in earned}


def test_crisis_navigator_only_fires_in_an_event_round():
    """Round 1 has no authored event, so the credential cannot be earned there."""
    beating = {"KGM": 30, "UFG": 10, "KFR": 0, "VLA": 10, "CFL": 0, "SUN": 30, "CASH": 20}
    r1 = _results(1, beating)
    assert r1["events"] == []

    run = _run()
    badges.award_round_badges(
        run, round_number=1, allocation=beating, forecast={}, results=r1, pack=PACK
    )
    assert "crisis_navigator" not in badges.earned_ids(run)

    # Round 3 *is* an event round (the mining supply shock).
    r3 = _results(3, {"KGM": 40, "UFG": 10, "KFR": 10, "VLA": 10, "CFL": 0, "SUN": 10, "CASH": 20})
    assert r3["events"] and r3["beat_benchmark"]
    run2 = _run()
    badges.award_round_badges(
        run2, round_number=3, allocation=SPREAD, forecast={}, results=r3, pack=PACK
    )
    assert "crisis_navigator" in badges.earned_ids(run2)


def test_sharp_read_requires_every_directional_call_to_land():
    """One wrong call sinks the badge; flat calls are ignored, not counted."""
    results = _results(2, SPREAD)  # rate hike: UFG up, VLA down, SUN down.
    moves = {s["id"]: s["share_return"] for s in results["per_share"]}
    assert moves["UFG"] > 0 and moves["VLA"] < 0

    right = {"directions": {"UFG": "up", "VLA": "down", "KGM": "flat"}}
    run = _run()
    badges.award_round_badges(
        run, round_number=2, allocation=SPREAD, forecast=right, results=results, pack=PACK
    )
    assert "sharp_read" in badges.earned_ids(run)

    wrong = {"directions": {"UFG": "up", "VLA": "up"}}
    run2 = _run()
    badges.award_round_badges(
        run2, round_number=2, allocation=SPREAD, forecast=wrong, results=results, pack=PACK
    )
    assert "sharp_read" not in badges.earned_ids(run2)


def test_sharp_read_needs_a_minimum_number_of_calls():
    """A single lucky call is not a sector read."""
    results = _results(2, SPREAD)
    one_call = {"directions": {"UFG": "up", "VLA": "flat", "KGM": "flat"}}
    run = _run()
    badges.award_round_badges(
        run, round_number=2, allocation=SPREAD, forecast=one_call, results=results, pack=PACK
    )
    assert "sharp_read" not in badges.earned_ids(run)


def test_a_badge_is_never_awarded_twice():
    run = _run()
    for rnd in (1, 4):
        results = _results(rnd, SPREAD)
        badges.award_round_badges(
            run, round_number=rnd, allocation=SPREAD, forecast={}, results=results, pack=PACK
        )
    ids = [b["id"] for b in run.badges]
    assert len(ids) == len(set(ids))


# --- Run-scope rules ---------------------------------------------------------


def _decisions(allocations: list[dict]) -> list[RoundDecision]:
    out = []
    value = bench = 1_000_000.0
    for rnd, allocation in enumerate(allocations, start=1):
        results = engine.compute_round(PACK, rnd, allocation, value, bench)
        out.append(
            RoundDecision(
                run_id=1, round_number=rnd, allocation=allocation, forecast={}, results=results
            )
        )
        value, bench = results["end_value"], results["benchmark_end"]
    return out


def test_mandate_keeper_needs_a_clean_sheet_in_every_round():
    clean = _decisions([SPREAD] * PACK.total_rounds)
    run = _run(client_trust=50.0)
    badges.award_run_badges(run, decisions=clean, reflections=[], pack=PACK)
    assert "mandate_keeper" in badges.earned_ids(run)

    dirty = _decisions([SPREAD, SPREAD, CONCENTRATED, SPREAD])
    run2 = _run(client_trust=50.0)
    badges.award_run_badges(run2, decisions=dirty, reflections=[], pack=PACK)
    assert "mandate_keeper" not in badges.earned_ids(run2)


def test_trusted_advisor_tracks_final_client_trust():
    decisions = _decisions([SPREAD] * PACK.total_rounds)
    low = _run(client_trust=40.0)
    badges.award_run_badges(low, decisions=decisions, reflections=[], pack=PACK)
    assert "trusted_advisor" not in badges.earned_ids(low)

    high = _run(client_trust=88.0)
    badges.award_run_badges(high, decisions=decisions, reflections=[], pack=PACK)
    assert "trusted_advisor" in badges.earned_ids(high)


def test_alpha_generator_requires_beating_the_benchmark_over_the_year():
    decisions = _decisions([SPREAD] * PACK.total_rounds)
    ahead = _run(client_trust=50.0, final_value=1_100_000.0, benchmark_value=1_050_000.0)
    badges.award_run_badges(ahead, decisions=decisions, reflections=[], pack=PACK)
    assert "alpha_generator" in badges.earned_ids(ahead)

    behind = _run(client_trust=50.0, final_value=1_000_000.0, benchmark_value=1_050_000.0)
    badges.award_run_badges(behind, decisions=decisions, reflections=[], pack=PACK)
    assert "alpha_generator" not in badges.earned_ids(behind)


def test_deep_thinker_needs_a_substantial_reflection_every_round():
    decisions = _decisions([SPREAD] * PACK.total_rounds)
    long_text = " ".join(["word"] * 40)

    full = [
        Reflection(run_id=1, round_number=r, text=long_text)
        for r in range(1, PACK.total_rounds + 1)
    ]
    run = _run(client_trust=50.0)
    badges.award_run_badges(run, decisions=decisions, reflections=full, pack=PACK)
    assert "deep_thinker" in badges.earned_ids(run)

    # One throwaway answer is enough to lose it.
    lazy = list(full[:-1]) + [Reflection(run_id=1, round_number=4, text="it went fine")]
    run2 = _run(client_trust=50.0)
    badges.award_run_badges(run2, decisions=decisions, reflections=lazy, pack=PACK)
    assert "deep_thinker" not in badges.earned_ids(run2)


# --- The firewall: badges are recognition, never marks ------------------------


def test_the_scoring_path_never_reads_a_badge():
    """No badge may reach the composite model (R8, KTD6).

    ``scoring.leaderboard`` does pass badges through — but purely as display
    data for the table. The *scoring* functions must not mention them at all.
    """
    import inspect as _inspect

    from app import scoring

    scored = [
        scoring.finalize_run,
        scoring.composite_score,
        scoring.decision_quality,
        scoring.reflection_score,
        scoring.outcome_score,
    ]
    for fn in scored:
        assert "badge" not in _inspect.getsource(fn).lower(), f"{fn.__name__} reads badges"


def test_awarding_badges_does_not_move_the_composite_score(db_session):
    """The same run scores identically with and without credentials attached."""
    from app import scoring
    from app.models import STATUS_COMPLETED, User

    user = db_session.query(User).filter(User.username == "student").first()

    def _finished_run() -> Run:
        run = Run(
            user_id=user.id,
            status=STATUS_COMPLETED,
            client_trust=90.0,
            final_value=1_100_000.0,
            benchmark_value=1_050_000.0,
            badges=[],
        )
        db_session.add(run)
        db_session.flush()
        value = bench = 1_000_000.0
        for rnd, allocation in enumerate([SPREAD] * PACK.total_rounds, start=1):
            results = engine.compute_round(PACK, rnd, allocation, value, bench)
            db_session.add(
                RoundDecision(
                    run_id=run.id, round_number=rnd, allocation=allocation,
                    forecast={}, results=results,
                )
            )
            db_session.add(
                Reflection(run_id=run.id, round_number=rnd, text=" ".join(["word"] * 40))
            )
            value, bench = results["end_value"], results["benchmark_end"]
        db_session.flush()
        return run

    plain = _finished_run()
    scoring.finalize_run(db_session, plain, PACK)

    decorated = _finished_run()
    scoring.finalize_run(db_session, decorated, PACK)
    badges.award_run_badges(
        decorated,
        decisions=sorted(decorated.decisions, key=lambda d: d.round_number),
        reflections=sorted(decorated.reflections, key=lambda r: r.round_number),
        pack=PACK,
    )
    # Re-scoring a run that now carries badges must land on the same number.
    scoring.finalize_run(db_session, decorated, PACK)

    assert decorated.badges, "expected this run to have earned credentials"
    assert decorated.composite_score == plain.composite_score


def test_canned_citation_falls_back_to_authored_text():
    service = CannedFeedbackService(PACK)
    result = service.badge_citation(
        badge_id="mandate_keeper", badge_name="Mandate Keeper", badge_why="rule text"
    )
    assert result.source == "canned"
    assert result.text == PACK.fallback.badge_citations["mandate_keeper"]


def test_citation_failure_never_loses_the_award():
    """If the live citation call explodes, the badge still stands, with words."""
    from app.feedback import OpenAIFeedbackService

    class Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    raise RuntimeError("API down")

    service = OpenAIFeedbackService(PACK, client=Boom(), model="test")
    result = service.badge_citation(
        badge_id="diversifier", badge_name="Diversifier", badge_why="rule text"
    )
    assert result.source == "canned"
    assert result.text.strip()
