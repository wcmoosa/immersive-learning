"""FastAPI application: routes, session auth, and page rendering.

U1 establishes the shell — app wiring, session middleware, login/logout, the
student dashboard, and a lecturer landing. The student round flow (U4),
scoring/leaderboard surface (U6), and full lecturer view (U7) extend this file.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app import engine
from app.auth import (
    authenticate,
    get_current_user,
    login_user,
    logout_user,
    require_role,
    require_user,
)
from app.content import CASH_ID, load_content_pack
from app.db import get_session
from app.feedback import get_feedback_service
from app.models import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STEP_ALLOCATION,
    STEP_BRIEFING,
    STEP_FORECAST,
    STEP_REFLECTION,
    STEP_RESULTS,
    STEP_SUMMARY,
    TOTAL_ROUNDS,
    FeedbackRecord,
    Reflection,
    RoundDecision,
    Run,
    User,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# The scenario pack and feedback service are loaded once at startup. The
# feedback service picks OpenAI when a key is present, else the canned path.
PACK = load_content_pack()
FEEDBACK = get_feedback_service(PACK)

# Where each run step sends the student when they hit /run/play.
STEP_TO_PATH = {
    STEP_BRIEFING: "/run/brief",
    STEP_FORECAST: "/run/forecast",
    STEP_ALLOCATION: "/run/allocate",
    STEP_RESULTS: "/run/results",
    STEP_REFLECTION: "/run/reflect",
}

app = FastAPI(title="Market Analyst Simulation")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-only-insecure-secret-change-me"),
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Display filters shared across templates.
templates.env.filters["zar"] = lambda v: "R{:,.0f}".format(v or 0)
templates.env.filters["pct"] = lambda v: "{:+.1f}%".format((v or 0) * 100)
templates.env.filters["pct_abs"] = lambda v: "{:.1f}%".format((v or 0) * 100)
templates.env.filters["signed"] = lambda v: "{:+,.0f}".format(v or 0)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Turn auth failures into browser-friendly responses.

    Unauthenticated requests (401) redirect to the login page; forbidden
    requests (403) render a small forbidden page. Everything else re-raises the
    default representation.
    """
    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=303)
    if exc.status_code == 403:
        return templates.TemplateResponse(
            request, "forbidden.html", {}, status_code=403
        )
    return HTMLResponse(f"<h1>{exc.status_code}</h1><p>{exc.detail}</p>", status_code=exc.status_code)


@app.get("/", response_class=HTMLResponse)
def index(user: User | None = Depends(get_current_user)) -> Response:
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    if user.role == "lecturer":
        return RedirectResponse(url="/lecturer", status_code=303)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, user: User | None = Depends(get_current_user)) -> Response:
    if user is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
) -> Response:
    user = authenticate(session, username.strip(), password)
    if user is None:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid username or password."}, status_code=401
        )
    login_user(request, user)
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
def logout(request: Request) -> Response:
    logout_user(request)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    current_run = (
        session.query(Run)
        .filter(Run.user_id == user.id)
        .order_by(Run.started_at.desc())
        .first()
    )
    completed = current_run is not None and current_run.status == STATUS_COMPLETED
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"user": user, "run": current_run, "completed": completed},
    )


@app.get("/lecturer", response_class=HTMLResponse)
def lecturer_landing(
    request: Request,
    user: User = Depends(require_role("lecturer")),
    session: Session = Depends(get_session),
) -> Response:
    # Full cohort view is built in U7; this landing confirms the role gate works.
    return templates.TemplateResponse(request, "lecturer.html", {"user": user, "rows": []})


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# =============================================================================
# Student round flow (U4)
# =============================================================================

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=303)


def _current_run(session: Session, user: User) -> Run | None:
    return (
        session.query(Run)
        .filter(Run.user_id == user.id, Run.status == STATUS_IN_PROGRESS)
        .order_by(Run.started_at.desc())
        .first()
    )


