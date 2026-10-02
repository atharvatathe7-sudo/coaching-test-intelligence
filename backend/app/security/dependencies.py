"""
FastAPI dependencies for authentication and roles.

Routers declare these once (router-level `dependencies=`), so handlers
never implement their own authentication checks.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import config
from ..database.connection import get_db
from ..database.models import User


def current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """The signed-in user, or 401. Stores the session on request.state."""
    from .sessions import resolve_session

    resolved = resolve_session(
        db, request.cookies.get(config.SESSION_COOKIE_NAME)
    )

    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in, or the session has expired.",
        )

    session, user = resolved
    request.state.session = session
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access is required.",
        )
    return user
