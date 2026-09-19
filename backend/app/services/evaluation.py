from sqlalchemy.orm import Session

from ..database.models import Question, StudentAnswer, Test, TestResult


def evaluate_test(db: Session, test_id: int) -> list[TestResult]:
    """
    Evaluate every student's answers for one test.

    Compares student answers with the official answer key,
    calculates correct/wrong/blank counts, marks, and accuracy,
    and stores the results in the test_results table.
    """

    test = db.get(Test, test_id)

    if test is None:
        raise ValueError(f"Test {test_id} not found.")

    questions = (
        db.query(Question)
        .filter(Question.test_id == test_id)
        .all()
    )

    if not questions:
        raise ValueError(f"Test {test_id} has no questions.")

    question_map = {
        question.id: question
        for question in questions
    }

    student_ids = (
        db.query(StudentAnswer.student_id)
        .filter(StudentAnswer.test_id == test_id)
        .distinct()
        .all()
    )

    student_ids = [row[0] for row in student_ids]

    if not student_ids:
        raise ValueError(f"Test {test_id} has no student answers.")

    # Remove previous calculated results for this test.
    db.query(TestResult).filter(
        TestResult.test_id == test_id
    ).delete(synchronize_session=False)

    results = []

    for student_id in student_ids:
        answers = (
            db.query(StudentAnswer)
            .filter(
                StudentAnswer.test_id == test_id,
                StudentAnswer.student_id == student_id,
            )
            .all()
        )

        correct_count = 0
        wrong_count = 0
        blank_count = 0

        for student_answer in answers:
            question = question_map.get(student_answer.question_id)

            if question is None:
                continue

            answer = student_answer.answer

            if answer is None or answer.strip() == "":
                blank_count += 1

            elif answer.strip().upper() == question.correct_answer.strip().upper():
                correct_count += 1

            else:
                wrong_count += 1

        total_attempted = correct_count + wrong_count

        if total_attempted > 0:
            accuracy = (correct_count / total_attempted) * 100
        else:
            accuracy = 0.0

        marks = (
            correct_count * test.marks_correct
            + wrong_count * test.marks_wrong
            + blank_count * test.marks_blank
        )

        result = TestResult(
            test_id=test_id,
            student_id=student_id,
            correct_count=correct_count,
            wrong_count=wrong_count,
            blank_count=blank_count,
            marks=marks,
            accuracy=accuracy,
        )

        db.add(result)
        results.append(result)

    db.commit()

    for result in results:
        db.refresh(result)

    return results