def _owned_run(session: Session, user: User, run_id: int) -> Run:
    """Fetch a run by id, enforcing per-record ownership (plan U4)."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your run")
    return run


def _decision_for(run: Run, round_number: int) -> RoundDecision | None:
    for d in run.decisions:
        if d.round_number == round_number:
            return d
    return None


def _round_start_values(run: Run) -> tuple[float, float]:
    """Portfolio and benchmark value at the start of the run's current round."""
    if run.current_round == 1:
        return PACK.starting_capital, PACK.starting_capital
    prev = _decision_for(run, run.current_round - 1)
    if prev is None or prev.portfolio_value is None:
        return PACK.starting_capital, PACK.starting_capital
    return prev.portfolio_value, prev.benchmark_value


def _guard_step(run: Run, expected_step: str) -> RedirectResponse | None:
    """Enforce the state machine: off-step requests bounce to /run/play."""
    if run.current_step != expected_step:
        return _redirect("/run/play")
    return None


def _journey(run: Run) -> list[dict]:
    """Completed rounds as chart/journey points, oldest first."""
    points = []
    for d in sorted(run.decisions, key=lambda x: x.round_number):
        if d.portfolio_value is None:
            continue
        points.append(
            {
                "round": d.round_number,
                "portfolio_value": d.portfolio_value,
                "benchmark_value": d.benchmark_value,
                "trust_after": d.trust_after,
                "allocation": d.allocation,
                "results": d.results,
            }
        )
    return points


def _history_for_feedback(run: Run, upto_round: int) -> list[dict]:
    hist = []
    for d in sorted(run.decisions, key=lambda x: x.round_number):
        if d.round_number >= upto_round or not d.results:
            continue
        hist.append(
            {
                "round": d.round_number,
                "portfolio_return": d.results.get("portfolio_return"),
                "benchmark_return": d.results.get("benchmark_return"),
                "beat_benchmark": d.results.get("beat_benchmark"),
            }
        )
    return hist


@app.post("/run/start")
def run_start(
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    existing = _current_run(session, user)
    if existing is not None:
        return _redirect("/run/play")
    completed = (
        session.query(Run)
        .filter(Run.user_id == user.id, Run.status == STATUS_COMPLETED)
        .first()
    )
    if completed is not None:
        # One playthrough per student in the demo; revisit the summary instead.
        return _redirect(f"/run/{completed.id}/summary")
    run = Run(
        user_id=user.id,
        status=STATUS_IN_PROGRESS,
        current_round=1,
        current_step=STEP_BRIEFING,
        client_trust=PACK.starting_trust,
        started_at=_now(),
    )
    session.add(run)
    session.commit()
    return _redirect("/run/play")


@app.get("/run/play")
def run_play(
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if run.current_step == STEP_SUMMARY:
        return _redirect(f"/run/{run.id}/summary")
    return _redirect(STEP_TO_PATH.get(run.current_step, "/dashboard"))


@app.get("/run/brief", response_class=HTMLResponse)
def run_brief(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_BRIEFING)) is not None:
        return bounce
    brief = PACK.brief_for_round(run.current_round)
    return templates.TemplateResponse(
        request,
        "brief.html",
        {"user": user, "run": run, "brief": brief, "pack": PACK},
    )


@app.post("/run/brief")
def run_brief_continue(
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_BRIEFING)) is not None:
        return bounce
    run.current_step = STEP_FORECAST
    session.commit()
    return _redirect("/run/forecast")


@app.get("/run/forecast", response_class=HTMLResponse)
def run_forecast(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_FORECAST)) is not None:
        return bounce
    existing = _decision_for(run, run.current_round)
    prior = existing.forecast if existing and existing.forecast else None
    return templates.TemplateResponse(
        request,
        "forecast.html",
        {"user": user, "run": run, "pack": PACK, "prior": prior},
    )


