"""Composite performance model — transparent, deterministic scoring (U6).

Every component is a small pure function returning ``(score_0_100, why)``. The
``why`` string is shown in the UI: this is the "explainable, academically
approvable logic" made visible (plan KTD6, R8).

Critically, **no LLM output ever enters a score**. Reflection quality is a
deterministic engagement heuristic; U5's LLM indicative rating is displayed
beside it as a labelled annotation only. This keeps every score reproducible
and the "AI never determines scores" pitch literally true.
"""

from __future__ import annotations

from app.content import CASH_ID, ContentPack
from app.engine import check_mandate
from app.models import Reflection, Run, RoundDecision

# Composite weights. Decisions are weighted like outcomes to reinforce
# "reasoning matters, not just returns" (plan U6). Surfaced in the UI.
DECISION_WEIGHT = 0.4
REFLECTION_WEIGHT = 0.2
OUTCOME_WEIGHT = 0.4

# Outcome scaling: ±10% of excess return over the benchmark spans the full
# 0-100 range, centred on 50 when the run exactly matches the market.
_OUTCOME_CENTRE = 50.0
_OUTCOME_SCALE = 500.0

_MIN_REFLECTION_WORDS = 5


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# --- Individual components ---------------------------------------------------

def diversification_score(allocation: dict, pack: ContentPack) -> tuple[float, str]:
    """Higher when capital is spread across holdings (Herfindahl-based)."""
    slots = len(pack.shares) + 1  # shares + cash
    hhi = sum((float(v) / 100.0) ** 2 for v in allocation.values())
    if hhi <= 0:
        return 0.0, "Nothing was allocated."
    effective = 1.0 / hhi
    score = _clamp((effective - 1.0) / (slots - 1.0) * 100.0)
    return score, f"Spread across the equivalent of {effective:.1f} equal holdings."


def mandate_score(allocation: dict, pack: ContentPack) -> tuple[float, str]:
    """100 when the mandate is honoured; penalised per breach."""
    result = check_mandate(allocation, pack)
    if result["kept"]:
        return 100.0, "Stayed within the client's mandate."
    score = _clamp(100.0 - 40.0 * len(result["breaches"]))
    return score, "Broke the mandate: " + " ".join(result["breaches"])


def consistency_score(forecast: dict, allocation: dict, pack: ContentPack) -> tuple[float, str]:
    """Reward allocations that align with the student's own sector forecast."""
    directions = (forecast or {}).get("directions", {}) if forecast else {}
    invested = sum(float(allocation.get(s.id, 0)) for s in pack.shares)
    baseline = invested / len(pack.shares) if pack.shares else 0.0

    considered = 0
    aligned = 0
    for share in pack.shares:
        d = directions.get(share.id, "flat")
        if d == "flat":
            continue
        considered += 1
        weight = float(allocation.get(share.id, 0))
        if d == "up" and weight >= baseline:
            aligned += 1
        elif d == "down" and weight <= baseline:
            aligned += 1

    if considered == 0:
        return 50.0, "No directional calls to align against — a neutral reading."
    score = aligned / considered * 100.0
    return score, f"Your allocation matched {aligned} of {considered} sector calls."


def reflection_score(text: str) -> tuple[float, str]:
    """Deterministic engagement heuristic — never uses any LLM output."""
    words = len((text or "").split())
    if words < _MIN_REFLECTION_WORDS:
        return 10.0, "Too brief to show engagement."
    score = _clamp(20.0 + words * 3.0)
    return score, f"A {words}-word reflection shows engagement with the round."


def outcome_score(total_return: float, benchmark_return: float) -> tuple[float, str]:
    """Return vs benchmark, scaled; exactly matching the market lands mid-scale."""
    excess = total_return - benchmark_return
    score = _clamp(_OUTCOME_CENTRE + excess * _OUTCOME_SCALE)
    verb = "beat" if excess > 0 else ("matched" if excess == 0 else "trailed")
    return score, (
        f"Your {total_return * 100:+.1f}% {verb} the market's "
        f"{benchmark_return * 100:+.1f}% ({excess * 100:+.1f}% difference)."
    )


# --- Aggregation -------------------------------------------------------------

