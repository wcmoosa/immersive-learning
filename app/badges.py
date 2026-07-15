"""Analyst credentials — deterministic, rule-awarded badges (U9).

The gamification layer that sits *beside* the score, never inside it. Every
badge is awarded by a pure rule over the student's own decisions and the
rule-based results; no LLM output can earn, withhold, or alter one. The AI's
only job is to write the one-line **citation** that accompanies an award (see
``FeedbackService.badge_citation``) — words, never marks.

That split is the demo's whole integrity story rendered on a single card: the
rule says *why* the credential was earned, the AI says it beautifully.

Badges never enter ``composite_score``. They are display-only recognition.

Two scopes:

* **round** — evaluated the moment a round's results are computed.
* **run**   — evaluated once, when the run is finalised.

Each rule returns a plain-language ``why`` when earned, or ``None``. Badges are
awarded at most once per run (deduplicated by id).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.content import ContentPack
from app.models import Reflection, Run, RoundDecision
from app.scoring import diversification_score

# Thresholds — tuned so a typical strong run earns three or four credentials and
# a careless one earns almost none. All deterministic (R9, KTD4).
_TRUSTED_ADVISOR_TRUST = 75.0
_DIVERSIFIER_AVG_SCORE = 70.0
_DEEP_THINKER_MIN_WORDS = 20
_SHARP_READ_MIN_CALLS = 2

SCOPE_ROUND = "round"
SCOPE_RUN = "run"


@dataclass(frozen=True)
class Badge:
    id: str
    name: str
    icon: str
    scope: str
    blurb: str  # what it takes to earn it — shown to the student


# --- Round-scope rules -------------------------------------------------------
# Signature: (round_number, allocation, forecast, results, pack) -> why | None


def _market_beater(round_number, allocation, forecast, results, pack) -> str | None:
    """Beat the market — but only counts if the mandate held."""
    if not (results["beat_benchmark"] and results["mandate"]["kept"]):
        return None
    return (
        f"Returned {results['portfolio_return'] * 100:+.1f}% against the market's "
        f"{results['benchmark_return'] * 100:+.1f}% in round {round_number}, "
        "without stepping outside the client's mandate."
    )


def _crisis_navigator(round_number, allocation, forecast, results, pack) -> str | None:
    """Beat the market in a round where a scenario event struck."""
    events = results.get("events") or []
    if not events or not results["beat_benchmark"]:
        return None
    titles = "; ".join(e["title"] for e in events)
    return (
        f"Beat the market in round {round_number} — the quarter of the "
        f"{titles.lower()} — when the shock knocked others off course."
    )


def _sharp_read(round_number, allocation, forecast, results, pack) -> str | None:
    """Every directional sector call made this round proved correct."""
    directions = (forecast or {}).get("directions") or {}
    moves = {s["id"]: s["share_return"] for s in results["per_share"]}

    calls = 0
    for share_id, direction in directions.items():
        if direction not in ("up", "down"):
            continue
        if share_id not in moves:
            continue
        calls += 1
        actual = moves[share_id]
        if direction == "up" and actual <= 0:
            return None
        if direction == "down" and actual >= 0:
            return None

    if calls < _SHARP_READ_MIN_CALLS:
        return None
    return f"Called all {calls} directional sector moves correctly in round {round_number}."


# --- Run-scope rules ---------------------------------------------------------
# Signature: (run, decisions, reflections, pack) -> why | None


def _mandate_keeper(run, decisions, reflections, pack) -> str | None:
    """Never once breached the client's mandate across the full year."""
    if len(decisions) < pack.total_rounds:
        return None
    for d in decisions:
        if not (d.results or {}).get("mandate", {}).get("kept"):
            return None
    return (
        f"Honoured {pack.client.name}'s mandate in all {pack.total_rounds} quarters — "
        "never over-concentrated, never short of cash."
    )


def _trusted_advisor(run, decisions, reflections, pack) -> str | None:
    """Finished the year with the client's confidence high."""
    trust = run.client_trust or 0.0
    if trust < _TRUSTED_ADVISOR_TRUST:
        return None
    return (
        f"Closed the year with {pack.client.name}'s trust at {trust:.0f}/100 — "
        "she would hand this analyst more of her money."
    )


def _alpha_generator(run, decisions, reflections, pack) -> str | None:
    """Beat the benchmark over the whole year, not just a lucky quarter."""
    if run.final_value is None or run.benchmark_value is None:
        return None
    if run.final_value <= run.benchmark_value:
        return None
    total = run.final_value / pack.starting_capital - 1
    bench = run.benchmark_value / pack.starting_capital - 1
    return (
        f"Ended the year at {run.final_value:,.0f} ({total * 100:+.1f}%) against the "
        f"market's {bench * 100:+.1f}% — {(total - bench) * 100:+.1f}% of genuine alpha."
    )


def _diversifier(run, decisions, reflections, pack) -> str | None:
    """Spread the client's risk consistently, quarter after quarter."""
    if not decisions:
        return None
    scores = [diversification_score(d.allocation or {}, pack)[0] for d in decisions]
    average = sum(scores) / len(scores)
    if average < _DIVERSIFIER_AVG_SCORE:
        return None
    return (
        f"Averaged {average:.0f}/100 on diversification across the year — risk spread, "
        "never riding on a single company."
    )


