from sqlalchemy.orm import Session

from ..database.models import Test
from .analytics import analyze_students


def compare_tests(
    db: Session,
    previous_test_id: int,
    current_test_id: int,
) -> dict:
    """
    Compare student and batch performance between two tests.

    The comparison is based on marks, accuracy, correct/wrong/blank
    answers, and chapter/topic performance.
    """

    previous_test = db.get(Test, previous_test_id)
    current_test = db.get(Test, current_test_id)

    if previous_test is None:
        raise ValueError(f"Previous test {previous_test_id} not found.")

    if current_test is None:
        raise ValueError(f"Current test {current_test_id} not found.")

    previous_students = analyze_students(db, previous_test_id)
    current_students = analyze_students(db, current_test_id)

    previous_map = {
        student["student_id"]: student
        for student in previous_students
    }

    current_map = {
        student["student_id"]: student
        for student in current_students
    }

    common_student_ids = sorted(
        set(previous_map.keys()) & set(current_map.keys())
    )

    student_progress = []

    for student_id in common_student_ids:
        previous = previous_map[student_id]
        current = current_map[student_id]

        student_progress.append(
            {
                "student_id": student_id,
                "roll_number": current["roll_number"],
                "student_name": current["student_name"],
                "previous_marks": previous["marks"],
                "current_marks": current["marks"],
                "marks_change": round(
                    current["marks"] - previous["marks"], 2
                ),
                "previous_accuracy": previous["accuracy"],
                "current_accuracy": current["accuracy"],
                "accuracy_change": round(
                    current["accuracy"] - previous["accuracy"], 2
                ),
                "previous_correct": previous["correct"],
                "current_correct": current["correct"],
                "previous_wrong": previous["wrong"],
                "current_wrong": current["wrong"],
                "previous_blank": previous["blank"],
                "current_blank": current["blank"],
            }
        )

    student_progress.sort(
        key=lambda x: x["marks_change"],
        reverse=True,
    )

    if student_progress:
        average_previous_marks = round(
            sum(x["previous_marks"] for x in student_progress)
            / len(student_progress),
            2,
        )

        average_current_marks = round(
            sum(x["current_marks"] for x in student_progress)
            / len(student_progress),
            2,
        )

        average_previous_accuracy = round(
            sum(x["previous_accuracy"] for x in student_progress)
            / len(student_progress),
            2,
        )

        average_current_accuracy = round(
            sum(x["current_accuracy"] for x in student_progress)
            / len(student_progress),
            2,
        )
    else:
        average_previous_marks = 0.0
        average_current_marks = 0.0
        average_previous_accuracy = 0.0
        average_current_accuracy = 0.0

    improved_students = [
        student
        for student in student_progress
        if student["marks_change"] > 0
    ]

    declined_students = [
        student
        for student in student_progress
        if student["marks_change"] < 0
    ]

    unchanged_students = [
        student
        for student in student_progress
        if student["marks_change"] == 0
    ]

    return {
        "previous_test": {
            "id": previous_test.id,
            "name": previous_test.name,
            "subject": previous_test.subject,
            "test_date": previous_test.test_date,
        },
        "current_test": {
            "id": current_test.id,
            "name": current_test.name,
            "subject": current_test.subject,
            "test_date": current_test.test_date,
        },
        "common_student_count": len(common_student_ids),
        "batch_comparison": {
            "average_previous_marks": average_previous_marks,
            "average_current_marks": average_current_marks,
            "average_marks_change": round(
                average_current_marks - average_previous_marks,
                2,
            ),
            "average_previous_accuracy": average_previous_accuracy,
            "average_current_accuracy": average_current_accuracy,
            "average_accuracy_change": round(
                average_current_accuracy - average_previous_accuracy,
                2,
            ),
        },
        "student_summary": {
            "improved": len(improved_students),
            "declined": len(declined_students),
            "unchanged": len(unchanged_students),
        },
        "improved_students": improved_students,
        "declined_students": declined_students,
        "unchanged_students": unchanged_students,
        "students": student_progress,
    }