@app.post("/run/forecast")
async def run_forecast_submit(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_FORECAST)) is not None:
        return bounce
    form = await request.form()
    directions = {}
    for share in PACK.shares:
        choice = form.get(f"forecast_{share.id}", "flat")
        directions[share.id] = choice if choice in ("up", "down", "flat") else "flat"
    forecast = {"directions": directions, "rationale": (form.get("rationale") or "").strip()}

    decision = _decision_for(run, run.current_round)
    if decision is None:
        decision = RoundDecision(run_id=run.id, round_number=run.current_round)
        session.add(decision)
    decision.forecast = forecast
    run.current_step = STEP_ALLOCATION
    session.commit()
    return _redirect("/run/allocate")


def _parse_allocation(form) -> dict:
    allocation = {}
    for share in PACK.shares:
        raw = form.get(share.id, "")
        try:
            allocation[share.id] = float(raw) if raw not in ("", None) else 0.0
        except ValueError:
            allocation[share.id] = 0.0
    raw_cash = form.get(CASH_ID, "")
    try:
        allocation[CASH_ID] = float(raw_cash) if raw_cash not in ("", None) else 0.0
    except ValueError:
        allocation[CASH_ID] = 0.0
    return allocation


@app.get("/run/allocate", response_class=HTMLResponse)
def run_allocate(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_ALLOCATION)) is not None:
        return bounce
    start_value, _ = _round_start_values(run)
    decision = _decision_for(run, run.current_round)
    prior_alloc = decision.allocation if decision and decision.allocation else {}
    return templates.TemplateResponse(
        request,
        "allocate.html",
        {
            "user": user,
            "run": run,
            "pack": PACK,
            "mandate": PACK.client.mandate,
            "start_value": start_value,
            "prior_alloc": prior_alloc,
            "error": None,
        },
    )


@app.post("/run/allocate/preview", response_class=HTMLResponse)
async def run_allocate_preview(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    """htmx live total: returns the total + validity fragment as the form changes."""
    form = await request.form()
    allocation = _parse_allocation(form)
    total = sum(allocation.values())
    ok, why = engine.validate_allocation(allocation, PACK)
    return templates.TemplateResponse(
        request,
        "_alloc_total.html",
        {"total": total, "ok": ok, "why": why},
    )


@app.post("/run/allocate")
async def run_allocate_submit(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_ALLOCATION)) is not None:
        return bounce
    form = await request.form()
    allocation = _parse_allocation(form)
    ok, why = engine.validate_allocation(allocation, PACK)
    start_value, benchmark_start = _round_start_values(run)
    if not ok:
        return templates.TemplateResponse(
            request,
            "allocate.html",
            {
                "user": user,
                "run": run,
                "pack": PACK,
                "mandate": PACK.client.mandate,
                "start_value": start_value,
                "prior_alloc": allocation,
                "error": why,
            },
            status_code=400,
        )

    results = engine.compute_round(PACK, run.current_round, allocation, start_value, benchmark_start)
    trust_after, trust_why = engine.update_trust(run.client_trust, results, PACK)
    results["trust_why"] = trust_why

    decision = _decision_for(run, run.current_round)
    if decision is None:
        decision = RoundDecision(run_id=run.id, round_number=run.current_round)
        session.add(decision)
    decision.allocation = allocation
    decision.results = results
    decision.portfolio_value = results["end_value"]
    decision.benchmark_value = results["benchmark_end"]
    decision.trust_before = run.client_trust
    decision.trust_after = trust_after

    run.client_trust = trust_after
    run.current_step = STEP_RESULTS
    session.commit()
    return _redirect("/run/results")


@app.get("/run/results", response_class=HTMLResponse)
def run_results(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_RESULTS)) is not None:
        return bounce
    decision = _decision_for(run, run.current_round)
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "user": user,
            "run": run,
            "pack": PACK,
            "decision": decision,
            "results": decision.results,
            "journey": _journey(run),
            "trust_delta": (decision.trust_after or 0) - (decision.trust_before or 0),
        },
    )


