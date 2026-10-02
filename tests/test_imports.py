import itertools

import pytest

from backend.app.database import models
from backend.app.database.models import (
    Chapter,
    Question,
    Student,
    StudentAnswer,
    Topic,
)
from backend.app.services import importer

# Aliased so pytest does not try to collect the model classes as tests.
DbTest = models.Test
DbResult = models.TestResult

_counter = itertools.count(1)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def make_batch(client):
    name = f"Import Batch {next(_counter)}"
    response = client.post(
        "/api/batches", json={"institute_id": 1, "name": name}
    )
    assert response.status_code == 200
    return response.json()["id"]


def as_csv(header, rows):
    lines = [header] + rows
    return "\n".join(lines) + "\n"


def upload(client, path, text, data=None, name="file.csv"):
    response = client.post(
        f"/api/imports/{path}",
        data={k: str(v) for k, v in (data or {}).items()},
        files={"file": (name, text.encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def roster_csv(rows=("R1,Asha", "R2,Bala", "R3,Chitra")):
    return as_csv("roll_number,name", list(rows))


SETUP_ROWS = [
    "1,A,Imported Chapter,Imported Topic 1",
    "2,B,Imported Chapter,Imported Topic 2",
    "3,C,Imported Chapter 2,Imported Topic 3",
    "4,D,Imported Chapter 2,Imported Topic 3",
]


def setup_csv(rows=None):
    return as_csv(
        "question_number,correct_answer,chapter,topic",
        list(rows if rows is not None else SETUP_ROWS),
    )


def setup_data(batch_id, name="Chem Test 1", **extra):
    data = {
        "batch_id": batch_id,
        "test_name": name,
        "subject": "Chemistry",
        "test_date": "2026-03-01",
        "marks_correct": 4,
        "marks_wrong": -1,
        "marks_blank": 0,
    }
    data.update(extra)
    return data


ANSWER_ROWS = [
    # R1: all correct -> 16
    "R1,1,A", "R1,2,B", "R1,3,C", "R1,4,D",
    # R2: correct, wrong, blank, correct -> 7
    "R2,1,A", "R2,2,A", "R2,3,", "R2,4,d",
    # R3: all wrong -> -4
    "R3,1,B", "R3,2,C", "R3,3,D", "R3,4,A",
]


def answers_csv(rows=None):
    return as_csv(
        "roll_number,question_number,answer",
        list(rows if rows is not None else ANSWER_ROWS),
    )


def errors_of(report):
    return [(e["field"], e["message"]) for e in report["errors"]]


def count(db, model, **filters):
    db.expire_all()
    return db.query(model).filter_by(**filters).count()


@pytest.fixture()
def imported(client):
    """A batch with roster + test setup imported (no answers yet)."""
    batch_id = make_batch(client)
    roster = upload(
        client, "roster", roster_csv(),
        {"batch_id": batch_id, "dry_run": False},
    )
    assert roster["status"] == "imported"

    setup = upload(
        client, "test-setup", setup_csv(),
        {**setup_data(batch_id), "dry_run": False,
         "confirm_new_chapters_topics": True},
    )
    assert setup["status"] == "imported", setup["errors"]

    return batch_id, setup["summary"]["test_id"]


# ------------------------------------------------------------------
# Roster
# ------------------------------------------------------------------

def test_roster_valid_import(client, db):
    batch_id = make_batch(client)

    dry = upload(client, "roster", roster_csv(), {"batch_id": batch_id})
    assert dry["status"] == "valid"
    assert dry["summary"]["students_to_create"] == 3
    assert count(db, Student, batch_id=batch_id) == 0

    done = upload(
        client, "roster", roster_csv(),
        {"batch_id": batch_id, "dry_run": False},
    )
    assert done["status"] == "imported"
    assert done["summary"]["students_created"] == 3
    assert count(db, Student, batch_id=batch_id) == 3


def test_roster_duplicate_roll_number(client, db):
    batch_id = make_batch(client)
    report = upload(
        client, "roster",
        roster_csv(["R1,Asha", "R2,Bala", "r1 ,Asha Again"]),
        {"batch_id": batch_id, "dry_run": False},
    )

    assert report["status"] == "invalid"
    assert report["errors"][0]["row"] == 4
    assert "Duplicate roll number" in report["errors"][0]["message"]
    assert count(db, Student, batch_id=batch_id) == 0


def test_roster_missing_column_and_blank_values(client):
    batch_id = make_batch(client)

    report = upload(
        client, "roster", "roll_number\nR1\n", {"batch_id": batch_id}
    )
    assert report["status"] == "invalid"
    assert errors_of(report) == [("name", "Required column 'name' is missing.")]

    report = upload(
        client, "roster", roster_csv([",Asha", "R2,"]), {"batch_id": batch_id}
    )
    assert [e["field"] for e in report["errors"]] == ["roll_number", "name"]


def test_roster_invalid_batch_and_malformed_rows(client):
    report = upload(client, "roster", roster_csv(), {"batch_id": 99999})
    assert report["status"] == "invalid"
    assert report["errors"][0]["field"] == "batch_id"

    batch_id = make_batch(client)
    report = upload(
        client, "roster", roster_csv(["R1,Asha,extra"]), {"batch_id": batch_id}
    )
    assert report["status"] == "invalid"
    assert "columns" in report["errors"][0]["message"]


def test_roster_existing_students(client, db):
    batch_id = make_batch(client)
    data = {"batch_id": batch_id, "dry_run": False}
    upload(client, "roster", roster_csv(), data)

    # Same roll + same name: skipped with a warning, new student added.
    again = upload(
        client, "roster",
        roster_csv(["R1,Asha", "R4,Devi"]), data,
    )
    assert again["status"] == "imported"
    assert again["summary"]["students_created"] == 1
    assert again["warning_count"] == 1
    assert count(db, Student, batch_id=batch_id) == 4

    # Same roll, different name: conflict, nothing overwritten.
    conflict = upload(
        client, "roster", roster_csv(["R1,Someone Else", "R9,New"]), data
    )
    assert conflict["status"] == "invalid"
    assert "not overwritten" in conflict["errors"][0]["message"]
    assert count(db, Student, batch_id=batch_id) == 4
    assert db.query(Student).filter_by(
        batch_id=batch_id, roll_number="R1"
    ).one().name == "Asha"


# ------------------------------------------------------------------
# Test setup
# ------------------------------------------------------------------

def test_setup_valid_import_with_confirmation(client, db):
    batch_id = make_batch(client)

    dry = upload(client, "test-setup", setup_csv(), setup_data(batch_id))
    assert dry["status"] == "valid"
    assert dry["summary"]["new_chapters"] == 2
    assert dry["summary"]["new_topics"] == 3
    assert dry["summary"]["requires_confirmation"] is True
    messages = [w["message"] for w in dry["warnings"]]
    assert "New chapter 'Imported Chapter' will be created." in messages
    assert "New topic 'Imported Topic 3' will be created." in messages

    chapters_before = db.query(Chapter).count()

    # Without confirmation the commit is refused and writes nothing.
    refused = upload(
        client, "test-setup", setup_csv(),
        setup_data(batch_id, dry_run=False),
    )
    assert refused["status"] == "invalid"
    assert refused["errors"][0]["field"] == "confirm_new_chapters_topics"
    assert count(db, DbTest, batch_id=batch_id) == 0
    assert db.query(Chapter).count() == chapters_before

    done = upload(
        client, "test-setup", setup_csv(),
        setup_data(
            batch_id, dry_run=False, confirm_new_chapters_topics=True
        ),
    )
    assert done["status"] == "imported"
    test_id = done["summary"]["test_id"]

    test = db.get(DbTest, test_id)
    assert (test.name, test.subject, test.marks_wrong) == (
        "Chem Test 1", "Chemistry", -1.0
    )
    assert count(db, Question, test_id=test_id) == 4
    assert db.query(Chapter).count() == chapters_before + 2


def test_setup_matches_existing_chapters_by_normalized_name(client, db):
    batch_id = make_batch(client)
    chapters_before = db.query(Chapter).count()
    topics_before = db.query(Topic).count()

    report = upload(
        client, "test-setup",
        setup_csv(["1,a,  mechanics ,KINEMATICS", "2,B,Mechanics,Kinematics"]),
        setup_data(
            batch_id, name="Physics Test 9", subject=" physics ",
            dry_run=False,
        ),
    )

    assert report["status"] == "imported", report["errors"]
    assert report["warning_count"] == 0
    assert db.query(Chapter).count() == chapters_before
    assert db.query(Topic).count() == topics_before


def test_setup_row_errors(client):
    batch_id = make_batch(client)
    rows = [
        "1,A,Ch,Tp",
        "1,B,Ch,Tp",       # duplicate question
        "2,E,Ch,Tp",       # invalid key
        "3,A,,Tp",         # missing chapter
        "4,A,Ch,",         # missing topic
        "x,A,Ch,Tp",       # bad number
    ]
    report = upload(client, "test-setup", setup_csv(rows), setup_data(batch_id))

    assert report["status"] == "invalid"
    assert [(e["row"], e["field"]) for e in report["errors"]] == [
        (3, "question_number"),
        (4, "correct_answer"),
        (5, "chapter"),
        (6, "topic"),
        (7, "question_number"),
    ]


def test_setup_metadata_and_file_errors(client):
    batch_id = make_batch(client)

    bad = upload(
        client, "test-setup", setup_csv(),
        setup_data(
            batch_id, name="", test_date="01/03/2026",
            marks_correct="abc", marks_wrong="x",
        ),
    )
    assert {e["field"] for e in bad["errors"]} == {
        "test_name", "test_date", "marks_correct", "marks_wrong",
    }

    assert upload(
        client, "test-setup", setup_csv(), setup_data(99999)
    )["errors"][0]["field"] == "batch_id"

    empty = upload(client, "test-setup", setup_csv([]), setup_data(batch_id))
    assert "no question rows" in empty["errors"][0]["message"]

    missing = upload(
        client, "test-setup", "question_number,correct_answer\n1,A\n",
        setup_data(batch_id),
    )
    assert {e["field"] for e in missing["errors"]} == {"chapter", "topic"}


def test_setup_malformed_csv(client):
    batch_id = make_batch(client)

    response = client.post(
        "/api/imports/test-setup",
        data={k: str(v) for k, v in setup_data(batch_id).items()},
        files={"file": ("bad.csv", b"\xff\xfe\x00bad", "text/csv")},
    )
    report = response.json()
    assert report["status"] == "invalid"
    assert "UTF-8" in report["errors"][0]["message"]

    empty = upload(client, "test-setup", "", setup_data(batch_id))
    assert "empty" in empty["errors"][0]["message"]


def test_setup_duplicate_test_identity(client, imported, db):
    batch_id, test_id = imported
    tests_before = count(db, DbTest, batch_id=batch_id)

    report = upload(
        client, "test-setup", setup_csv(),
        setup_data(
            batch_id, name=" chem  TEST 1 ", dry_run=False,
            confirm_new_chapters_topics=True,
        ),
    )

    assert report["status"] == "invalid"
    assert "already exists" in report["errors"][0]["message"]
    assert count(db, DbTest, batch_id=batch_id) == tests_before

    # Same name on another date is a different test.
    other = upload(
        client, "test-setup", setup_csv(),
        setup_data(
            batch_id, test_date="2026-03-08", dry_run=False,
            confirm_new_chapters_topics=True,
        ),
    )
    assert other["status"] == "imported"


def test_setup_commit_failure_leaves_nothing_behind(
    client, db, monkeypatch
):
    batch_id = make_batch(client)
    tests_before = db.query(DbTest).count()
    chapters_before = db.query(Chapter).count()
    topics_before = db.query(Topic).count()
    questions_before = db.query(Question).count()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(importer, "Question", boom)

    report = upload(
        client, "test-setup", setup_csv(),
        setup_data(
            batch_id, name="Doomed", dry_run=False,
            confirm_new_chapters_topics=True,
        ),
    )

    assert report["status"] == "invalid"
    assert "Nothing was imported" in report["errors"][0]["message"]
    assert "Traceback" not in str(report)

    db.expire_all()
    assert db.query(DbTest).count() == tests_before
    assert db.query(Chapter).count() == chapters_before
    assert db.query(Topic).count() == topics_before
    assert db.query(Question).count() == questions_before


# ------------------------------------------------------------------
# Answers
# ------------------------------------------------------------------

def test_answers_valid_import_evaluates_automatically(client, imported, db):
    _, test_id = imported

    dry = upload(client, "answers", answers_csv(), {"test_id": test_id})
    assert dry["status"] == "valid"
    assert count(db, StudentAnswer, test_id=test_id) == 0

    done = upload(
        client, "answers", answers_csv(),
        {"test_id": test_id, "dry_run": False},
    )
    assert done["status"] == "imported", done["errors"]
    assert done["summary"]["students_evaluated"] == 3

    # Blank answer was stored as unanswered.
    assert count(db, StudentAnswer, test_id=test_id) == 12
    assert count(db, DbResult, test_id=test_id) == 3
    blanks = db.query(StudentAnswer).filter_by(
        test_id=test_id, answer=None
    ).count()
    assert blanks == 1


def test_answers_end_to_end_analytics(client, imported):
    _, test_id = imported
    upload(
        client, "answers", answers_csv(),
        {"test_id": test_id, "dry_run": False},
    )

    overview = client.get(
        f"/api/tests/{test_id}/analytics/batch"
    ).json()["overview"]

    # Marks: 16, 7, -4. Accuracy: 100, 66.67, 0.
    assert overview["average_marks"] == pytest.approx(6.33, abs=0.01)
    assert overview["average_accuracy"] == pytest.approx(55.56, abs=0.01)
    assert overview["total_correct"] == 6
    assert overview["total_wrong"] == 5
    assert overview["total_blank"] == 1

    questions = client.get(
        f"/api/tests/{test_id}/analytics/questions"
    ).json()
    items = questions["questions"] if isinstance(questions, dict) else questions
    q1 = next(q for q in items if q["question_number"] == 1)
    assert q1["correct_percentage"] == pytest.approx(66.67, abs=0.01)

    chapters = client.get(
        f"/api/tests/{test_id}/analytics/chapters-topics"
    ).json()["chapters"]
    assert {c["chapter_name"] for c in chapters} == {
        "Imported Chapter", "Imported Chapter 2",
    }

    # Existing evaluate endpoint still works on imported data.
    again = client.post(f"/api/tests/{test_id}/evaluate")
    assert again.status_code == 200
    assert again.json()["students_evaluated"] == 3

    # Dashboard pieces work on imported tests like on seeded ones.
    assert client.get(f"/api/tests/{test_id}/action-report").status_code == 200
    assert client.get(
        f"/api/tests/{test_id}/questions/1/investigation"
    ).status_code == 200


def test_answers_row_errors(client, imported, db):
    _, test_id = imported
    rows = [
        "R1,1,A",
        "R1,1,B",      # duplicate
        "R9,1,A",      # unknown student
        "R2,99,A",     # unknown question
        "R2,2,X",      # invalid answer
        "R3,two,A",    # bad question number
    ]
    report = upload(
        client, "answers", answers_csv(rows),
        {"test_id": test_id, "dry_run": False},
    )

    assert report["status"] == "invalid"
    assert [(e["row"], e["field"]) for e in report["errors"]] == [
        (3, "roll_number"),
        (4, "roll_number"),
        (5, "question_number"),
        (6, "answer"),
        (7, "question_number"),
    ]
    assert report["errors"][1]["value"] == "R9"
    assert count(db, StudentAnswer, test_id=test_id) == 0
    assert count(db, DbResult, test_id=test_id) == 0


def test_answers_missing_column_and_unknown_test(client, imported):
    _, test_id = imported

    report = upload(
        client, "answers", "roll_number,answer\nR1,A\n", {"test_id": test_id}
    )
    assert errors_of(report) == [
        ("question_number", "Required column 'question_number' is missing.")
    ]

    report = upload(client, "answers", answers_csv(), {"test_id": 99999})
    assert report["errors"][0]["field"] == "test_id"


def test_answers_student_from_other_batch_rejected(client, imported):
    _, test_id = imported
    other_batch = make_batch(client)
    upload(
        client, "roster", roster_csv(["OTHER,Stranger"]),
        {"batch_id": other_batch, "dry_run": False},
    )

    report = upload(
        client, "answers", answers_csv(["OTHER,1,A"]), {"test_id": test_id}
    )

    assert report["status"] == "invalid"
    assert "not in this batch" in report["errors"][0]["message"]


def test_answers_missing_rows_become_blank_with_warning(client, imported, db):
    _, test_id = imported
    report = upload(
        client, "answers",
        answers_csv(["R1,1,A", "R1,2,B", "R2,1,A", "R2,2,B", "R2,3,C", "R2,4,D"]),
        {"test_id": test_id, "dry_run": False},
    )

    assert report["status"] == "imported"
    warnings = [w["message"] for w in report["warnings"]]
    assert any("R1" == w["value"] for w in report["warnings"] if w["field"])
    assert any("not be evaluated" in m for m in warnings)  # R3 absent

    # Every evaluated student has one answer per question.
    assert count(db, StudentAnswer, test_id=test_id) == 8
    for result in db.query(DbResult).filter_by(test_id=test_id):
        assert (
            result.correct_count + result.wrong_count + result.blank_count
            == 4
        )


def test_answers_reimport_rejected_then_replace(client, imported, db):
    _, test_id = imported
    first = {"test_id": test_id, "dry_run": False}
    upload(client, "answers", answers_csv(), first)

    action = client.post(
        "/api/actions",
        json={
            "test_id": test_id, "question_number": 1,
            "action_type": "review", "note": "keep me",
        },
    ).json()

    rejected = upload(client, "answers", answers_csv(), first)
    assert rejected["status"] == "invalid"
    assert "already exist" in rejected["errors"][0]["message"]
    assert count(db, StudentAnswer, test_id=test_id) == 12

    # Everyone answers everything correctly this time.
    all_correct = answers_csv(
        [f"{r},{n},{k}" for r in ("R1", "R2", "R3")
         for n, k in ((1, "A"), (2, "B"), (3, "C"), (4, "D"))]
    )
    replaced = upload(
        client, "answers", all_correct,
        {**first, "replace": True},
    )
    assert replaced["status"] == "imported", replaced["errors"]
    assert any("replaced" in w["message"] for w in replaced["warnings"])

    overview = client.get(
        f"/api/tests/{test_id}/analytics/batch"
    ).json()["overview"]
    assert overview["average_marks"] == 16.0
    assert count(db, StudentAnswer, test_id=test_id) == 12
    assert count(db, DbResult, test_id=test_id) == 3
    assert count(db, Question, test_id=test_id) == 4

    # Teacher actions survive the replacement.
    actions = client.get(f"/api/tests/{test_id}/actions").json()["actions"]
    assert [a["id"] for a in actions] == [action["id"]]
    assert actions[0]["note"] == "keep me"


def test_failed_replace_keeps_old_answers(client, imported, db, monkeypatch):
    _, test_id = imported
    first = {"test_id": test_id, "dry_run": False}
    upload(client, "answers", answers_csv(), first)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated evaluation failure")

    monkeypatch.setattr(importer, "evaluate_test", boom)

    report = upload(
        client, "answers", answers_csv(),
        {**first, "replace": True},
    )

    assert report["status"] == "invalid"
    assert "Nothing was imported" in report["errors"][0]["message"]

    db.expire_all()
    assert count(db, StudentAnswer, test_id=test_id) == 12
    assert count(db, DbResult, test_id=test_id) == 3


def test_large_import_with_late_error_writes_nothing(client, db):
    batch_id = make_batch(client)
    roll_numbers = [f"S{i:03d}" for i in range(1, 201)]

    upload(
        client, "roster",
        roster_csv([f"{r},Student {r}" for r in roll_numbers]),
        {"batch_id": batch_id, "dry_run": False},
    )
    setup = upload(
        client, "test-setup",
        setup_csv([f"{n},A,Big Chapter,Big Topic" for n in range(1, 21)]),
        setup_data(batch_id, name="Big Test", dry_run=False,
                   confirm_new_chapters_topics=True),
    )
    test_id = setup["summary"]["test_id"]

    rows = [f"{r},{n},A" for r in roll_numbers for n in range(1, 21)]
    rows[-1] = "S200,20,Z"   # invalid value on the very last row

    report = upload(
        client, "answers", answers_csv(rows),
        {"test_id": test_id, "dry_run": False},
    )

    assert report["status"] == "invalid"
    assert report["errors"][0]["row"] == len(rows) + 1
    assert count(db, StudentAnswer, test_id=test_id) == 0
    assert count(db, DbResult, test_id=test_id) == 0

    # Fixing the row imports all 4,000 answers.
    rows[-1] = "S200,20,A"
    report = upload(
        client, "answers", answers_csv(rows),
        {"test_id": test_id, "dry_run": False},
    )
    assert report["status"] == "imported"
    assert count(db, StudentAnswer, test_id=test_id) == 4000


# ------------------------------------------------------------------
# Constraints
# ------------------------------------------------------------------

def test_duplicate_batch_and_test_are_rejected_by_api(client):
    batch_id = make_batch(client)
    name = client.get("/api/batches").json()["batches"][-1]["name"]

    response = client.post(
        "/api/batches", json={"institute_id": 1, "name": name}
    )
    assert response.status_code == 400

    body = {
        "batch_id": batch_id, "name": "Dup", "subject": "Physics",
        "test_date": "2026-01-01",
    }
    assert client.post("/api/tests", json=body).status_code == 200
    assert client.post("/api/tests", json=body).status_code == 400
