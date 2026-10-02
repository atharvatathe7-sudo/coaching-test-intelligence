"""
Authentication routes: login, logout, current user, password change.

POST /api/auth/login is the only public write route. Failures always
return the same 401 response, whether the email is unknown, the password
wrong, the account disabled or temporarily locked.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from . import config
from .database.connection import get_db
from .database.models import Institute, User
from .schemas.auth import LoginRequest, PasswordChange
from .security.clock import utcnow
from .security.dependencies import current_user
from .security.passwords import (
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    verify_dummy,
    verify_password,
)
from .security.sessions import (
    create_session,
    revoke_session,
    revoke_user_sessions,
)

router = APIRouter(prefix="/api/auth")

LOGIN_FAILED = "Invalid email or password."


def normalize_email(email: str) -> str:
    return email.strip().lower()


def user_info(db: Session, user: User) -> dict:
    institute = db.get(Institute, user.institute_id)
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "institute": {"id": institute.id, "name": institute.name},
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=token,
        max_age=config.SESSION_ABSOLUTE_DAYS * 24 * 3600,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=config.SESSION_COOKIE_NAME,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.email == normalize_email(payload.email))
        .first()
    )

    if user is None:
        verify_dummy(payload.password)
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)

    now = utcnow()

    if user.locked_until is not None and user.locked_until > now:
        verify_dummy(payload.password)
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)

    if not verify_password(user.password_hash, payload.password):
        user.failed_login_count += 1

        if user.failed_login_count >= config.LOGIN_MAX_FAILURES:
            user.locked_until = now + timedelta(
                minutes=config.LOGIN_LOCK_MINUTES
            )
            user.failed_login_count = 0

        db.commit()
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)

    if not user.is_active:
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    token = create_session(db, user)
    db.commit()

    _set_session_cookie(response, token)

    return {"user": user_info(db, user)}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    revoke_session(db, request.state.session)
    db.commit()
    _clear_session_cookie(response)
    return {"status": "signed_out"}


@router.get("/me")
def me(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return {"user": user_info(db, user)}


@router.post("/password")
def change_password(
    payload: PasswordChange,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(
            status_code=400,
            detail="The current password is not correct.",
        )

    try:
        user.password_hash = hash_password(payload.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Sign out every other session of this user.
    revoked = revoke_user_sessions(
        db, user.id, except_session_id=request.state.session.id
    )
    db.commit()

    return {"status": "password_changed", "other_sessions_revoked": revoked}
