"""
Server-side sessions.

The browser holds an opaque random token in an HttpOnly cookie; the
database stores only its SHA-256 hash. Sessions slide forward while in
use (idle timeout) up to an absolute maximum lifetime, and can be revoked
at any time (logout, password change, user disabled).
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from .. import config
from ..database.models import User, UserSession
from .clock import utcnow


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _absolute_expiry(session: UserSession):
    return session.created_at + timedelta(days=config.SESSION_ABSOLUTE_DAYS)


def create_session(db: Session, user: User) -> str:
    """Create a session row and return the raw token (for the cookie)."""
    token = secrets.token_urlsafe(32)
    now = utcnow()

    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=min(
                now + timedelta(hours=config.SESSION_IDLE_HOURS),
                now + timedelta(days=config.SESSION_ABSOLUTE_DAYS),
            ),
        )
    )
    return token


def resolve_session(db: Session, token: str | None):
    """
    Return (session, user) for a valid token, else None.

    Valid means: known, not revoked, not past its sliding or absolute
    expiry, and belonging to an active user. A valid session is slid
    forward (written at most once per SESSION_TOUCH_SECONDS).
    """

    if not token:
        return None

    session = (
        db.query(UserSession)
        .filter(UserSession.token_hash == hash_token(token))
        .first()
    )

    if session is None or session.revoked_at is not None:
        return None

    now = utcnow()

    if now >= session.expires_at or now >= _absolute_expiry(session):
        return None

    user = db.get(User, session.user_id)

    if user is None or not user.is_active:
        return None

    if (now - session.last_seen_at).total_seconds() >= config.SESSION_TOUCH_SECONDS:
        session.last_seen_at = now
        session.expires_at = min(
            now + timedelta(hours=config.SESSION_IDLE_HOURS),
            _absolute_expiry(session),
        )
        db.commit()

    return session, user


def revoke_session(db: Session, session: UserSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = utcnow()


def revoke_user_sessions(
    db: Session,
    user_id: int,
    except_session_id: int | None = None,
) -> int:
    """Revoke every active session of a user (optionally keeping one)."""
    query = db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    )

    if except_session_id is not None:
        query = query.filter(UserSession.id != except_session_id)

    now = utcnow()
    count = 0

    for session in query:
        session.revoked_at = now
        count += 1

    return count
