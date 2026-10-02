"""
CSV data imports: roster, test setup (answer key + chapter/topic
mapping) and student answers.

Every import follows the same stages:

    parse CSV  ->  validate (read-only)  ->  commit (one transaction)

Validation never writes. Commit only runs when validation found no
errors, and it runs inside a single transaction: any failure rolls
everything back, so an import is never left half-done.

Rows are matched by natural identifiers (roll number, question number,
normalized chapter/topic name), never by database IDs.
"""

import logging
import math
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database.models import (
    Batch,
    Chapter,
    Question,
    Student,
    StudentAnswer,
    Test,
    TestResult,
    Topic,
)
from .evaluation import evaluate_test
from .import_csv import (
    ANSWER_OPTIONS,
    ImportReport,
    clean_text,
    normalize_name,
    parse_csv,
)

logger = logging.getLogger(__name__)

ROSTER_FILE = "roster.csv"
TEST_SETUP_FILE = "test_setup.csv"
ANSWERS_FILE = "answers.csv"

ROSTER_COLUMNS = ("roll_number", "name")
TEST_SETUP_COLUMNS = (
    "question_number",
    "correct_answer",
    "chapter",
    "topic",
)
ANSWER_COLUMNS = ("roll_number", "question_number", "answer")


def _finish(report: ImportReport, dry_run: bool, committed: bool) -> dict:
    if report.has_errors:
        return report.to_dict("invalid")

    if dry_run or not committed:
        return report.to_dict("valid")

    return report.to_dict("imported")


def _commit_failed(report: ImportReport, file: str, exc: Exception) -> None:
    logger.exception("Import commit failed")

    if isinstance(exc, IntegrityError):
        message = (
            "The data conflicts with existing records. "
            "Nothing was imported."
        )
    else:
        message = "An unexpected error occurred. Nothing was imported."

    report.error(file, message)


def _parse_question_number(value: str) -> int | None:
    try:
        number = int(value)
    except ValueError:
        return None

    return number if number > 0 else None


# -------------------------------------------------------------------
# Roster
# -------------------------------------------------------------------

def validate_roster_rows(
    rows: list[tuple[int, dict]],
    existing: dict[str, str],
    report: ImportReport,
) -> list[dict]:
    """
    Validate roster rows. Returns the students that would be created.

    existing maps normalized roll number -> name for the batch.
    An existing roll number with the same name is skipped (warning);
    with a different name it is a conflict (error), so a name is never
    silently overwritten.
    """

    seen: dict[str, int] = {}
    to_create: list[dict] = []

    for line, row in rows:
        roll = clean_text(row["roll_number"])
        name = clean_text(row["name"])

        if not roll:
            report.error(
                ROSTER_FILE, "Roll number is blank.",
                row=line, field="roll_number",
            )
            continue

        if not name:
            report.error(
                ROSTER_FILE, "Student name is blank.",
                row=line, field="name", value=roll,
            )
            continue

        key = normalize_name(roll)

        if key in seen:
            report.error(
                ROSTER_FILE,
                f"Duplicate roll number (first seen on row {seen[key]}).",
                row=line, field="roll_number", value=roll,
            )
            continue

        seen[key] = line

        if key in existing:
            if normalize_name(existing[key]) == normalize_name(name):
                report.warning(
                    ROSTER_FILE,
                    "Student already exists in this batch; skipped.",
                    row=line, field="roll_number", value=roll,
                )
            else:
                report.error(
                    ROSTER_FILE,
                    f"Roll number already belongs to '{existing[key]}' "
                    "in this batch. Existing names are not overwritten.",
                    row=line, field="roll_number", value=roll,
                )
            continue

        to_create.append({"roll_number": roll, "name": name})

    return to_create