def decision_quality(rounds: list[dict], pack: ContentPack) -> tuple[float, str]:
    """Average of diversification, mandate compliance, and forecast consistency."""
    if not rounds:
        return 0.0, "No decisions to assess."
    divs, mands, cons = [], [], []
    for rnd in rounds:
        allocation = rnd.get("allocation") or {}
        forecast = rnd.get("forecast") or {}
        divs.append(diversification_score(allocation, pack)[0])
        mands.append(mandate_score(allocation, pack)[0])
        cons.append(consistency_score(forecast, allocation, pack)[0])
    d = sum(divs) / len(divs)
    m = sum(mands) / len(mands)
    c = sum(cons) / len(cons)
    score = (d + m + c) / 3.0
    why = (
        f"Diversification {d:.0f}/100, mandate discipline {m:.0f}/100, and "
        f"forecast consistency {c:.0f}/100, averaged across your rounds."
    )
    return score, why


def composite_score(decision: float, reflection: float, outcome: float) -> float:
    return _clamp(
        decision * DECISION_WEIGHT + reflection * REFLECTION_WEIGHT + outcome * OUTCOME_WEIGHT
    )


def finalize_run(session, run: Run, pack: ContentPack) -> None:
    """Compute and persist the composite breakdown when a run completes."""
    decisions = (
        session.query(RoundDecision)
        .filter(RoundDecision.run_id == run.id)
        .order_by(RoundDecision.round_number)
        .all()
    )
    reflections = (
        session.query(Reflection)
        .filter(Reflection.run_id == run.id)
        .order_by(Reflection.round_number)
        .all()
    )

    # Deterministic per-reflection quality (stored for the lecturer view too).
    for reflection in reflections:
        qs, qw = reflection_score(reflection.text or "")
        reflection.quality_score = qs
        reflection.quality_why = qw

    rounds = [{"allocation": d.allocation, "forecast": d.forecast} for d in decisions]
    decision, decision_why = decision_quality(rounds, pack)

    if reflections:
        reflection_component = sum(r.quality_score or 0 for r in reflections) / len(reflections)
    else:
        reflection_component = 0.0
    reflection_why = f"Average engagement across {len(reflections)} reflections."

    total_return = (run.final_value / pack.starting_capital - 1) if run.final_value else 0.0
    bench_return = (run.benchmark_value / pack.starting_capital - 1) if run.benchmark_value else 0.0
    outcome, outcome_why = outcome_score(total_return, bench_return)

    composite = composite_score(decision, reflection_component, outcome)

    # Aggregate LLM indicative reading — display only, never part of the score.
    rated = [r.indicative_rating for r in reflections if r.indicative_rating is not None]
    indicative = None
    if rated:
        indicative = {
            "rating": sum(rated) / len(rated),
            "why": "AI-assisted reading averaged across your reflections.",
        }

    run.composite_score = composite
    run.composite_breakdown = {
        "composite": composite,
        "weights": {
            "decision": DECISION_WEIGHT,
            "reflection": REFLECTION_WEIGHT,
            "outcome": OUTCOME_WEIGHT,
        },
        "components": [
            {"key": "decision", "label": "Decision quality", "score": decision, "weight": DECISION_WEIGHT, "why": decision_why},
            {
                "key": "reflection",
                "label": "Reflection quality",
                "score": reflection_component,
                "weight": REFLECTION_WEIGHT,
                "why": reflection_why,
                "indicative": indicative,
            },
            {"key": "outcome", "label": "Outcome (return vs benchmark)", "score": outcome, "weight": OUTCOME_WEIGHT, "why": outcome_why},
        ],
    }


def leaderboard(session) -> list[dict]:
    """Completed runs ranked by composite score, best first."""
    from app.models import STATUS_COMPLETED, User

    runs = (
        session.query(Run)
        .filter(Run.status == STATUS_COMPLETED, Run.composite_score.isnot(None))
        .order_by(Run.composite_score.desc())
        .all()
    )
    rows = []
    for rank, run in enumerate(runs, start=1):
        user = session.get(User, run.user_id)
        rows.append(
            {
                "rank": rank,
                "run_id": run.id,
                "user_id": run.user_id,
                "name": user.display_name if user else "Unknown",
                "composite": run.composite_score,
                "final_value": run.final_value,
                "trust": run.client_trust,
            }
        )
    return rows
