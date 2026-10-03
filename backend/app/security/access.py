"""
Tenant ownership checks: the one place that decides whether an object
belongs to the signed-in user's institute.

Ownership anchors:
- Batch.institute_id owns batches, and through them students, tests,
  questions, answers, results and teacher actions.
- Chapter.institute_id owns chapters, and through them topics.
- OMRBatch.institute_id owns OMR review batches, and through them their
  sheets, answers and stored images. The batch's test must also belong
  to the same institute.

find_* return the object only when it belongs to the user's institute,
otherwise None. owned_* are FastAPI path dependencies that return the
object or raise 404. A 404 (not 403) is used for other institutes'
objects so their existence is not revealed.
"""

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..database.connection import get_db
from ..database.models import (
    Batch,
    Chapter,
    OMRAnswer,
    OMRBatch,
    OMRSheet,
    Student,
    TeacherAction,
    Test,
    Topic,
    User,
)
from .dependencies import current_user


def find_batch(db: Session, user: User, batch_id: int | None) -> Batch | None:
    if batch_id is None:
        return None
    batch = db.get(Batch, batch_id)
    if batch is None or batch.institute_id != user.institute_id:
        return None
    return batch


def find_test(db: Session, user: User, test_id: int | None) -> Test | None:
    if test_id is None:
        return None
    test = db.get(Test, test_id)
    if test is None or find_batch(db, user, test.batch_id) is None:
        return None
    return test


def find_student(db: Session, user: User, student_id: int) -> Student | None:
    student = db.get(Student, student_id)
    if student is None or find_batch(db, user, student.batch_id) is None:
        return None
    return student


def find_action(db: Session, user: User, action_id: int) -> TeacherAction | None:
    action = db.get(TeacherAction, action_id)
    if action is None or find_test(db, user, action.test_id) is None:
        return None
    return action


def find_chapter(db: Session, user: User, chapter_id: int) -> Chapter | None:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None or chapter.institute_id != user.institute_id:
        return None
    return chapter


def find_topic(db: Session, user: User, topic_id: int) -> Topic | None:
    topic = db.get(Topic, topic_id)
    if topic is None or find_chapter(db, user, topic.chapter_id) is None:
        return None
    return topic


def find_omr_batch(db: Session, user: User, batch_id: int | None) -> OMRBatch | None:
    if batch_id is None:
        return None
    batch = db.get(OMRBatch, batch_id)
    if batch is None or batch.institute_id != user.institute_id:
        return None
    # Defence in depth: the test it belongs to must be ours as well.
    if find_test(db, user, batch.test_id) is None:
        return None
    return batch


def find_omr_sheet(db: Session, user: User, sheet_id: int) -> OMRSheet | None:
    sheet = db.get(OMRSheet, sheet_id)
    if sheet is None or find_omr_batch(db, user, sheet.batch_id) is None:
        return None
    return sheet


def find_omr_answer(db: Session, user: User, answer_id: int) -> OMRAnswer | None:
    answer = db.get(OMRAnswer, answer_id)
    if answer is None or find_omr_sheet(db, user, answer.sheet_id) is None:
        return None
    return answer


def institute_batches(db: Session, user: User):
    """Query of the user's institute's batches."""
    return db.query(Batch).filter(Batch.institute_id == user.institute_id)


def institute_tests(db: Session, user: User):
    """Query of the user's institute's tests."""
    return (
        db.query(Test)
        .join(Batch, Batch.id == Test.batch_id)
        .filter(Batch.institute_id == user.institute_id)
    )


def _found(obj, kind: str):
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{kind} not found.")
    return obj


# --- Path dependencies ----------------------------------------------------

def owned_batch(
    batch_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Batch:
    return _found(find_batch(db, user, batch_id), "Batch")


def owned_test(
    test_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Test:
    return _found(find_test(db, user, test_id), "Test")


def owned_student(
    student_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Student:
    return _found(find_student(db, user, student_id), "Student")


def owned_action(
    action_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> TeacherAction:
    return _found(find_action(db, user, action_id), "Action")


def owned_test_pair(
    previous_test_id: int,
    current_test_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> tuple[Test, Test]:
    return (
        _found(find_test(db, user, previous_test_id), "Test"),
        _found(find_test(db, user, current_test_id), "Test"),
    )


def owned_omr_batch(
    batch_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OMRBatch:
    return _found(find_omr_batch(db, user, batch_id), "OMR batch")


def owned_omr_sheet(
    sheet_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OMRSheet:
    return _found(find_omr_sheet(db, user, sheet_id), "OMR sheet")


def owned_omr_answer(
    item_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OMRAnswer:
    return _found(find_omr_answer(db, user, item_id), "Review item")

