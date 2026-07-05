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
