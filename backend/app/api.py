"""
Main API routes.

Every route here requires a signed-in user (router-level dependency).
Objects named in the URL are loaded through security.access, which also
checks they belong to the user's institute; handlers therefore only ever
see authorized objects. Admin-only routes add require_admin.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database.connection import get_db
from .database.models import (
    Batch,
    Chapter,
    Question,
    Student,
    StudentAnswer,
    TeacherAction,
    Test,
    Topic,
    User,
)
from .schemas.api import (
    BatchCreate,
    TeacherActionCreate,
    TeacherActionUpdate,
)
from .security import access
from .security.access import owned_action, owned_test, owned_test_pair
from .security.dependencies import current_user, require_admin
from .services import audit
from .services.action_outcomes import get_action_outcomes
from .services.action_report import generate_teacher_action_report
from .services.analytics import (
    analyze_batch,
    analyze_questions,
    analyze_students,
    analyze_topics_and_chapters,
)
from .services.evaluation import classify_answer, evaluate_test
from .services.progress import compare_tests


router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _not_found_from(exc: ValueError):
    return HTTPException(status_code=404, detail=str(exc))


# -------------------------------------------------------------------
# Batches
# -------------------------------------------------------------------

@router.post("/batches", dependencies=[Depends(require_admin)])
def create_batch(
    payload: BatchCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    # The institute always comes from the signed-in user, never the client.
    batch = Batch(
        institute_id=user.institute_id,
        name=payload.name.strip(),
    )

    db.add(batch)

    try:
        db.flush()
        audit.record(db, user, "batch.create", "batch", batch.id, {})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="A batch with this name already exists in the institute.",
        )

    db.refresh(batch)

    return {
        "id": batch.id,
        "institute_id": batch.institute_id,
        "name": batch.name,
    }


@router.get("/batches")
def list_batches(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    batches = access.institute_batches(db, user).order_by(Batch.id).all()

    return {
        "batches": [
            {
                "id": batch.id,
                "institute_id": batch.institute_id,
                "name": batch.name,
            }
            for batch in batches
        ]
    }


# -------------------------------------------------------------------
# Students
# -------------------------------------------------------------------

@router.get("/students")
def list_students(
    batch_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if batch_id is not None:
        if access.find_batch(db, user, batch_id) is None:
            raise HTTPException(status_code=404, detail="Batch not found.")
        query = db.query(Student).filter(Student.batch_id == batch_id)
    else:
        query = (
            db.query(Student)
            .join(Batch, Batch.id == Student.batch_id)
            .filter(Batch.institute_id == user.institute_id)
        )

    students = query.order_by(Student.id).all()

    return {
        "students": [
            {
                "id": student.id,
                "batch_id": student.batch_id,
                "roll_number": student.roll_number,
                "name": student.name,
            }
            for student in students
        ]
    }


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

@router.get("/tests")
def list_tests(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    tests = access.institute_tests(db, user).order_by(Test.id).all()

    return {
        "tests": [
            {
                "id": test.id,
                "name": test.name,
                "subject": test.subject,
                "batch_id": test.batch_id,
                "test_date": test.test_date,
            }
            for test in tests
        ]
    }


def serialize_test(test: Test) -> dict:
    return {
        "id": test.id,
        "name": test.name,
        "subject": test.subject,
        "batch_id": test.batch_id,
        "test_date": test.test_date,
        "marks_correct": test.marks_correct,
        "marks_wrong": test.marks_wrong,
        "marks_blank": test.marks_blank,
    }


@router.get("/tests/{test_id}")
def get_test(test: Test = Depends(owned_test)):
    return serialize_test(test)


@router.get("/tests/{test_id}/questions")
def list_questions(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    questions = (
        db.query(Question)
        .filter(Question.test_id == test.id)
        .order_by(Question.question_number)
        .all()
    )

    return {
        "test_id": test.id,
        "questions": [
            {
                "id": question.id,
                "question_number": question.question_number,
                "subject": question.subject,
                "chapter_id": question.chapter_id,
                "topic_id": question.topic_id,
                "correct_answer": question.correct_answer,
                "difficulty": question.difficulty,
            }
            for question in questions
        ],
    }


# -------------------------------------------------------------------
# Evaluation
# -------------------------------------------------------------------

@router.post(
    "/tests/{test_id}/evaluate",
    dependencies=[Depends(require_admin)],
)
def evaluate_test_api(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    try:
        results = evaluate_test(db, test.id)

    except ValueError as exc:
        raise _not_found_from(exc)

    return {
        "test_id": test.id,
        "students_evaluated": len(results),
        "results": [
            {
                "student_id": result.student_id,
                "correct": result.correct_count,
                "wrong": result.wrong_count,
                "blank": result.blank_count,
                "marks": result.marks,
                "accuracy": result.accuracy,
            }
            for result in results
        ],
    }


# -------------------------------------------------------------------
# Analytics
# -------------------------------------------------------------------

@router.get("/tests/{test_id}/analytics/questions")
def question_analytics(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    try:
        return {
            "test_id": test.id,
            "questions": analyze_questions(db, test.id),
        }

    except ValueError as exc:
        raise _not_found_from(exc)


@router.get("/tests/{test_id}/analytics/chapters-topics")
def chapter_topic_analytics(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    try:
        data = analyze_topics_and_chapters(db, test.id)

        return {
            "test_id": test.id,
            "chapters": data["chapters"],
            "topics": data["topics"],
        }

    except ValueError as exc:
        raise _not_found_from(exc)


@router.get("/tests/{test_id}/analytics/students")
def student_analytics(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    try:
        return {
            "test_id": test.id,
            "students": analyze_students(db, test.id),
        }

    except ValueError as exc:
        raise _not_found_from(exc)


@router.get("/tests/{test_id}/analytics/batch")
def batch_analytics(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    try:
        return analyze_batch(db, test.id)

    except ValueError as exc:
        raise _not_found_from(exc)


# -------------------------------------------------------------------
# Teacher Action Report
# -------------------------------------------------------------------

@router.get("/tests/{test_id}/action-report")
def teacher_action_report(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    try:
        return generate_teacher_action_report(db, test.id)

    except ValueError as exc:
        raise _not_found_from(exc)


# -------------------------------------------------------------------
# Teacher Action Tracking
# -------------------------------------------------------------------

def _serialize_action(action: TeacherAction, db: Session) -> dict:
    question = (
        db.get(Question, action.question_id)
        if action.question_id
        else None
    )
    chapter = (
        db.get(Chapter, action.chapter_id)
        if action.chapter_id
        else None
    )
    topic = (
        db.get(Topic, action.topic_id)
        if action.topic_id
        else None
    )

    return {
        "id": action.id,
        "test_id": action.test_id,
        "question_id": action.question_id,
        "question_number": (
            question.question_number if question else None
        ),
        "chapter_id": action.chapter_id,
        "chapter_name": chapter.name if chapter else None,
        "topic_id": action.topic_id,
        "topic_name": topic.name if topic else None,
        "finding_type": action.finding_type,
        "finding_title": action.finding_title,
        "finding_reason": action.finding_reason,
        "action_type": action.action_type,
        "status": action.status,
        "note": action.note,
        "created_by_user_id": action.created_by_user_id,
        "created_at": action.created_at.isoformat(),
        "updated_at": action.updated_at.isoformat(),
    }


@router.post("/actions")
def create_teacher_action(
    payload: TeacherActionCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    test = access.find_test(db, user, payload.test_id)

    if test is None:
        raise HTTPException(status_code=404, detail="Test not found.")

    question_id = None
    chapter_id = payload.chapter_id
    topic_id = payload.topic_id

    if payload.question_number is not None:
        question = (
            db.query(Question)
            .filter(
                Question.test_id == test.id,
                Question.question_number == payload.question_number,
            )
            .first()
        )

        if question is None:
            raise HTTPException(
                status_code=404,
                detail="Question not found in this test.",
            )

        question_id = question.id

    if chapter_id is not None and access.find_chapter(db, user, chapter_id) is None:
        raise HTTPException(status_code=404, detail="Chapter not found.")

    if topic_id is not None:
        topic = access.find_topic(db, user, topic_id)

        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found.")

        if chapter_id is not None and topic.chapter_id != chapter_id:
            raise HTTPException(
                status_code=400,
                detail="Topic does not belong to the given chapter.",
            )

    action = TeacherAction(
        test_id=test.id,
        question_id=question_id,
        chapter_id=chapter_id,
        topic_id=topic_id,
        finding_type=payload.finding_type,
        finding_title=payload.finding_title,
        finding_reason=payload.finding_reason,
        action_type=payload.action_type,
        status=payload.status,
        note=payload.note,
        created_by_user_id=user.id,
    )

    db.add(action)
    db.commit()
    db.refresh(action)

    return _serialize_action(action, db)


@router.get("/tests/{test_id}/actions")
def list_teacher_actions(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    actions = (
        db.query(TeacherAction)
        .filter(TeacherAction.test_id == test.id)
        .order_by(TeacherAction.created_at, TeacherAction.id)
        .all()
    )

    return {
        "test_id": test.id,
        "actions": [_serialize_action(a, db) for a in actions],
    }


@router.get("/tests/{test_id}/actions/outcomes")
def teacher_action_outcomes(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    try:
        outcomes = get_action_outcomes(db, test.id)

    except ValueError as exc:
        raise _not_found_from(exc)

    return {"test_id": test.id, "outcomes": outcomes}


@router.patch("/actions/{action_id}")
def update_teacher_action(
    payload: TeacherActionUpdate,
    action: TeacherAction = Depends(owned_action),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    # Teachers edit only their own actions; admins can edit any action
    # in their institute (including ones recorded before sign-in existed).
    if user.role != "admin" and action.created_by_user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only edit actions you recorded.",
        )

    fields = payload.model_fields_set

    if "action_type" in fields and payload.action_type is not None:
        action.action_type = payload.action_type

    if "status" in fields and payload.status is not None:
        action.status = payload.status

    if "note" in fields:
        action.note = payload.note

    action.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(action)

    return _serialize_action(action, db)


# -------------------------------------------------------------------
# Test-to-Test Progress
# -------------------------------------------------------------------

@router.get("/tests/{previous_test_id}/compare/{current_test_id}")
def test_progress(
    tests: tuple[Test, Test] = Depends(owned_test_pair),
    db: Session = Depends(get_db),
):
    previous_test, current_test = tests

    try:
        return compare_tests(db, previous_test.id, current_test.id)

    except ValueError as exc:
        raise _not_found_from(exc)


# -------------------------------------------------------------------
# Question Investigation
# -------------------------------------------------------------------

@router.get("/tests/{test_id}/questions/{question_number}/investigation")
def question_investigation(
    question_number: int,
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    """
    Return the evidence needed to investigate one question:
    question metadata, aggregate performance, and every student's answer.
    """

    question = (
        db.query(Question)
        .filter(
            Question.test_id == test.id,
            Question.question_number == question_number,
        )
        .first()
    )

    if question is None:
        raise HTTPException(
            status_code=404,
            detail=f"Question {question_number} not found.",
        )

    chapter = db.get(Chapter, question.chapter_id)
    topic = db.get(Topic, question.topic_id)

    students = (
        db.query(Student)
        .filter(Student.batch_id == test.batch_id)
        .order_by(Student.roll_number)
        .all()
    )

    answers = {
        row.student_id: row.answer
        for row in db.query(StudentAnswer).filter(
            StudentAnswer.test_id == test.id,
            StudentAnswer.question_id == question.id,
        )
    }

    student_rows = []

    correct_count = 0
    wrong_count = 0
    blank_count = 0

    for student in students:
        answer = answers.get(student.id)

        outcome = classify_answer(answer, question.correct_answer)
        result = outcome.capitalize()

        if outcome == "blank":
            blank_count += 1
        elif outcome == "correct":
            correct_count += 1
        else:
            wrong_count += 1

        student_rows.append(
            {
                "student_id": student.id,
                "roll_number": student.roll_number,
                "student_name": student.name,
                "answer": answer,
                "result": result,
            }
        )

    total_students = len(students)

    def percentage(count):
        if total_students == 0:
            return 0.0
        return round((count / total_students) * 100, 2)

    return {
        "test_id": test.id,
        "test_name": test.name,
        "question": {
            "id": question.id,
            "question_number": question.question_number,
            "subject": question.subject,
            "chapter_id": question.chapter_id,
            "chapter_name": chapter.name if chapter else None,
            "topic_id": question.topic_id,
            "topic_name": topic.name if topic else None,
            "correct_answer": question.correct_answer,
            "difficulty": question.difficulty,
        },
        "performance": {
            "total_students": total_students,
            "correct_count": correct_count,
            "wrong_count": wrong_count,
            "blank_count": blank_count,
            "correct_percentage": percentage(correct_count),
            "wrong_percentage": percentage(wrong_count),
            "blank_percentage": percentage(blank_count),
        },
        "students": student_rows,
    }
