"""
Admin user management for the admin's own institute: list, create,
update (name, role, enable/disable) and reset password.

There is no self-signup. Disabling a user or resetting their password
revokes all of their sessions.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth_api import normalize_email
from .database.connection import get_db
from .database.models import User
from .schemas.auth import PasswordReset, UserCreate, UserUpdate
from .security.clock import utcnow
from .security.dependencies import require_admin
from .security.passwords import PasswordPolicyError, hash_password
from .security.sessions import revoke_user_sessions
from .services import audit

router = APIRouter(
    prefix="/api/users",
    dependencies=[Depends(require_admin)],
)


def serialize_user(user: User) -> dict:
    now = utcnow()
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "locked": bool(user.locked_until and user.locked_until > now),
        "created_at": user.created_at.isoformat(),
        "last_login_at": (
            user.last_login_at.isoformat() if user.last_login_at else None
        ),
    }


def _owned_user(db: Session, admin: User, user_id: int) -> User:
    user = db.get(User, user_id)

    if user is None or user.institute_id != admin.institute_id:
        raise HTTPException(status_code=404, detail="User not found.")

    return user


def _valid_email(email: str) -> str:
    email = normalize_email(email)
    local, _, domain = email.partition("@")

    if not local or "." not in domain or " " in email:
        raise HTTPException(status_code=400, detail="Enter a valid email.")

    return email


@router.get("")
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = (
        db.query(User)
        .filter(User.institute_id == admin.institute_id)
        .order_by(User.id)
        .all()
    )
    return {"users": [serialize_user(u) for u in users]}


@router.post("")
def create_user(
    payload: UserCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        password_hash = hash_password(payload.password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user = User(
        institute_id=admin.institute_id,
        name=payload.name.strip(),
        email=_valid_email(payload.email),
        password_hash=password_hash,
        role=payload.role,
        is_active=True,
    )
    db.add(user)

    try:
        db.flush()
        audit.record(db, admin, "user.create", "user", user.id, {"role": user.role})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A user with this email already exists.",
        )

    db.refresh(user)
    return serialize_user(user)


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _owned_user(db, admin, user_id)
    fields = payload.model_fields_set

    if user.id == admin.id and (
        ("role" in fields and payload.role != admin.role)
        or ("is_active" in fields and payload.is_active is False)
    ):
        raise HTTPException(
            status_code=400,
            detail="You cannot disable or demote your own account.",
        )

    changes = {}

    if "name" in fields and payload.name is not None:
        if payload.name.strip() != user.name:
            changes["name"] = True
        user.name = payload.name.strip()

    if "role" in fields and payload.role is not None:
        if payload.role != user.role:
            changes["role"] = [user.role, payload.role]
        user.role = payload.role

    if "is_active" in fields and payload.is_active is not None:
        if payload.is_active != user.is_active:
            changes["is_active"] = [user.is_active, payload.is_active]
        user.is_active = payload.is_active

        if payload.is_active:
            user.failed_login_count = 0
            user.locked_until = None
        else:
            revoke_user_sessions(db, user.id)

    if changes:
        audit.record(db, admin, "user.update", "user", user.id, {"changes": changes})

    db.commit()
    db.refresh(user)
    return serialize_user(user)


@router.post("/{user_id}/password")
def reset_password(
    user_id: int,
    payload: PasswordReset,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _owned_user(db, admin, user_id)

    try:
        user.password_hash = hash_password(payload.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user.failed_login_count = 0
    user.locked_until = None
    revoked = revoke_user_sessions(db, user.id)
    audit.record(
        db, admin, "user.password_reset", "user", user.id,
        {"sessions_revoked": revoked},
    )
    db.commit()

    return {"status": "password_reset", "sessions_revoked": revoked}
