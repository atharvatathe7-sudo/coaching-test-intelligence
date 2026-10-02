from sqlalchemy.orm import Session

from ..database.models import Question, Test
from .analytics import analyze_students, analyze_topics_and_chapters

# Changes smaller than this (in percentage points) are reported as
# "unchanged" for chapters/topics, since small differences are noise.
UNCHANGED_THRESHOLD_PP = 0.5


def _status(change: float) -> str:
    if change >= UNCHANGED_THRESHOLD_PP:
        return "improved"
    if change <= -UNCHANGED_THRESHOLD_PP:
        return "declined"
    return "unchanged"


def _compare_groups(
    previous: list[dict],
    current: list[dict],
    key: str,
    name_key: str,
    extra_keys: tuple[str, ...] = (),
) -> list[dict]:
    """
    Compare chapter or topic stats between two tests.

    Performance is the percentage of correct responses, which is
    normalized by the number of responses, so tests with different
    sizes remain comparable. Items present in only one test are
    returned with change fields set to None.
    """

    previous_map = {item[key]: item for item in previous}
    current_map = {item[key]: item for item in current}

    rows = []

    for item_id in set(previous_map) | set(current_map):
        prev = previous_map.get(item_id)
        curr = current_map.get(item_id)
        source = curr or prev

        row = {
            key: item_id,
            name_key: source[name_key],
            "previous_percentage": (
                prev["correct_percentage"] if prev else None
            ),
            "current_percentage": (
                curr["correct_percentage"] if curr else None
            ),
            "previous_questions": prev["questions"] if prev else 0,
            "current_questions": curr["questions"] if curr else 0,
        }

        for extra in extra_keys:
            row[extra] = source[extra]

        if prev and curr:
            change = round(
                curr["correct_percentage"]
                - prev["correct_percentage"],
                2,
            )
            row["change_pp"] = change
            row["status"] = _status(change)
        else:
            row["change_pp"] = None
            row["status"] = (
                "only_in_current" if curr else "only_in_previous"
            )

        rows.append(row)

    rows.sort(
        key=lambda r: (
            r["change_pp"] is None,
            -(r["change_pp"] or 0),
            r[name_key],
        )
    )

    return rows


def _max_marks(db: Session, test: Test) -> float:
    question_count = (
        db.query(Question)
        .filter(Question.test_id == test.id)
        .count()
    )
    return question_count * test.marks_correct


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

    previous_topics = analyze_topics_and_chapters(db, previous_test_id)
    current_topics = analyze_topics_and_chapters(db, current_test_id)

    chapter_progress = _compare_groups(
        previous_topics["chapters"],
        current_topics["chapters"],
        "chapter_id",
        "chapter_name",
        ("subject",),
    )

    topic_progress = _compare_groups(
        previous_topics["topics"],
        current_topics["topics"],
        "topic_id",
        "topic_name",
        ("chapter_id", "chapter_name"),
    )

    def _movers(rows: list[dict], status: str, reverse: bool) -> list[dict]:
        matched = [r for r in rows if r["status"] == status]
        matched.sort(key=lambda r: r["change_pp"], reverse=reverse)
        return matched[:3]

    # Marks as a percentage of the maximum possible marks, so tests
    # with different question counts or marking schemes compare fairly.
    previous_max = _max_marks(db, previous_test)
    current_max = _max_marks(db, current_test)

    def _pct(marks: float, maximum: float) -> float:
        return round(marks / maximum * 100, 2) if maximum else 0.0

    previous_pct = _pct(average_previous_marks, previous_max)
    current_pct = _pct(average_current_marks, current_max)

    comparability_notes = []

    if previous_test.batch_id != current_test.batch_id:
        comparability_notes.append(
            "The tests belong to different batches."
        )
    if previous_test.subject != current_test.subject:
        comparability_notes.append(
            "The tests cover different subjects."
        )
    if previous_max != current_max:
        comparability_notes.append(
            "The tests have different maximum marks; use the "
            "percentage-of-maximum figures rather than raw marks."
        )
    if any(
        r["status"] in ("only_in_previous", "only_in_current")
        for r in chapter_progress + topic_progress
    ):
        comparability_notes.append(
            "Some chapters/topics appear in only one test and are "
            "not compared."
        )

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
            "previous_max_marks": previous_max,
            "current_max_marks": current_max,
            "previous_marks_percentage": previous_pct,
            "current_marks_percentage": current_pct,
            "marks_percentage_change_pp": round(
                current_pct - previous_pct, 2
            ),
        },
        "comparability_notes": comparability_notes,
        "unchanged_threshold_pp": UNCHANGED_THRESHOLD_PP,
        "chapter_progress": chapter_progress,
        "topic_progress": topic_progress,
        "biggest_improvements": {
            "chapters": _movers(chapter_progress, "improved", True),
            "topics": _movers(topic_progress, "improved", True),
        },
        "biggest_declines": {
            "chapters": _movers(chapter_progress, "declined", False),
            "topics": _movers(topic_progress, "declined", False),
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