def import_roster(
    db: Session,
    batch_id: int,
    raw: bytes,
    dry_run: bool = True,
) -> dict:
    report = ImportReport()
    batch = db.get(Batch, batch_id)

    if batch is None:
        report.error(
            ROSTER_FILE, "Batch not found.",
            field="batch_id", value=batch_id,
        )

    rows = parse_csv(raw, ROSTER_FILE, ROSTER_COLUMNS, report)

    existing = {}

    if batch is not None:
        existing = {
            normalize_name(s.roll_number): s.name
            for s in db.query(Student).filter(Student.batch_id == batch_id)
        }

    to_create = validate_roster_rows(rows, existing, report)

    report.summary = {
        "rows": len(rows),
        "students_to_create": len(to_create),
        "already_existing": len(rows) - len(to_create),
    }

    if report.has_errors or dry_run:
        return _finish(report, dry_run, committed=False)

    try:
        db.add_all(
            Student(
                batch_id=batch_id,
                roll_number=item["roll_number"],
                name=item["name"],
            )
            for item in to_create
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        _commit_failed(report, ROSTER_FILE, exc)
        return _finish(report, dry_run, committed=False)

    report.summary["students_created"] = len(to_create)

    return _finish(report, dry_run, committed=True)


# -------------------------------------------------------------------
# Test setup
# -------------------------------------------------------------------

def _validate_marks(report: ImportReport, field: str, value) -> float | None:
    text = clean_text(str(value) if value is not None else "")

    if not text:
        report.error(
            TEST_SETUP_FILE, "Marks value is blank.",
            field=field,
        )
        return None

    try:
        number = float(text)
    except ValueError:
        number = math.nan

    if not math.isfinite(number):
        report.error(
            TEST_SETUP_FILE, "Marks must be a number.",
            field=field, value=text,
        )
        return None

    return number


def validate_test_metadata(
    db: Session,
    batch_id: int,
    test_name: str,
    subject: str,
    test_date: str,
    marks_correct,
    marks_wrong,
    marks_blank,
    report: ImportReport,
) -> dict | None:
    """Validate the test-level fields. Returns clean values or None."""

    before = len(report.errors)

    batch = db.get(Batch, batch_id)

    if batch is None:
        report.error(
            TEST_SETUP_FILE, "Batch not found.",
            field="batch_id", value=batch_id,
        )

    name = clean_text(test_name)
    subject_clean = clean_text(subject)

    if not name:
        report.error(
            TEST_SETUP_FILE, "Test name is blank.", field="test_name",
        )

    if not subject_clean:
        report.error(
            TEST_SETUP_FILE, "Subject is blank.", field="subject",
        )

    parsed_date = None
    date_text = clean_text(test_date)

    if not date_text:
        report.error(
            TEST_SETUP_FILE, "Test date is blank.", field="test_date",
        )
    else:
        try:
            parsed_date = date.fromisoformat(date_text)
        except ValueError:
            report.error(
                TEST_SETUP_FILE,
                "Test date must be in YYYY-MM-DD format.",
                field="test_date", value=date_text,
            )

    correct = _validate_marks(report, "marks_correct", marks_correct)
    wrong = _validate_marks(report, "marks_wrong", marks_wrong)
    blank = _validate_marks(report, "marks_blank", marks_blank)

    if correct is not None and correct <= 0:
        report.error(
            TEST_SETUP_FILE, "Marks for a correct answer must be positive.",
            field="marks_correct", value=correct,
        )

    if wrong is not None and wrong > 0:
        report.warning(
            TEST_SETUP_FILE,
            "Marks for a wrong answer are positive; "
            "negative marking is usually zero or below.",
            field="marks_wrong", value=wrong,
        )

    if (
        batch is not None
        and name
        and parsed_date is not None
    ):
        for other in db.query(Test).filter(
            Test.batch_id == batch_id,
            Test.test_date == parsed_date,
        ):
            if normalize_name(other.name) == normalize_name(name):
                report.error(
                    TEST_SETUP_FILE,
                    "A test with this name and date already exists in "
                    "this batch. Replacing a test is not supported.",
                    field="test_name", value=name,
                )
                break

    if len(report.errors) > before:
        return None

    return {
        "batch_id": batch_id,
        "name": name,
        "subject": subject_clean,
        "test_date": parsed_date,
        "marks_correct": correct,
        "marks_wrong": wrong,
        "marks_blank": blank,
    }


def validate_question_rows(
    rows: list[tuple[int, dict]],
    report: ImportReport,
) -> list[dict]:
    """Validate answer-key rows. Returns the clean question list."""

    seen: dict[int, int] = {}
    questions: list[dict] = []

    for line, row in rows:
        raw_number = row["question_number"]
        number = _parse_question_number(raw_number)
        ok = True

        if number is None:
            report.error(
                TEST_SETUP_FILE,
                "Question number must be a positive whole number.",
                row=line, field="question_number", value=raw_number,
            )
            ok = False
        elif number in seen:
            report.error(
                TEST_SETUP_FILE,
                f"Duplicate question number (first seen on row "
                f"{seen[number]}).",
                row=line, field="question_number", value=raw_number,
            )
            ok = False
        else:
            seen[number] = line

        answer = row["correct_answer"].strip().upper()

        if answer not in ANSWER_OPTIONS:
            report.error(
                TEST_SETUP_FILE,
                "Correct answer must be one of "
                f"{', '.join(ANSWER_OPTIONS)}.",
                row=line, field="correct_answer",
                value=row["correct_answer"],
            )
            ok = False

        chapter = clean_text(row["chapter"])
        topic = clean_text(row["topic"])

        if not chapter:
            report.error(
                TEST_SETUP_FILE, "Chapter is blank.",
                row=line, field="chapter",
            )
            ok = False

        if not topic:
            report.error(
                TEST_SETUP_FILE, "Topic is blank.",
                row=line, field="topic",
            )
            ok = False

        if ok:
            questions.append(
                {
                    "row": line,
                    "question_number": number,
                    "correct_answer": answer,
                    "chapter": chapter,
                    "topic": topic,
                }
            )

    return questions


def plan_chapters_topics(
    questions: list[dict],
    subject: str,
    existing_chapters: dict[tuple[str, str], int],
    existing_topics: set[tuple[int, str]],
    report: ImportReport,
) -> tuple[dict, dict]:
    """
    Work out which chapters/topics are new and warn about each one.

    existing_chapters maps (normalized subject, normalized name) -> id,
    existing_topics holds (chapter id, normalized topic name).
    Returns (new_chapters, new_topics) keyed by normalized name.
    """

    subject_key = normalize_name(subject)
    new_chapters: dict[str, dict] = {}
    new_topics: dict[tuple[str, str], dict] = {}

    for item in questions:
        chapter_key = normalize_name(item["chapter"])
        topic_key = normalize_name(item["topic"])
        chapter_id = existing_chapters.get((subject_key, chapter_key))

        if chapter_id is None and chapter_key not in new_chapters:
            new_chapters[chapter_key] = {"name": item["chapter"]}
            report.warning(
                TEST_SETUP_FILE,
                f"New chapter '{item['chapter']}' will be created.",
                row=item["row"], field="chapter", value=item["chapter"],
            )

        topic_exists = (
            chapter_id is not None
            and (chapter_id, topic_key) in existing_topics
        )

        if not topic_exists and (chapter_key, topic_key) not in new_topics:
            new_topics[(chapter_key, topic_key)] = {"name": item["topic"]}
            report.warning(
                TEST_SETUP_FILE,
                f"New topic '{item['topic']}' will be created.",
                row=item["row"], field="topic", value=item["topic"],
            )

    return new_chapters, new_topics


def import_test_setup(
    db: Session,
    *,
    batch_id: int,
    test_name: str,
    subject: str,
    test_date: str,
    marks_correct,
    marks_wrong,
    marks_blank,
    raw: bytes,
    dry_run: bool = True,
    confirm_new_chapters_topics: bool = False,
) -> dict:
    report = ImportReport()

    meta = validate_test_metadata(
        db, batch_id, test_name, subject, test_date,
        marks_correct, marks_wrong, marks_blank, report,
    )

    rows = parse_csv(raw, TEST_SETUP_FILE, TEST_SETUP_COLUMNS, report)
    questions = validate_question_rows(rows, report)

    if not rows and not report.has_errors:
        report.error(TEST_SETUP_FILE, "File has no question rows.")

    numbers = sorted(q["question_number"] for q in questions)

    if numbers and numbers != list(range(1, len(numbers) + 1)):
        missing = sorted(set(range(1, numbers[-1] + 1)) - set(numbers))
        report.warning(
            TEST_SETUP_FILE,
            "Question numbers are not continuous from 1"
            + (
                f" (missing: {', '.join(map(str, missing[:10]))})."
                if missing
                else "."
            ),
        )

    subject_clean = clean_text(subject)

    existing_chapters = {
        (normalize_name(c.subject), normalize_name(c.name)): c.id
        for c in db.query(Chapter)
    }
    existing_topics = {
        (t.chapter_id, normalize_name(t.name)) for t in db.query(Topic)
    }

    new_chapters, new_topics = plan_chapters_topics(
        questions,
        subject_clean,
        existing_chapters,
        existing_topics,
        report,
    )

    needs_confirmation = bool(new_chapters or new_topics)

    report.summary = {
        "questions": len(questions),
        "new_chapters": len(new_chapters),
        "new_topics": len(new_topics),
        "requires_confirmation": needs_confirmation,
    }

    if (
        not dry_run
        and needs_confirmation
        and not confirm_new_chapters_topics
        and not report.has_errors
    ):
        report.error(
            TEST_SETUP_FILE,
            f"{len(new_chapters)} new chapters and {len(new_topics)} new "
            "topics would be created. Confirm to proceed.",
            field="confirm_new_chapters_topics",
        )

    if report.has_errors or dry_run or meta is None:
        return _finish(report, dry_run, committed=False)

    try:
        test = Test(
            batch_id=meta["batch_id"],
            name=meta["name"],
            subject=meta["subject"],
            test_date=meta["test_date"],
            marks_correct=meta["marks_correct"],
            marks_wrong=meta["marks_wrong"],
            marks_blank=meta["marks_blank"],
        )
        db.add(test)
        db.flush()

        chapter_ids = dict(existing_chapters)
        subject_key = normalize_name(subject_clean)

        for chapter_key, info in new_chapters.items():
            chapter = Chapter(subject=subject_clean, name=info["name"])
            db.add(chapter)
            db.flush()
            chapter_ids[(subject_key, chapter_key)] = chapter.id

        topic_ids = {}

        for topic in db.query(Topic):
            topic_ids[(topic.chapter_id, normalize_name(topic.name))] = (
                topic.id
            )

        for (chapter_key, topic_key), info in new_topics.items():
            chapter_id = chapter_ids[(subject_key, chapter_key)]
            topic = Topic(chapter_id=chapter_id, name=info["name"])
            db.add(topic)
            db.flush()
            topic_ids[(chapter_id, topic_key)] = topic.id

        for item in questions:
            chapter_id = chapter_ids[
                (subject_key, normalize_name(item["chapter"]))
            ]
            db.add(
                Question(
                    test_id=test.id,
                    question_number=item["question_number"],
                    subject=meta["subject"],
                    chapter_id=chapter_id,
                    topic_id=topic_ids[
                        (chapter_id, normalize_name(item["topic"]))
                    ],
                    correct_answer=item["correct_answer"],
                    difficulty="medium",
                )
            )

        db.commit()
        test_id = test.id
    except Exception as exc:
        db.rollback()
        _commit_failed(report, TEST_SETUP_FILE, exc)
        return _finish(report, dry_run, committed=False)

    report.summary["test_id"] = test_id

    return _finish(report, dry_run, committed=True)


# -------------------------------------------------------------------
# Student answers
# -------------------------------------------------------------------

def validate_answer_rows(
    rows: list[tuple[int, dict]],
    students: dict[str, Student],
    questions: dict[int, int],
    report: ImportReport,
) -> list[tuple[int, int, str | None]]:
    """
    Validate answer rows against the batch roster and the test's
    questions. Returns (student_id, question_id, answer) records.

    Students that appear in the file but have no row for some question
    get an explicit blank record for it (with a warning), so every
    evaluated student has one answer per question.
    """

    seen: dict[tuple[str, int], int] = {}
    records: list[tuple[int, int, str | None]] = []
    answered: dict[str, set[int]] = {}

    for line, row in rows:
        roll = clean_text(row["roll_number"])
        raw_number = row["question_number"]

        if not roll:
            report.error(
                ANSWERS_FILE, "Roll number is blank.",
                row=line, field="roll_number",
            )
            continue

        student = students.get(normalize_name(roll))
        number = _parse_question_number(raw_number)
        ok = True

        if student is None:
            report.error(
                ANSWERS_FILE,
                "Student roll number is not in this batch.",
                row=line, field="roll_number", value=roll,
            )
            ok = False

        if number is None:
            report.error(
                ANSWERS_FILE,
                "Question number must be a positive whole number.",
                row=line, field="question_number", value=raw_number,
            )
            ok = False
        elif number not in questions:
            report.error(
                ANSWERS_FILE,
                "Question number is not in this test.",
                row=line, field="question_number", value=raw_number,
            )
            ok = False

        raw_answer = row["answer"]
        answer = raw_answer.strip().upper()

        if answer and answer not in ANSWER_OPTIONS:
            report.error(
                ANSWERS_FILE,
                f"Answer must be {', '.join(ANSWER_OPTIONS)}, or blank.",
                row=line, field="answer", value=raw_answer,
            )
            ok = False

        if not ok:
            continue

        key = (normalize_name(roll), number)

        if key in seen:
            report.error(
                ANSWERS_FILE,
                f"Duplicate answer for this student and question "
                f"(first seen on row {seen[key]}).",
                row=line, field="roll_number", value=roll,
            )
            continue

        seen[key] = line
        answered.setdefault(key[0], set()).add(number)
        records.append((student.id, questions[number], answer or None))

    all_numbers = set(questions)

    for roll_key, numbers in answered.items():
        missing = sorted(all_numbers - numbers)

        if not missing:
            continue

        student = students[roll_key]

        report.warning(
            ANSWERS_FILE,
            f"No row for {len(missing)} question(s) "
            f"(e.g. Q{missing[0]}); recorded as blank.",
            field="roll_number", value=student.roll_number,
        )

        for number in missing:
            records.append((student.id, questions[number], None))

    absent = [
        s for key, s in students.items() if key not in answered
    ]

    if absent:
        report.warning(
            ANSWERS_FILE,
            f"{len(absent)} student(s) in the batch have no answers and "
            "will not be evaluated.",
        )

    return records


def import_answers(
    db: Session,
    test_id: int,
    raw: bytes,
    replace: bool = False,
    dry_run: bool = True,
) -> dict:
    report = ImportReport()
    test = db.get(Test, test_id)

    if test is None:
        report.error(
            ANSWERS_FILE, "Test not found.",
            field="test_id", value=test_id,
        )

    rows = parse_csv(raw, ANSWERS_FILE, ANSWER_COLUMNS, report)

    records: list[tuple[int, int, str | None]] = []
    existing_rows = 0

    if test is not None:
        students = {
            normalize_name(s.roll_number): s
            for s in db.query(Student).filter(
                Student.batch_id == test.batch_id
            )
        }
        questions = {
            q.question_number: q.id
            for q in db.query(Question).filter(Question.test_id == test_id)
        }

        if not questions:
            report.error(
                ANSWERS_FILE,
                "This test has no questions. Import the test setup first.",
                field="test_id", value=test_id,
            )

        existing_rows = (
            db.query(StudentAnswer)
            .filter(StudentAnswer.test_id == test_id)
            .count()
        )

        if existing_rows and not replace:
            report.error(
                ANSWERS_FILE,
                "Answers already exist for this test. "
                "Use replace to overwrite them.",
                field="test_id", value=test_id,
            )
        elif existing_rows:
            report.warning(
                ANSWERS_FILE,
                f"{existing_rows} existing answer rows and the test "
                "results will be replaced.",
            )

        records = validate_answer_rows(rows, students, questions, report)

        if rows and not records and not report.has_errors:
            report.error(ANSWERS_FILE, "File has no usable answer rows.")

        if not rows and not report.has_errors:
            report.error(ANSWERS_FILE, "File has no answer rows.")

    report.summary = {
        "rows": len(rows),
        "students": len({r[0] for r in records}),
        "answer_records": len(records),
        "replacing_existing": bool(existing_rows and replace),
    }

    if report.has_errors or dry_run:
        return _finish(report, dry_run, committed=False)

    try:
        if replace:
            db.query(StudentAnswer).filter(
                StudentAnswer.test_id == test_id
            ).delete(synchronize_session=False)
            db.query(TestResult).filter(
                TestResult.test_id == test_id
            ).delete(synchronize_session=False)
            db.flush()

        db.add_all(
            StudentAnswer(
                test_id=test_id,
                student_id=student_id,
                question_id=question_id,
                answer=answer,
            )
            for student_id, question_id, answer in records
        )
        db.flush()

        results = evaluate_test(db, test_id, commit=False)

        db.commit()
    except Exception as exc:
        db.rollback()
        _commit_failed(report, ANSWERS_FILE, exc)
        return _finish(report, dry_run, committed=False)

    report.summary["students_evaluated"] = len(results)

    return _finish(report, dry_run, committed=True)