def _deep_thinker(run, decisions, reflections, pack) -> str | None:
    """Wrote a substantial reflection after every single round."""
    if len(reflections) < pack.total_rounds:
        return None
    counts = [len((r.text or "").split()) for r in reflections]
    if min(counts) < _DEEP_THINKER_MIN_WORDS:
        return None
    return (
        f"Reflected in depth after every quarter — {sum(counts)} words of reasoning "
        "about their own decisions."
    )


# --- The catalog -------------------------------------------------------------
# Order here is the order badges are displayed.

CATALOG: list[Badge] = [
    Badge(
        id="market_beater",
        name="Market Beater",
        icon="📈",
        scope=SCOPE_ROUND,
        blurb="Beat the benchmark in a round while keeping the mandate.",
    ),
    Badge(
        id="crisis_navigator",
        name="Crisis Navigator",
        icon="🧭",
        scope=SCOPE_ROUND,
        blurb="Beat the benchmark in a round when a market shock hit.",
    ),
    Badge(
        id="sharp_read",
        name="Sharp Read",
        icon="🎯",
        scope=SCOPE_ROUND,
        blurb="Get every directional sector call in a round right.",
    ),
    Badge(
        id="mandate_keeper",
        name="Mandate Keeper",
        icon="🛡️",
        scope=SCOPE_RUN,
        blurb="Never breach the client's mandate, in any round.",
    ),
    Badge(
        id="alpha_generator",
        name="Alpha Generator",
        icon="🏆",
        scope=SCOPE_RUN,
        blurb="Finish the year ahead of the market benchmark.",
    ),
    Badge(
        id="trusted_advisor",
        name="Trusted Advisor",
        icon="🤝",
        scope=SCOPE_RUN,
        blurb=f"Finish with the client's trust at {_TRUSTED_ADVISOR_TRUST:.0f} or above.",
    ),
    Badge(
        id="diversifier",
        name="Diversifier",
        icon="🧩",
        scope=SCOPE_RUN,
        blurb="Keep the portfolio well spread across the whole year.",
    ),
    Badge(
        id="deep_thinker",
        name="Deep Thinker",
        icon="💭",
        scope=SCOPE_RUN,
        blurb="Write a substantial reflection after every round.",
    ),
]

_ROUND_RULES: dict[str, Callable] = {
    "market_beater": _market_beater,
    "crisis_navigator": _crisis_navigator,
    "sharp_read": _sharp_read,
}

_RUN_RULES: dict[str, Callable] = {
    "mandate_keeper": _mandate_keeper,
    "alpha_generator": _alpha_generator,
    "trusted_advisor": _trusted_advisor,
    "diversifier": _diversifier,
    "deep_thinker": _deep_thinker,
}


def badge_by_id(badge_id: str) -> Badge:
    for badge in CATALOG:
        if badge.id == badge_id:
            return badge
    raise KeyError(badge_id)


# --- Awarding ----------------------------------------------------------------


def _record(badge: Badge, why: str, round_number: int | None) -> dict:
    """The persisted shape of an earned badge.

    ``citation`` is filled in lazily by the feedback service (AI or authored);
    a badge is fully valid — earned, explained, displayable — without one.
    """
    return {
        "id": badge.id,
        "name": badge.name,
        "icon": badge.icon,
        "scope": badge.scope,
        "round": round_number,
        "why": why,
        "citation": None,
        "citation_source": None,
    }


def earned_ids(run: Run) -> set[str]:
    return {b["id"] for b in (run.badges or [])}


def _append(run: Run, new: list[dict]) -> None:
    # Reassign rather than mutate: SQLAlchemy does not track in-place changes to
    # a JSON column, so an ``.append()`` here would silently never persist.
    run.badges = list(run.badges or []) + new


def award_round_badges(
    run: Run,
    *,
    round_number: int,
    allocation: dict,
    forecast: dict,
    results: dict,
    pack: ContentPack,
) -> list[dict]:
    """Evaluate the round-scope rules and award any newly earned badges."""
    already = earned_ids(run)
    new: list[dict] = []
    for badge in CATALOG:
        if badge.scope != SCOPE_ROUND or badge.id in already:
            continue
        why = _ROUND_RULES[badge.id](round_number, allocation, forecast, results, pack)
        if why:
            new.append(_record(badge, why, round_number))
    _append(run, new)
    return new


def award_run_badges(
    run: Run,
    *,
    decisions: list[RoundDecision],
    reflections: list[Reflection],
    pack: ContentPack,
) -> list[dict]:
    """Evaluate the run-scope rules at completion and award what was earned."""
    already = earned_ids(run)
    new: list[dict] = []
    for badge in CATALOG:
        if badge.scope != SCOPE_RUN or badge.id in already:
            continue
        why = _RUN_RULES[badge.id](run, decisions, reflections, pack)
        if why:
            new.append(_record(badge, why, None))
    _append(run, new)
    return new


def badges_for_round(run: Run, round_number: int) -> list[dict]:
    return [b for b in (run.badges or []) if b.get("round") == round_number]


def set_citation(run: Run, badge_id: str, citation: str, source: str) -> None:
    """Attach a generated citation to an earned badge (reassigns for JSON tracking)."""
    updated = []
    for badge in run.badges or []:
        if badge["id"] == badge_id:
            badge = {**badge, "citation": citation, "citation_source": source}
        updated.append(badge)
    run.badges = updated
