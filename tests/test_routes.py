"""Route + auth tests for the app shell (U1)."""

from __future__ import annotations

from tests.conftest import login


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Welcome, Analyst" in resp.text


def test_student_login_reaches_dashboard(client):
    resp = login(client, "student")
    assert resp.status_code == 200
    assert "Your desk" in resp.text


def test_lecturer_login_reaches_lecturer_view(client):
    resp = login(client, "lecturer")
    assert resp.status_code == 200
    assert "Cohort overview" in resp.text


def test_wrong_credentials_shows_error_and_no_session(client):
    resp = client.post(
        "/login",
        data={"username": "student", "password": "wrong"},
        follow_redirects=True,
    )
    assert resp.status_code == 401
    assert "Invalid username or password" in resp.text

    # No session was created: the dashboard must bounce back to login.
    dash = client.get("/dashboard", follow_redirects=False)
    assert dash.status_code == 303
    assert dash.headers["location"] == "/login"


def test_student_cannot_access_lecturer_route(client):
    login(client, "student")
    resp = client.get("/lecturer", follow_redirects=False)
    assert resp.status_code == 403


def test_unauthenticated_dashboard_redirects_to_login(client):
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_logout_clears_session(client):
    login(client, "student")
    client.get("/logout")
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# =============================================================================
# Student round flow (U4)
# =============================================================================

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    STATUS_COMPLETED,
    FeedbackRecord,
    Reflection,
    Run,
    RoundDecision,
    User,
)

VALID_ALLOC = {"KGM": 20, "UFG": 20, "KFR": 10, "VLA": 10, "CFL": 10, "SUN": 20, "CASH": 10}


def _forecast_form():
    data = {f"forecast_{sid}": "up" for sid in ["KGM", "UFG", "KFR", "VLA", "CFL", "SUN"]}
    data["rationale"] = "I expect steady growth across sectors."
    return data


def _play_one_round(client, reflection="A thoughtful reflection about my choices."):
    """Walk brief -> forecast -> allocate -> results -> reflect for one round."""
    client.post("/run/brief")
    client.post("/run/forecast", data=_forecast_form())
    client.post("/run/allocate", data=VALID_ALLOC)
    client.get("/run/feedback")  # generate the AI panel (canned in tests)
    client.post("/run/results")
    return client.post("/run/reflect", data={"reflection": reflection}, follow_redirects=False)


def _run_id_for(username):
    with SessionLocal() as s:
        user = s.query(User).filter(User.username == username).one()
        run = s.query(Run).filter(Run.user_id == user.id).order_by(Run.id.desc()).first()
        return run.id if run else None


def test_full_playthrough_persists_all_rounds(client):
    login(client, "student")
    client.post("/run/start")
    for _ in range(4):
        last = _play_one_round(client)
    # Final reflect redirects to the summary of a now-completed run.
    assert last.status_code == 303
    assert "/summary" in last.headers["location"]

    run_id = _run_id_for("student")
    with SessionLocal() as s:
        run = s.get(Run, run_id)
        assert run.status == STATUS_COMPLETED
        decisions = s.query(RoundDecision).filter(RoundDecision.run_id == run_id).all()
        reflections = s.query(Reflection).filter(Reflection.run_id == run_id).all()
        feedback = s.query(FeedbackRecord).filter(FeedbackRecord.run_id == run_id).all()
        assert len(decisions) == 4
        assert len(reflections) == 4
        assert len(feedback) == 4
        assert run.final_value is not None

    summary = client.get(f"/run/{run_id}/summary")
    assert summary.status_code == 200
    assert "The year in review" in summary.text


def test_allocation_not_summing_to_100_re_renders_with_error(client):
    login(client, "student")
    client.post("/run/start")
    client.post("/run/brief")
    client.post("/run/forecast", data=_forecast_form())
    bad = dict(VALID_ALLOC)
    bad["CASH"] = 5  # now sums to 95
    resp = client.post("/run/allocate", data=bad, follow_redirects=False)
    assert resp.status_code == 400
    assert "100%" in resp.text
    # No decision was finalised.
    run_id = _run_id_for("student")
    with SessionLocal() as s:
        dec = s.query(RoundDecision).filter(RoundDecision.run_id == run_id).first()
        assert dec.results is None


