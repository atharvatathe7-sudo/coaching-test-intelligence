"""
Audit trail for administrative changes.

record() adds an entry to the caller's session; the caller commits it
together with the change, so either both are saved or neither is.

Never put student names, roll numbers, answers, passwords or tokens in
`detail`: use ids, counts and non-personal before/after values.
"""

from sqlalchemy.orm import Session

from ..database.models import AuditLog, User

# Actions that change correctness results for a test, making earlier
# finding snapshots (e.g. "Only 25% correct") potentially stale.
REEVALUATING_ACTIONS = ("answer_key.correct", "answers.replace")


def record(
    db: Session,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: int | None,
    detail: dict | None = None,
    institute_id: int | None = None,
) -> None:
    db.add(
        AuditLog(
            institute_id=institute_id or actor.institute_id,
            user_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail or {},
        )
    )


def last_reevaluation(db: Session, test_id: int):
    """When the test's results were last changed by a correction, or None."""
    row = (
        db.query(AuditLog.created_at)
        .filter(
            AuditLog.entity_type == "test",
            AuditLog.entity_id == test_id,
            AuditLog.action.in_(REEVALUATING_ACTIONS),
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    return row[0] if row else None
