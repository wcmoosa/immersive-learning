"""Content pack loader + validation tests (U2)."""

from __future__ import annotations

import copy
import os
import tempfile

import pytest
import yaml

from app.content import BADGE_IDS, ContentError, load_content_pack

# A minimal-but-valid pack used to probe validation error paths.
VALID_RAW = {
    "title": "Test Market",
    "currency": "ZAR",
    "starting_capital": 1000000,
    "total_rounds": 2,
    "starting_trust": 50,
    "client": {
        "name": "Test Client",
        "persona": "A test persona.",
        "mandate": {
            "summary": "Grow steadily.",
            "risk_tolerance": "moderate",
            "max_single_share_pct": 40,
            "min_cash_pct": 10,
        },
    },
    "shares": [
        {
            "id": "AAA",
            "name": "Alpha",
            "sector": "Mining",
            "start_price": 100,
            "rounds": [{"price": 110, "why": "up"}, {"price": 121, "why": "up more"}],
        },
        {
            "id": "BBB",
            "name": "Beta",
            "sector": "Banking",
            "start_price": 50,
            "rounds": [{"price": 45, "why": "down"}, {"price": 45, "why": "flat"}],
        },
    ],
    "events": [
        {"id": "evt", "round": 2, "title": "T", "narrative": "N", "affected_shares": ["AAA"]},
    ],
    "briefs": [
        {"round": 1, "headline": "H1", "body": "B1", "sector_news": ["x"]},
        {"round": 2, "headline": "H2", "body": "B2"},
    ],
    "fallback": {
        "feedback": {
            "beat_kept": "a",
            "beat_breached": "b",
            "trailed_kept": "c",
            "trailed_breached": "d",
        },
        "reflection_prompts": ["p1", "p2"],
        "badge_citations": {badge_id: f"citation for {badge_id}" for badge_id in BADGE_IDS},
    },
}


def _load_from(raw: dict):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(raw, fh)
        return load_content_pack(path)
    finally:
        os.remove(path)


# --- Happy path: the shipped pack --------------------------------------------

def test_shipped_pack_loads_with_six_shares_and_four_rounds():
    pack = load_content_pack()  # default shipped path
    assert len(pack.shares) == 6
    assert pack.total_rounds == 4
    for share in pack.shares:
        assert len(share.rounds) == 4
    assert pack.currency == "ZAR"
    assert pack.starting_capital == 1000000


def test_shipped_pack_has_one_share_per_sa_sector():
    pack = load_content_pack()
    sectors = set(pack.sectors)
    assert {"Mining", "Banking", "Food retail", "Telecoms", "Logistics", "Renewable energy"} <= sectors


def test_share_return_helpers_match_prices():
    pack = load_content_pack()
    kgm = pack.share_by_id("KGM")
    assert kgm.return_in_round(1) == pytest.approx(0.06)  # 106 / 100 - 1
    # round 3 return uses the round-2 end price as its base (122 / 104 - 1).
    assert kgm.return_in_round(3) == pytest.approx(122 / 104 - 1)


def test_benchmark_is_equal_weight_average():
    pack = load_content_pack()
    expected = sum(s.return_in_round(1) for s in pack.shares) / 6
    assert pack.benchmark_return_in_round(1) == pytest.approx(expected)


# --- Error paths -------------------------------------------------------------

def test_valid_minimal_pack_loads():
    pack = _load_from(copy.deepcopy(VALID_RAW))
    assert len(pack.shares) == 2


def test_missing_round_price_fails_naming_the_share():
    raw = copy.deepcopy(VALID_RAW)
    raw["shares"][0]["rounds"] = [{"price": 110, "why": "only one round"}]  # needs 2
    with pytest.raises(ContentError) as exc:
        _load_from(raw)
    assert "AAA" in str(exc.value)
    assert "total_rounds" in str(exc.value) or "round" in str(exc.value)


def test_event_referencing_unknown_share_fails():
    raw = copy.deepcopy(VALID_RAW)
    raw["events"][0]["affected_shares"] = ["ZZZ"]
    with pytest.raises(ContentError) as exc:
        _load_from(raw)
    assert "ZZZ" in str(exc.value)
    assert "evt" in str(exc.value)


def test_missing_fallback_category_fails():
    raw = copy.deepcopy(VALID_RAW)
    del raw["fallback"]["feedback"]["beat_kept"]
    with pytest.raises(ContentError) as exc:
        _load_from(raw)
    assert "beat_kept" in str(exc.value)


def test_missing_badge_citation_fails():
    raw = copy.deepcopy(VALID_RAW)
    del raw["fallback"]["badge_citations"]["mandate_keeper"]
    with pytest.raises(ContentError) as exc:
        _load_from(raw)
    assert "mandate_keeper" in str(exc.value)


def test_missing_brief_for_a_round_fails():
    raw = copy.deepcopy(VALID_RAW)
    raw["briefs"] = [b for b in raw["briefs"] if b["round"] != 2]
    with pytest.raises(ContentError) as exc:
        _load_from(raw)
    assert "round 2" in str(exc.value)


def test_missing_file_fails_cleanly():
    with pytest.raises(ContentError) as exc:
        load_content_pack("/no/such/pack.yaml")
    assert "not found" in str(exc.value)
