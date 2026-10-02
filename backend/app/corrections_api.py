"""
Admin-only data corrections: test metadata, test deletion, roster
corrections, and the audit log.

Every change is one transaction that also writes its audit entry.
Answer-key and answer corrections are CSV workflows under /api/imports.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .api import serialize_test
from .database.connection import get_db
from .database.models import (
    AuditLog,
    Question,
    Student,
    StudentAnswer,
    TeacherAction,
    Test,
    TestResult,
    User,
)
from .schemas.api import StudentUpdate, TestUpdate
from .security.access import owned_student, owned_test
from .security.dependencies import require_admin
from .services import audit
from .services.evaluation import evaluate_test
from .services.import_csv import clean_text, normalize_name
from .ops.backup import BackupError, pre_operation_backup

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


# -------------------------------------------------------------------
# Test metadata
# -------------------------------------------------------------------

@router.patch("/tests/{test_id}")
def update_test(
    payload: TestUpdate,
    test: Test = Depends(owned_test),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    fields = {
        name: getattr(payload, name)
        for name in payload.model_fields_set
        if getattr(payload, name) is not None
    }

    if "name" in fields:
        fields["name"] = clean_text(fields["name"])
    if "subject" in fields:
        fields["subject"] = clean_text(fields["subject"])

    for name in ("name", "subject"):
        if name in fields and not fields[name]:
            raise HTTPException(status_code=400, detail=f"{name} is blank.")

    changes = {
        name: [getattr(test, name), value]
        for name, value in fields.items()
        if getattr(test, name) != value
    }

    if not changes:
        return {"test": serialize_test(test), "changed": [], "reevaluated": False}

    new_name = changes.get("name", [None, test.name])[1]
    new_date = changes.get("test_date", [None, test.test_date])[1]

    # Same identity rule as the importer: (batch, normalized name, date).
    for other in db.query(Test).filter(
        Test.batch_id == test.batch_id,
        Test.test_date == new_date,
        Test.id != test.id,
    ):
        if normalize_name(other.name) == normalize_name(new_name):
            raise HTTPException(
                status_code=409,
                detail="Another test in this batch has this name and date.",
            )

    for name, (_, value) in changes.items():
        setattr(test, name, value)

    if "subject" in changes:
        # Keep the per-question copy of the subject consistent.
        db.query(Question).filter(Question.test_id == test.id).update(
            {"subject": test.subject}, synchronize_session=False
        )

    marks_changed = bool(
        {"marks_correct", "marks_wrong", "marks_blank"} & set(changes)
    )
    has_answers = (
        db.query(StudentAnswer.id).filter(StudentAnswer.test_id == test.id).first()
        is not None
    )
    reevaluated = marks_changed and has_answers

    try:
        db.flush()

        if reevaluated:
            evaluate_test(db, test.id, commit=False)

        audit.record(
            db, admin, "test.update", "test", test.id,
            {
                "changes": {
                    name: [str(before), str(after)]
                    for name, (before, after) in changes.items()
                },
                "reevaluated": reevaluated,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(test)

    return {
        "test": serialize_test(test),
        "changed": sorted(changes),
        "reevaluated": reevaluated,
    }


@router.delete("/tests/{test_id}")
def delete_test(
    test: Test = Depends(owned_test),
    confirm_delete_actions: bool = Query(False),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Delete a test with its questions, answers and results.

    Teacher actions are historical records: if any exist the deletion is
    refused (409) unless confirm_delete_actions=true is sent.
    """

    action_count = (
        db.query(TeacherAction).filter(TeacherAction.test_id == test.id).count()
    )

    if action_count and not confirm_delete_actions:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"This test has {action_count} teacher action(s). "
                    "Deleting the test also deletes them; confirm to proceed."
                ),
                "teacher_actions": action_count,
            },
        )

    detail = {
        "name": test.name,
        "test_date": test.test_date.isoformat(),
        "batch_id": test.batch_id,
        "questions": db.query(Question).filter(Question.test_id == test.id).count(),
        "answer_records": db.query(StudentAnswer)
        .filter(StudentAnswer.test_id == test.id)
        .count(),
        "results": db.query(TestResult).filter(TestResult.test_id == test.id).count(),
        "teacher_actions_deleted": action_count,
    }

    try:
        pre_operation_backup("delete-test")
    except BackupError as exc:
        raise HTTPException(status_code=503, detail=f"{exc} Nothing was deleted.")
    test_id = test.id

    try:
        db.query(TeacherAction).filter(TeacherAction.test_id == test.id).delete(
            synchronize_session=False
        )
        # Questions, answers and results go with the test (ON DELETE CASCADE).
        db.delete(test)
        db.flush()
        audit.record(db, admin, "test.delete", "test", test_id, detail)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"status": "deleted", **detail}


# -------------------------------------------------------------------
# Roster corrections
# -------------------------------------------------------------------

@router.patch("/students/{student_id}")
def update_student(
    payload: StudentUpdate,
    student: Student = Depends(owned_student),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    changed = []

    if payload.name is not None:
        name = clean_text(payload.name)
        if not name:
            raise HTTPException(status_code=400, detail="Name is blank.")
        if name != student.name:
            student.name = name
            changed.append("name")

    if payload.roll_number is not None:
        roll = clean_text(payload.roll_number)
        if not roll:
            raise HTTPException(status_code=400, detail="Roll number is blank.")

        # Imports match roll numbers case-insensitively, so uniqueness is
        # checked the same way.
        clash = [
            other
            for other in db.query(Student).filter(
                Student.batch_id == student.batch_id,
                Student.id != student.id,
            )
            if normalize_name(other.roll_number) == normalize_name(roll)
        ]
        if clash:
            raise HTTPException(
                status_code=409,
                detail="Another student in this batch has this roll number.",
            )
        if roll != student.roll_number:
            student.roll_number = roll
            changed.append("roll_number")

    if changed:
        # Field names only: the audit log never stores names or roll numbers.
        audit.record(
            db, admin, "student.update", "student", student.id,
            {"batch_id": student.batch_id, "fields_changed": changed},
        )
        db.commit()
        db.refresh(student)

    return {
        "student": {
            "id": student.id,
            "batch_id": student.batch_id,
            "roll_number": student.roll_number,
            "name": student.name,
        },
        "changed": changed,
    }


@router.delete("/students/{student_id}")
def delete_student(
    student: Student = Depends(owned_student),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    has_answers = (
        db.query(StudentAnswer.id)
        .filter(StudentAnswer.student_id == student.id)
        .first()
        is not None
    ) or (
        db.query(TestResult.id).filter(TestResult.student_id == student.id).first()
        is not None
    )

    if has_answers:
        raise HTTPException(
            status_code=409,
            detail=(
                "This student has test answers and cannot be deleted. "
                "Correct the roster entry instead."
            ),
        )

    student_id, batch_id = student.id, student.batch_id
    db.delete(student)
    audit.record(
        db, admin, "student.delete", "student", student_id, {"batch_id": batch_id}
    )
    db.commit()

    return {"status": "deleted", "student_id": student_id}


# -------------------------------------------------------------------
# Audit log
# -------------------------------------------------------------------

@router.get("/audit")
def list_audit(
    limit: int = Query(100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .filter(AuditLog.institute_id == admin.institute_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .all()
    )

    return {
        "entries": [
            {
                "id": entry.id,
                "action": entry.action,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "detail": entry.detail,
                "user": {"id": entry.user_id, "name": user_name},
                "created_at": entry.created_at.isoformat(),
            }
            for entry, user_name in rows
        ]
    }
