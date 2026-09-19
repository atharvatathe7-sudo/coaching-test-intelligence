from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database.connection import get_db
from .database.models import (
    Institute,
    Batch,
    Student,
    Test,
    Question,
)
from .schemas.api import (
    InstituteCreate,
    BatchCreate,
    StudentCreate,
    TestCreate,
    QuestionCreate,
)
from .services.evaluation import evaluate_test
from .services.analytics import (
    analyze_questions,
    analyze_topics_and_chapters,
    analyze_students,
    analyze_batch,
)
from .services.action_report import generate_teacher_action_report
from .services.progress import compare_tests


router = APIRouter(prefix="/api")


@router.get("/status")
def api_status():
    return {
        "status": "ok",
        "service": "Coaching Test Intelligence API",
        "version": "0.1.0",
    }


# -------------------------------------------------------------------
# Institutes
# -------------------------------------------------------------------

@router.post("/institutes")
def create_institute(
    payload: InstituteCreate,
    db: Session = Depends(get_db),
):
    institute = Institute(name=payload.name)
    db.add(institute)
    db.commit()
    db.refresh(institute)

    return {
        "id": institute.id,
        "name": institute.name,
    }


@router.get("/institutes")
def list_institutes(db: Session = Depends(get_db)):
    institutes = db.query(Institute).order_by(Institute.id).all()

    return {
        "institutes": [
            {
                "id": institute.id,
                "name": institute.name,
            }
            for institute in institutes
        ]
    }


# -------------------------------------------------------------------
# Batches
# -------------------------------------------------------------------

@router.post("/batches")
def create_batch(
    payload: BatchCreate,
    db: Session = Depends(get_db),
):
    institute = db.get(Institute, payload.institute_id)

    if institute is None:
        raise HTTPException(
            status_code=404,
            detail=f"Institute {payload.institute_id} not found.",
        )

    batch = Batch(
        institute_id=payload.institute_id,
        name=payload.name,
    )

    db.add(batch)
    db.commit()
    db.refresh(batch)

    return {
        "id": batch.id,
        "institute_id": batch.institute_id,
        "name": batch.name,
    }


@router.get("/batches")
def list_batches(db: Session = Depends(get_db)):
    batches = db.query(Batch).order_by(Batch.id).all()

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

@router.post("/students")
def create_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
):
    batch = db.get(Batch, payload.batch_id)

    if batch is None:
        raise HTTPException(
            status_code=404,
            detail=f"Batch {payload.batch_id} not found.",
        )

    student = Student(
        batch_id=payload.batch_id,
        roll_number=payload.roll_number,
        name=payload.name,
    )

    db.add(student)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not create student. Roll number may already exist in this batch.",
        )

    db.refresh(student)

    return {
        "id": student.id,
        "batch_id": student.batch_id,
        "roll_number": student.roll_number,
        "name": student.name,
    }


@router.get("/students")
def list_students(
    batch_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Student)

    if batch_id is not None:
        query = query.filter(Student.batch_id == batch_id)

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

@router.post("/tests")
def create_test(
    payload: TestCreate,
    db: Session = Depends(get_db),
):
    batch = db.get(Batch, payload.batch_id)

    if batch is None:
        raise HTTPException(
            status_code=404,
            detail=f"Batch {payload.batch_id} not found.",
        )

    test = Test(
        batch_id=payload.batch_id,
        name=payload.name,
        subject=payload.subject,
        test_date=payload.test_date,
        marks_correct=payload.marks_correct,
        marks_wrong=payload.marks_wrong,
        marks_blank=payload.marks_blank,
    )

    db.add(test)
    db.commit()
    db.refresh(test)

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


@router.get("/tests")
def list_tests(db: Session = Depends(get_db)):
    tests = db.query(Test).order_by(Test.id).all()

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


@router.get("/tests/{test_id}")
def get_test(
    test_id: int,
    db: Session = Depends(get_db),
):
    test = db.get(Test, test_id)

    if test is None:
        raise HTTPException(
            status_code=404,
            detail=f"Test {test_id} not found.",
        )

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


# -------------------------------------------------------------------
# Questions
# -------------------------------------------------------------------

@router.post("/questions")
def create_question(
    payload: QuestionCreate,
    db: Session = Depends(get_db),
):
    test = db.get(Test, payload.test_id)

    if test is None:
        raise HTTPException(
            status_code=404,
            detail=f"Test {payload.test_id} not found.",
        )

    question = Question(
        test_id=payload.test_id,
        question_number=payload.question_number,
        subject=payload.subject,
        chapter_id=payload.chapter_id,
        topic_id=payload.topic_id,
        correct_answer=payload.correct_answer,
        difficulty=payload.difficulty,
    )

    db.add(question)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not create question. Question number may already exist for this test.",
        )

    db.refresh(question)

    return {
        "id": question.id,
        "test_id": question.test_id,
        "question_number": question.question_number,
        "subject": question.subject,
        "chapter_id": question.chapter_id,
        "topic_id": question.topic_id,
        "correct_answer": question.correct_answer,
        "difficulty": question.difficulty,
    }


@router.get("/tests/{test_id}/questions")
def list_questions(
    test_id: int,
    db: Session = Depends(get_db),
):
    test = db.get(Test, test_id)

    if test is None:
        raise HTTPException(
            status_code=404,
            detail=f"Test {test_id} not found.",
        )

    questions = (
        db.query(Question)
        .filter(Question.test_id == test_id)
        .order_by(Question.question_number)
        .all()
    )

    return {
        "test_id": test_id,
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

@router.post("/tests/{test_id}/evaluate")
def evaluate_test_api(
    test_id: int,
    db: Session = Depends(get_db),
):
    try:
        results = evaluate_test(db, test_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    return {
        "test_id": test_id,
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
    test_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {
            "test_id": test_id,
            "questions": analyze_questions(db, test_id),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )


@router.get("/tests/{test_id}/analytics/chapters-topics")
def chapter_topic_analytics(
    test_id: int,
    db: Session = Depends(get_db),
):
    try:
        data = analyze_topics_and_chapters(db, test_id)

        return {
            "test_id": test_id,
            "chapters": data["chapters"],
            "topics": data["topics"],
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )


@router.get("/tests/{test_id}/analytics/students")
def student_analytics(
    test_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {
            "test_id": test_id,
            "students": analyze_students(db, test_id),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )


@router.get("/tests/{test_id}/analytics/batch")
def batch_analytics(
    test_id: int,
    db: Session = Depends(get_db),
):
    try:
        return analyze_batch(db, test_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )


# -------------------------------------------------------------------
# Teacher Action Report
# -------------------------------------------------------------------

@router.get("/tests/{test_id}/action-report")
def teacher_action_report(
    test_id: int,
    db: Session = Depends(get_db),
):
    try:
        return generate_teacher_action_report(db, test_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )


# -------------------------------------------------------------------
# Test-to-Test Progress
# -------------------------------------------------------------------

@router.get("/tests/{previous_test_id}/compare/{current_test_id}")
def test_progress(
    previous_test_id: int,
    current_test_id: int,
    db: Session = Depends(get_db),
):
    try:
        return compare_tests(
            db,
            previous_test_id,
            current_test_id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )
