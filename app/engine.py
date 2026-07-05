"""Deterministic simulation engine — pure functions over (content pack, decisions).

No I/O, no randomness: every student faces the same authored market, so any run
is reproducible and the leaderboard is fair (plan KTD4). Every computed number
is paired with a plain-language reason so outcomes stay explainable (R2, R3).

Allocations are dicts mapping share id -> percent, plus a ``"CASH"`` key, with
percentages summing to 100.
"""

from __future__ import annotations

from app.content import CASH_ID as _CASH  # kept in one place; see below
from app.content import ContentPack

CASH = _CASH
SUM_TOLERANCE = 0.01  # allocations must sum to 100 within this tolerance


def allocation_ids(pack: ContentPack) -> list[str]:
    """Valid allocation keys: every share id plus CASH."""
    return [s.id for s in pack.shares] + [CASH]


def validate_allocation(allocation: dict, pack: ContentPack) -> tuple[bool, str]:
    """Hard validation for form submission: valid keys, non-negative, sums to 100.

    Mandate compliance (concentration, cash floor) is *not* checked here — a
    student may submit a mandate-breaching allocation; the breach is surfaced
    and scored, not blocked (plan U4).
    """
    valid_keys = set(allocation_ids(pack))
    for key in allocation:
        if key not in valid_keys:
            return False, f"'{key}' is not a valid holding."
    for key, pct in allocation.items():
        try:
            value = float(pct)
        except (TypeError, ValueError):
            return False, f"Allocation for '{key}' must be a number."
        if value < 0:
            return False, f"Allocation for '{key}' cannot be negative."
    total = sum(float(v) for v in allocation.values())
    if abs(total - 100.0) > SUM_TOLERANCE:
        return False, f"Allocations must sum to 100% — they currently total {total:g}%."
    return True, "Allocation totals 100%."


def check_mandate(allocation: dict, pack: ContentPack) -> dict:
    """Soft mandate compliance: single-share concentration and the cash floor."""
    mandate = pack.client.mandate
    breaches: list[str] = []

    for key, pct in allocation.items():
        if key == CASH:
            continue
        if float(pct) > mandate.max_single_share_pct:
            share = pack.share_by_id(key)
            breaches.append(
                f"Over-concentrated in {share.name} ({float(pct):g}% > "
                f"{mandate.max_single_share_pct:g}% limit)."
            )

    cash_pct = float(allocation.get(CASH, 0))
    if cash_pct < mandate.min_cash_pct:
        breaches.append(
            f"Held only {cash_pct:g}% cash (mandate requires at least "
            f"{mandate.min_cash_pct:g}%)."
        )

    kept = not breaches
    why = (
        "Stayed within the client's mandate — diversified, with cash on hand."
        if kept
        else "Broke the client's mandate: " + " ".join(breaches)
    )
    return {"kept": kept, "breaches": breaches, "why": why}


def compute_round(
    pack: ContentPack,
    round_number: int,
    allocation: dict,
    start_value: float,
    benchmark_start: float,
) -> dict:
    """Value one round from the authored price paths.

    ``start_value`` / ``benchmark_start`` are the portfolio and benchmark values
    at the *start* of this round (threaded by the caller — round 1 uses the
    starting capital). Returns a fully explained results dict.
    """
    per_share = []
    weighted_return = 0.0
    for share in pack.shares:
        weight_pct = float(allocation.get(share.id, 0))
        weight = weight_pct / 100.0
        share_return = share.return_in_round(round_number)
        weighted_return += weight * share_return
        value_start = start_value * weight
        value_end = value_start * (1 + share_return)
        per_share.append(
            {
                "id": share.id,
                "name": share.name,
                "sector": share.sector,
                "weight_pct": weight_pct,
                "share_return": share_return,
                "value_start": value_start,
                "value_end": value_end,
                "change": value_end - value_start,
                "why": share.why_for_round(round_number),
            }
        )

    cash_pct = float(allocation.get(CASH, 0))
    end_value = start_value * (1 + weighted_return)
    portfolio_return = weighted_return  # cash contributes zero return

    benchmark_return = pack.benchmark_return_in_round(round_number)
    benchmark_end = benchmark_start * (1 + benchmark_return)

    mandate = check_mandate(allocation, pack)
    events = [
        {"id": e.id, "title": e.title, "narrative": e.narrative}
        for e in pack.events_for_round(round_number)
    ]

    return {
        "round": round_number,
        "start_value": start_value,
        "end_value": end_value,
        "portfolio_return": portfolio_return,
        "benchmark_start": benchmark_start,
        "benchmark_end": benchmark_end,
        "benchmark_return": benchmark_return,
        "beat_benchmark": portfolio_return > benchmark_return,
        "cash_pct": cash_pct,
        "per_share": per_share,
        "mandate": mandate,
        "events": events,
    }


# Trust movement weights — tuned so a disciplined, market-beating round lifts
# trust and a reckless or losing one erodes it. All deterministic (R9).
_TRUST_BEAT = 8.0
_TRUST_TRAIL = -6.0
_TRUST_MANDATE_KEPT = 4.0
_TRUST_MANDATE_BREACH = -10.0
_TRUST_LOSS = -4.0          # applied when the quarter loses real value
_TRUST_STRONG_GAIN = 3.0    # applied on a strong positive quarter
_TRUST_IDLE_CASH = -3.0     # applied when too much capital sits idle
_LOSS_THRESHOLD = -0.03
_STRONG_GAIN_THRESHOLD = 0.05
_IDLE_CASH_THRESHOLD = 50.0


def update_trust(trust_before: float, results: dict, pack: ContentPack) -> tuple[float, str]:
    """Move client trust from a round's results, bounded to [0, 100], with a why."""
    delta = 0.0
    reasons: list[str] = []

    if results["beat_benchmark"]:
        delta += _TRUST_BEAT
        reasons.append(f"beat the market (+{_TRUST_BEAT:g})")
    else:
        delta += _TRUST_TRAIL
        reasons.append(f"trailed the market ({_TRUST_TRAIL:g})")

    if results["mandate"]["kept"]:
        delta += _TRUST_MANDATE_KEPT
        reasons.append(f"honoured the mandate (+{_TRUST_MANDATE_KEPT:g})")
    else:
        delta += _TRUST_MANDATE_BREACH
        reasons.append(f"broke the mandate ({_TRUST_MANDATE_BREACH:g})")

    pr = results["portfolio_return"]
    if pr <= _LOSS_THRESHOLD:
        delta += _TRUST_LOSS
        reasons.append(f"lost value this quarter ({_TRUST_LOSS:g})")
    elif pr >= _STRONG_GAIN_THRESHOLD:
        delta += _TRUST_STRONG_GAIN
        reasons.append(f"strong gains (+{_TRUST_STRONG_GAIN:g})")

    if results["cash_pct"] > _IDLE_CASH_THRESHOLD:
        delta += _TRUST_IDLE_CASH
        reasons.append(f"left too much cash idle ({_TRUST_IDLE_CASH:g})")

    trust_after = max(0.0, min(100.0, trust_before + delta))
    direction = "rose" if trust_after >= trust_before else "fell"
    why = (
        f"Client trust {direction} from {trust_before:g} to {trust_after:g}: "
        + "; ".join(reasons)
        + "."
    )
    return trust_after, why
