"""FastAPI application: routes, session auth, and page rendering.

U1 establishes the shell — app wiring, session middleware, login/logout, the
student dashboard, and a lecturer landing. The student round flow (U4),
scoring/leaderboard surface (U6), and full lecturer view (U7) extend this file.
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    authenticate,
    get_current_user,
    login_user,
    logout_user,
    require_role,
    require_user,
)
from app.db import get_session
from app.models import STATUS_COMPLETED, Run, User

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Market Analyst Simulation")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-only-insecure-secret-change-me"),
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


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
