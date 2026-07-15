"""Seed a fictional completed cohort so the leaderboard and lecturer view look
alive before the live demo run starts (plan U8).

Each demo run is played through the *real* engine, scoring, and canned feedback
service — so the seeded data is identical in shape and logic to a live run,
never hand-faked numbers.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app import badges as badges_mod
from app import engine, scoring
from app.content import load_content_pack
from app.feedback import CannedFeedbackService
from app.models import (
    STATUS_COMPLETED,
    STEP_SUMMARY,
    FeedbackRecord,
    Reflection,
    Run,
    RoundDecision,
    User,
)

_PACK = load_content_pack()


def _forecast_from_allocation(allocation: dict) -> dict:
    invested = sum(v for k, v in allocation.items() if k != "CASH")
    baseline = invested / len(_PACK.shares) if _PACK.shares else 0
    directions = {}
    for share in _PACK.shares:
        w = allocation.get(share.id, 0)
        directions[share.id] = "up" if w >= baseline and w > 0 else "flat"
    return {"directions": directions, "rationale": "Positioned toward the sectors I expect to lead."}


# (username, display_name, [allocation per round], [reflection per round])
_PERSONAS = [
    (
        "nomvula",
        "Nomvula Zulu",
        [
            {"KGM": 15, "UFG": 15, "KFR": 10, "VLA": 15, "CFL": 10, "SUN": 25, "CASH": 10},
            {"KGM": 10, "UFG": 35, "KFR": 5, "VLA": 10, "CFL": 10, "SUN": 10, "CASH": 20},
            {"KGM": 35, "UFG": 20, "KFR": 10, "VLA": 10, "CFL": 5, "SUN": 10, "CASH": 10},
            {"KGM": 15, "UFG": 20, "KFR": 10, "VLA": 25, "CFL": 10, "SUN": 10, "CASH": 10},
        ],
        [
            "I leaned into renewables because load-shedding is clearly driving demand, but kept the portfolio spread so no single call could sink the client.",
            "The rate hike made banks the obvious winners, so I overweighted Umzansi while keeping a healthy cash buffer for safety.",
            "The supply shock was a gift for gold, so I rotated into Kalahari while trimming the freight names that would suffer.",
            "For the final quarter I backed the rebound in telecoms and stayed diversified to protect the year's gains for Mrs Dlamini.",
        ],
    ),
    (
        "sipho",
        "Sipho Ndlovu",
        [
            {"SUN": 80, "CASH": 20},
            {"UFG": 90, "CASH": 10},
            {"KGM": 95, "CASH": 5},
            {"VLA": 100},
        ],
        [
            "Went big on solar.",
            "All in on banks after the hike.",
            "Gold was spiking so I bet the lot.",
            "Telecoms to finish.",
        ],
    ),
    (
        "fatima",
        "Fatima Adams",
        [
            {"UFG": 20, "KFR": 20, "CASH": 60},
            {"UFG": 25, "KFR": 15, "CASH": 60},
            {"KGM": 20, "UFG": 20, "CASH": 60},
            {"UFG": 20, "SUN": 20, "CASH": 60},
        ],
        [
            "I kept most of it in cash because I was nervous about losing the client's money.",
            "Still cautious — I don't fully trust the market yet.",
            "Held back again during the supply shock; it felt too risky.",
            "Played it safe all year. Maybe too safe, looking at the returns.",
        ],
    ),
    (
        "johan",
        "Johan van der Merwe",
        [
            {"KGM": 15, "UFG": 15, "KFR": 15, "VLA": 15, "CFL": 15, "SUN": 15, "CASH": 10},
            {"SUN": 40, "UFG": 20, "KGM": 10, "VLA": 10, "KFR": 5, "CFL": 5, "CASH": 10},
            {"UFG": 40, "SUN": 15, "KGM": 15, "VLA": 10, "KFR": 5, "CFL": 5, "CASH": 10},
            {"KGM": 40, "UFG": 20, "VLA": 10, "SUN": 10, "KFR": 5, "CFL": 5, "CASH": 10},
        ],
        [
            "Started evenly spread to see how the market behaved.",
            "Chased solar since it was last quarter's winner.",
            "Rotated into banks after they led — following the momentum.",
            "Backed gold after its big run, though it cooled off on me.",
        ],
    ),
    (
        "lerato",
        "Lerato Mkhize",
        [
            {"KGM": 15, "UFG": 15, "KFR": 10, "VLA": 15, "CFL": 10, "SUN": 20, "CASH": 15},
            {"KGM": 10, "UFG": 30, "KFR": 10, "VLA": 10, "CFL": 10, "SUN": 10, "CASH": 20},
            {"KGM": 30, "UFG": 20, "KFR": 10, "VLA": 10, "CFL": 10, "SUN": 10, "CASH": 10},
            {"KGM": 15, "UFG": 20, "KFR": 10, "VLA": 20, "CFL": 10, "SUN": 15, "CASH": 10},
        ],
        [
            "Balanced start with a tilt to renewables, holding some cash back for flexibility.",
            "Tilted to banks for the rate hike but stayed broadly diversified.",
            "Added gold for the supply shock while keeping the rest of the book intact.",
            "Finished balanced, happy with a steady year that respected the mandate.",
        ],
    ),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _simulate_run(session, user: User, allocations: list[dict], reflections: list[str]) -> Run:
    canned = CannedFeedbackService(_PACK)
    run = Run(
        user_id=user.id,
        status=STATUS_COMPLETED,
        current_round=_PACK.total_rounds,
        current_step=STEP_SUMMARY,
        client_trust=_PACK.starting_trust,
        started_at=_now(),
        completed_at=_now(),
    )
    session.add(run)
    session.flush()

    start_value = _PACK.starting_capital
    benchmark = _PACK.starting_capital
    for r in range(1, _PACK.total_rounds + 1):
        allocation = allocations[r - 1]
        forecast = _forecast_from_allocation(allocation)
        results = engine.compute_round(_PACK, r, allocation, start_value, benchmark)
        trust_after, trust_why = engine.update_trust(run.client_trust, results, _PACK)
        results["trust_why"] = trust_why

        session.add(
            RoundDecision(
                run_id=run.id, round_number=r, forecast=forecast, allocation=allocation,
                results=results, portfolio_value=results["end_value"],
                benchmark_value=results["benchmark_end"], trust_before=run.client_trust,
                trust_after=trust_after,
            )
        )
        fb = canned.round_feedback(round_number=r, allocation=allocation, forecast=forecast, results=results)
        session.add(FeedbackRecord(run_id=run.id, round_number=r, text=fb.text, source=fb.source))

        badges_mod.award_round_badges(
            run, round_number=r, allocation=allocation, forecast=forecast,
            results=results, pack=_PACK,
        )

        text = reflections[r - 1]
        indic, indic_why = canned.rate_reflection(text=text)
        session.add(
            Reflection(run_id=run.id, round_number=r, text=text, indicative_rating=indic, indicative_why=indic_why)
        )

        run.client_trust = trust_after
        start_value = results["end_value"]
        benchmark = results["benchmark_end"]

    run.final_value = start_value
    run.benchmark_value = benchmark
    session.flush()
    scoring.finalize_run(session, run, _PACK)

    badges_mod.award_run_badges(
        run,
        decisions=sorted(run.decisions, key=lambda d: d.round_number),
        reflections=sorted(run.reflections, key=lambda r: r.round_number),
        pack=_PACK,
    )
    # Citations for the seeded cohort come from the authored pack, never a live
    # API call — seeding must work offline and produce identical data every time.
    for badge in list(run.badges or []):
        citation = canned.badge_citation(
            badge_id=badge["id"], badge_name=badge["name"], badge_why=badge["why"]
        )
        badges_mod.set_citation(run, badge["id"], citation.text, citation.source)
    return run


def seed_demo_runs(session_factory) -> None:
    """Create the fictional cohort. Idempotent — skips if already present."""
    with session_factory() as session:
        already = session.query(User).filter(User.username == _PERSONAS[0][0]).first()
        if already is not None:
            return
        for username, display, allocations, reflections in _PERSONAS:
            user = User(username=username, password="demo", role="student", display_name=display)
            session.add(user)
            session.flush()
            _simulate_run(session, user, allocations, reflections)
        session.commit()