def test_cannot_skip_ahead_in_state_machine(client):
    login(client, "student")
    client.post("/run/start")  # step = briefing
    # Jumping straight to allocate submission bounces to /run/play.
    resp = client.post("/run/allocate", data=VALID_ALLOC, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/run/play"


def test_cannot_resubmit_a_completed_step(client):
    login(client, "student")
    client.post("/run/start")
    client.post("/run/brief")
    client.post("/run/forecast", data=_forecast_form())
    client.post("/run/allocate", data=VALID_ALLOC)  # advances to results
    # A second allocate submission is now off-step and bounces.
    resp = client.post("/run/allocate", data=VALID_ALLOC, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/run/play"


def test_empty_reflection_is_accepted_and_flagged(client):
    login(client, "student")
    client.post("/run/start")
    client.post("/run/brief")
    client.post("/run/forecast", data=_forecast_form())
    client.post("/run/allocate", data=VALID_ALLOC)
    client.post("/run/results")
    resp = client.post("/run/reflect", data={"reflection": ""}, follow_redirects=False)
    assert resp.status_code == 303  # accepted, advances
    run_id = _run_id_for("student")
    with SessionLocal() as s:
        refl = s.query(Reflection).filter(Reflection.run_id == run_id, Reflection.round_number == 1).one()
        assert refl.text == ""
        assert refl.indicative_rating == 0.0  # floored, flagged as too short


def test_student_cannot_view_another_students_run(client):
    # Student A completes/creates a run.
    login(client, "student")
    client.post("/run/start")
    a_run_id = _run_id_for("student")

    # Student B logs in on a fresh client and tries to view A's run.
    from fastapi.testclient import TestClient
    from app.main import app

    other = TestClient(app)
    login(other, "thabo")
    resp = other.get(f"/run/{a_run_id}/summary", follow_redirects=False)
    assert resp.status_code == 403


def test_summary_of_missing_run_is_404(client):
    login(client, "student")
    resp = client.get("/run/99999/summary", follow_redirects=False)
    assert resp.status_code == 404


def test_each_step_page_renders(client):
    """GET every step template to catch Jinja rendering errors."""
    login(client, "student")
    client.post("/run/start")

    brief = client.get("/run/brief")
    assert brief.status_code == 200 and "Market snapshot" in brief.text
    client.post("/run/brief")

    forecast = client.get("/run/forecast")
    assert forecast.status_code == 200 and "Your forecast" in forecast.text
    client.post("/run/forecast", data=_forecast_form())

    allocate = client.get("/run/allocate")
    assert allocate.status_code == 200 and "Allocate the portfolio" in allocate.text
    client.post("/run/allocate", data=VALID_ALLOC)

    results = client.get("/run/results")
    assert results.status_code == 200 and "results" in results.text.lower()

    panel = client.get("/run/feedback")
    assert panel.status_code == 200 and panel.text.strip()  # canned coaching present
    client.post("/run/results")

    reflect = client.get("/run/reflect")
    assert reflect.status_code == 200 and "Reflect" in reflect.text
    # The prompt loads via an htmx fragment (deferred so the page renders instantly).
    prompt = client.get("/run/reflect/prompt")
    assert prompt.status_code == 200 and prompt.text.strip()


def test_allocate_preview_returns_live_total(client):
    login(client, "student")
    client.post("/run/start")
    client.post("/run/brief")
    client.post("/run/forecast", data=_forecast_form())
    resp = client.post("/run/allocate/preview", data=VALID_ALLOC)
    assert resp.status_code == 200
    assert "100%" in resp.text


def test_leaderboard_shows_completed_run(client):
    login(client, "student")
    client.post("/run/start")
    for _ in range(4):
        _play_one_round(client)
    board = client.get("/leaderboard")
    assert board.status_code == 200
    assert "Demo Student" in board.text


# =============================================================================
# Lecturer dashboard (U7)
# =============================================================================

def test_lecturer_sees_cohort_and_drilldown(client):
    from fastapi.testclient import TestClient
    from app.main import app

    # A student completes a full run.
    login(client, "student")
    client.post("/run/start")
    for _ in range(4):
        _play_one_round(client)
    run_id = _run_id_for("student")

    lecturer = TestClient(app)
    login(lecturer, "lecturer")
    board = lecturer.get("/lecturer")
    assert board.status_code == 200
    assert "Demo Student" in board.text
    assert "Completed" in board.text

    detail = lecturer.get(f"/lecturer/run/{run_id}")
    assert detail.status_code == 200
    assert "Round 1" in detail.text
    assert "AI feedback" in detail.text  # feedback record shown
    assert "Composite breakdown" in detail.text


def test_student_cannot_access_lecturer_detail(client):
    login(client, "student")
    resp = client.get("/lecturer/run/1", follow_redirects=False)
    assert resp.status_code == 403


def test_lecturer_detail_missing_run_is_404(client):
    login(client, "lecturer")
    resp = client.get("/lecturer/run/99999", follow_redirects=False)
    assert resp.status_code == 404
