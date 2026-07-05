"""Deterministic engine tests (U3) — hand-computed against the shipped pack.

Round-1 share returns (end/start - 1):
  KGM +6%, UFG +2%, KFR -4%, VLA +3%, CFL +1%, SUN +10%
Equal-weight benchmark round 1 = (6+2-4+3+1+10)/6 % = +3.0%.
"""

from __future__ import annotations

import pytest

from app import engine
from app.content import load_content_pack

PACK = load_content_pack()
CAP = PACK.starting_capital  # 1,000,000

# A diversified, mandate-compliant allocation used across tests.
DIVERSIFIED = {"KGM": 20, "UFG": 20, "KFR": 10, "VLA": 10, "CFL": 10, "SUN": 20, "CASH": 10}


# --- Allocation validation ---------------------------------------------------

def test_valid_allocation_sums_to_100():
    ok, why = engine.validate_allocation(DIVERSIFIED, PACK)
    assert ok, why


def test_allocation_99_and_101_rejected():
    ok99, _ = engine.validate_allocation({**DIVERSIFIED, "CASH": 9}, PACK)  # sums to 99
    ok101, _ = engine.validate_allocation({**DIVERSIFIED, "CASH": 11}, PACK)  # sums to 101
    assert not ok99
    assert not ok101


def test_unknown_share_rejected():
    ok, why = engine.validate_allocation({"ZZZ": 100}, PACK)
    assert not ok
    assert "ZZZ" in why


def test_negative_weight_rejected():
    bad = {**DIVERSIFIED, "KGM": -20, "SUN": 40}  # still sums to 100 but negative
    ok, _ = engine.validate_allocation(bad, PACK)
    assert not ok


def test_exactly_at_mandate_limit_passes_validation_and_mandate():
    at_limit = {"KGM": 40, "UFG": 30, "SUN": 20, "CASH": 10}  # 40 == max single, 10 == min cash
    ok, _ = engine.validate_allocation(at_limit, PACK)
    assert ok
    mandate = engine.check_mandate(at_limit, PACK)
    assert mandate["kept"], mandate["breaches"]


# --- Mandate compliance ------------------------------------------------------

def test_over_concentration_and_no_cash_flagged():
    mandate = engine.check_mandate({"KGM": 100}, PACK)
    assert not mandate["kept"]
    joined = " ".join(mandate["breaches"]).lower()
    assert "kgm" in joined or "concentr" in joined
    assert "cash" in joined


# --- Portfolio valuation -----------------------------------------------------

def test_diversified_round1_valuation_is_hand_computed():
    r = engine.compute_round(PACK, 1, DIVERSIFIED, CAP, CAP)
    # weighted return = .2*.06 + .2*.02 + .1*(-.04) + .1*.03 + .1*.01 + .2*.10 = .036
    assert r["portfolio_return"] == pytest.approx(0.036)
    assert r["end_value"] == pytest.approx(1_036_000)
    assert r["benchmark_return"] == pytest.approx(0.03)
    assert r["benchmark_end"] == pytest.approx(1_030_000)
    assert r["beat_benchmark"] is True


def test_hundred_percent_cash_is_flat():
    r = engine.compute_round(PACK, 1, {"CASH": 100}, CAP, CAP)
    assert r["end_value"] == pytest.approx(CAP)
    assert r["portfolio_return"] == pytest.approx(0.0)
    assert r["beat_benchmark"] is False  # benchmark was +3%


def test_all_in_one_share_matches_that_share_return():
    r = engine.compute_round(PACK, 1, {"KGM": 100}, CAP, CAP)
    assert r["portfolio_return"] == pytest.approx(0.06)
    assert r["end_value"] == pytest.approx(1_060_000)


def test_per_share_breakdown_carries_authored_why():
    r = engine.compute_round(PACK, 1, DIVERSIFIED, CAP, CAP)
    by_id = {s["id"]: s for s in r["per_share"]}
    assert "safe-haven" in by_id["KGM"]["why"].lower() or by_id["KGM"]["why"]
    # allocated value math for KGM: 20% of 1,000,000 grows 6%.
    assert by_id["KGM"]["value_start"] == pytest.approx(200_000)
    assert by_id["KGM"]["value_end"] == pytest.approx(212_000)
    assert by_id["KGM"]["change"] == pytest.approx(12_000)


# --- Event rounds ------------------------------------------------------------

def test_event_round3_reflects_authored_event_prices_and_why():
    # Round 3: KGM 122 from a round-2 base of 104 => +17.3%.
    r = engine.compute_round(PACK, 3, {"KGM": 100}, CAP, CAP)
    assert r["portfolio_return"] == pytest.approx(122 / 104 - 1)
    kgm = {s["id"]: s for s in r["per_share"]}["KGM"]
    assert "supply shock" in kgm["why"].lower()


# --- Trust updates -----------------------------------------------------------

def test_trust_rises_on_beat_and_mandate_kept():
    r = engine.compute_round(PACK, 1, DIVERSIFIED, CAP, CAP)
    trust_after, why = engine.update_trust(50.0, r, PACK)
    assert trust_after > 50.0
    assert why


def test_trust_drifts_down_on_all_cash():
    r = engine.compute_round(PACK, 1, {"CASH": 100}, CAP, CAP)
    trust_after, why = engine.update_trust(50.0, r, PACK)
    assert trust_after < 50.0


def test_trust_bounded_0_to_100():
    # Repeated disastrous rounds never go below 0.
    bad = engine.compute_round(PACK, 1, {"KGM": 100}, CAP, CAP)
    # Force a losing, breaching result by using a round where the sole share falls.
    losing = engine.compute_round(PACK, 2, {"VLA": 100}, CAP, CAP)  # VLA -8.7% in r2
    trust = 3.0
    for _ in range(10):
        trust, _ = engine.update_trust(trust, losing, PACK)
    assert trust >= 0.0

    winning = engine.compute_round(PACK, 4, {"SUN": 30, "VLA": 30, "UFG": 30, "CASH": 10}, CAP, CAP)
    trust = 98.0
    for _ in range(10):
        trust, _ = engine.update_trust(trust, winning, PACK)
    assert trust <= 100.0


# --- Determinism -------------------------------------------------------------

def test_compute_round_is_deterministic():
    a = engine.compute_round(PACK, 2, DIVERSIFIED, CAP, CAP)
    b = engine.compute_round(PACK, 2, DIVERSIFIED, CAP, CAP)
    assert a == b
