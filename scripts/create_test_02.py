from datetime import date

from backend.app.database.connection import SessionLocal
from backend.app.database.models import (
    Student,
    StudentAnswer,
    Test,
    Question,
)

db = SessionLocal()

try:
    existing = (
        db.query(Test)
        .filter(Test.name == "Physics Test 02")
        .first()
    )

    if existing:
        print("Physics Test 02 already exists.")
        print("Test ID:", existing.id)
        raise SystemExit

    test_01 = (
        db.query(Test)
        .filter(Test.name == "Physics Test 01")
        .first()
    )

    if test_01 is None:
        raise ValueError("Physics Test 01 not found.")

    students = (
        db.query(Student)
        .filter(Student.batch_id == test_01.batch_id)
        .order_by(Student.id)
        .all()
    )

    questions_01 = (
        db.query(Question)
        .filter(Question.test_id == test_01.id)
        .order_by(Question.question_number)
        .all()
    )

    if not students:
        raise ValueError("No students found.")

    if not questions_01:
        raise ValueError("No questions found for Test 01.")

    test_02 = Test(
        batch_id=test_01.batch_id,
        name="Physics Test 02",
        subject=test_01.subject,
        test_date=date.today(),
        marks_correct=test_01.marks_correct,
        marks_wrong=test_01.marks_wrong,
        marks_blank=test_01.marks_blank,
    )

    db.add(test_02)
    db.flush()

    question_map = {}

    for old_question in questions_01:
        new_question = Question(
            test_id=test_02.id,
            question_number=old_question.question_number,
            subject=old_question.subject,
            chapter_id=old_question.chapter_id,
            topic_id=old_question.topic_id,
            correct_answer=old_question.correct_answer,
            difficulty=old_question.difficulty,
        )

        db.add(new_question)
        db.flush()

        question_map[old_question.id] = new_question

    # Create a different performance pattern for Test 02.
    # Some students improve, some decline, and some remain similar.
    for student_index, student in enumerate(students):
        for question_index, old_question in enumerate(questions_01):
            new_question = question_map[old_question.id]

            pattern = (
                student_index * 7
                + question_index * 11
                + student.id
            ) % 10

            if pattern <= 4:
                answer = old_question.correct_answer

            elif pattern <= 7:
                wrong_answers = [
                    option
                    for option in ["A", "B", "C", "D"]
                    if option != old_question.correct_answer
                ]
                answer = wrong_answers[
                    (student_index + question_index) % len(wrong_answers)
                ]

            else:
                answer = None

            db.add(
                StudentAnswer(
                    test_id=test_02.id,
                    student_id=student.id,
                    question_id=new_question.id,
                    answer=answer,
                )
            )

    db.commit()

    print("Created:", test_02.name)
    print("Test ID:", test_02.id)
    print("Students:", len(students))
    print("Questions:", len(questions_01))
    print("Student answers:", len(students) * len(questions_01))

finally:
    db.close()