@app.get("/run/feedback", response_class=HTMLResponse)
def run_feedback_panel(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    """htmx panel: generates (and caches) the round's AI coaching feedback."""
    run = _current_run(session, user)
    if run is None:
        return HTMLResponse("")
    decision = _decision_for(run, run.current_round)
    if decision is None or not decision.results:
        return HTMLResponse("")

    record = (
        session.query(FeedbackRecord)
        .filter(FeedbackRecord.run_id == run.id, FeedbackRecord.round_number == run.current_round)
        .first()
    )
    if record is None:
        result = FEEDBACK.round_feedback(
            round_number=run.current_round,
            allocation=decision.allocation or {},
            forecast=decision.forecast or {},
            results=decision.results,
            history=_history_for_feedback(run, run.current_round),
        )
        record = FeedbackRecord(
            run_id=run.id,
            round_number=run.current_round,
            text=result.text,
            source=result.source,
        )
        session.add(record)
        session.commit()
    return templates.TemplateResponse(
        request, "_feedback_panel.html", {"feedback": record}
    )


@app.post("/run/results")
def run_results_continue(
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_RESULTS)) is not None:
        return bounce
    run.current_step = STEP_REFLECTION
    session.commit()
    return _redirect("/run/reflect")


@app.get("/run/reflect", response_class=HTMLResponse)
def run_reflect(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_REFLECTION)) is not None:
        return bounce
    decision = _decision_for(run, run.current_round)
    prompt = FEEDBACK.reflection_prompt(
        round_number=run.current_round,
        results=decision.results if decision else {},
        history=_history_for_feedback(run, run.current_round),
    )
    existing = next((r for r in run.reflections if r.round_number == run.current_round), None)
    return templates.TemplateResponse(
        request,
        "reflect.html",
        {"user": user, "run": run, "pack": PACK, "prompt": prompt, "existing": existing},
    )


@app.post("/run/reflect")
async def run_reflect_submit(
    request: Request,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _current_run(session, user)
    if run is None:
        return _redirect("/dashboard")
    if (bounce := _guard_step(run, STEP_REFLECTION)) is not None:
        return bounce
    form = await request.form()
    text = (form.get("reflection") or "").strip()

    indicative_rating, indicative_why = FEEDBACK.rate_reflection(text=text)
    reflection = next((r for r in run.reflections if r.round_number == run.current_round), None)
    if reflection is None:
        reflection = Reflection(run_id=run.id, round_number=run.current_round)
        session.add(reflection)
    reflection.text = text
    reflection.indicative_rating = indicative_rating
    reflection.indicative_why = indicative_why

    if run.current_round < TOTAL_ROUNDS:
        run.current_round += 1
        run.current_step = STEP_BRIEFING
        session.commit()
        return _redirect("/run/play")

    # Final round complete — close out the run.
    run.current_step = STEP_SUMMARY
    run.status = STATUS_COMPLETED
    run.completed_at = _now()
    last = _decision_for(run, TOTAL_ROUNDS)
    if last is not None:
        run.final_value = last.portfolio_value
        run.benchmark_value = last.benchmark_value
    session.flush()
    _finalize_run(session, run)  # composite scoring (U6) if available
    session.commit()
    return _redirect(f"/run/{run.id}/summary")


def _finalize_run(session: Session, run: Run) -> None:
    """Compute composite scoring at completion. Wired by U6; a no-op until then."""
    try:
        from app import scoring
    except ImportError:
        return
    scoring.finalize_run(run, PACK)


@app.get("/run/{run_id}/summary", response_class=HTMLResponse)
def run_summary(
    request: Request,
    run_id: int,
    user: User = Depends(require_role("student")),
    session: Session = Depends(get_session),
) -> Response:
    run = _owned_run(session, user, run_id)
    reflections = {r.round_number: r for r in run.reflections}
    feedback_by_round = {f.round_number: f for f in run.feedback}
    return templates.TemplateResponse(
        request,
        "summary.html",
        {
            "user": user,
            "run": run,
            "pack": PACK,
            "journey": _journey(run),
            "reflections": reflections,
            "feedback_by_round": feedback_by_round,
        },
    )
