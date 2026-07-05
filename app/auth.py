"""Session auth helpers.

Cookie-session auth via Starlette's ``SessionMiddleware`` — a signed cookie
carries the logged-in user id. Demo accounts use simple shared credentials
(no password hashing), which is acceptable for a throwaway showcase (plan U1).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User

SESSION_USER_KEY = "user_id"


def login_user(request: Request, user: User) -> None:
    request.session[SESSION_USER_KEY] = user.id


def logout_user(request: Request) -> None:
    request.session.pop(SESSION_USER_KEY, None)


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.query(User).filter(User.username == username).one_or_none()
    if user is None or user.password != password:
        return None
    return user


def get_current_user(
    request: Request, session: Session = Depends(get_session)
) -> User | None:
    """Return the logged-in user, or ``None`` when there is no valid session."""
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        return None
    return session.get(User, user_id)


def require_user(user: User | None = Depends(get_current_user)) -> User:
    """Dependency that redirects unauthenticated requests to the login page."""
    if user is None:
        # 307 preserves method; the exception handler in main.py turns auth
        # failures into a redirect for browser requests.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


def require_role(role: str):
    """Dependency factory enforcing a specific role."""

    def _dep(user: User = Depends(require_user)) -> User:
        if user.role != role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _dep
