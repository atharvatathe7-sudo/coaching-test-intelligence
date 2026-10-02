"""
Admin corrections and the audit log (Milestone 4D).

Each scenario builds its own small test through the real import API:
12 students, 4 questions keyed A, B, C, D. Student i answers every
question with the option at index (i % 4), so for every question exactly
3 of 12 students (25%) match the key.
"""

import itertools
import json

import pytest

from backend.app.database import models
from backend.app.services import importer

_counter = itertools.count(1)

DbTest = models.Test
DbResult = models.TestResult

OPTIONS = "ABCD"
KEY = {1: "A", 2: "B", 3: "C", 4: "D"}
HEADER = "question_number,correct_answer,chapter,topic\n"


def upload(client, path, text, data):
    response = client.post(
        f"/api/imports/{path}",
        data={k: str(v) for k, v in data.items()},
        files={"file": ("f.csv", text.encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def setup_rows(key=KEY, chapter="Mechanics", topic="Kinematics"):
    return HEADER + "".join(
        f"{n},{answer},{chapter},{topic}\n" for n, answer in key.items()
    )


@pytest.fixture()
def scenario(client):
    n = next(_counter)
    batch_id = client.post("/api/batches", json={"name": f"Correction Batch {n}"}).json()["id"]

    roster = "roll_number,name\n" + "".join(
        f"CR{n}-{i},Correction Student {n}-{i}\n" for i in range(12)
    )
    assert upload(client, "roster", roster, {"batch_id": batch_id, "dry_run": False})["status"] == "imported"

    setup = upload(client, "test-setup", setup_rows(), {
        "batch_id": batch_id, "test_name": f"Correction Test {n}", "subject": "Physics",
        "test_date": "2026-07-01", "dry_run": False, "confirm_new_chapters_topics": True,
    })
    assert setup["status"] == "imported", setup
    test_id = setup["summary"]["test_id"]

    answers = "roll_number,question_number,answer\n" + "".join(
        f"CR{n}-{i},{q},{OPTIONS[i % 4]}\n" for i in range(12) for q in KEY
    )
    assert upload(client, "answers", answers, {"test_id": test_id, "dry_run": False})["status"] == "imported"

    return {"n": n, "batch_id": batch_id, "test_id": test_id, "answers": answers}


def question_pct(client, test_id, number):
    items = client.get(f"/api/tests/{test_id}/analytics/questions").json()["questions"]
    return next(q for q in items if q["question_number"] == number)["correct_percentage"]


def audit_entries(client, action=None, entity_id=None):
    entries = client.get("/api/audit?limit=500").json()["entries"]
    return [
        e for e in entries
        if (action is None or e["action"] == action)
        and (entity_id is None or e["entity_id"] == entity_id)
    ]


def results(db, test_id):
    db.expire_all()
    return {r.student_id: r for r in db.query(DbResult).filter_by(test_id=test_id)}


# ------------------------------------------------------------------
# Answer-key correction
# ------------------------------------------------------------------

def test_wrong_key_dry_run_then_correction(client, scenario, db):
    test_id = scenario["test_id"]

    # A teacher acted on Q2 while the key was wrong.
    action = client.post("/api/actions", json={
        "test_id": test_id, "question_number": 2, "action_type": "reteach",
        "finding_reason": "Only 25.0% of students answered this question correctly.",
    }).json()

    before_results = {sid: r.marks for sid, r in results(db, test_id).items()}
    assert question_pct(client, test_id, 2) == 25.0

    corrected = {**KEY, 2: "C", 4: "A"}
    data = {"test_id": test_id}

    dry = upload(client, "answer-key", setup_rows(corrected), data)
    assert dry["status"] == "valid"
    assert dry["summary"]["key_changes"] == [
        {"question_number": 2, "from": "B", "to": "C"},
        {"question_number": 4, "from": "D", "to": "A"},
    ]
    assert dry["summary"]["mapping_changes"] == []
    assert dry["summary"]["will_reevaluate"] is True
    # Dry run changes nothing.
    assert question_pct(client, test_id, 2) == 25.0
    assert audit_entries(client, "answer_key.correct", test_id) == []

    done = upload(client, "answer-key", setup_rows(corrected), {**data, "dry_run": False})
    assert done["status"] == "imported", done["errors"]
    assert done["summary"]["students_reevaluated"] == 12

    # Keys updated in place; question ids unchanged.
    db.expire_all()
    questions = {q.question_number: q for q in db.query(models.Question).filter_by(test_id=test_id)}
    assert {n: q.correct_answer for n, q in questions.items()} == corrected

    # Results regenerated. Before: every student had exactly 1 right
    # (4 - 3 = 1 mark). Key now A, C, C, A: students answering "A" or "C"
    # get 2 right / 2 wrong (6 marks); "B" or "D" get none right (-4).
    assert sorted(before_results.values()) == [1.0] * 12
    after = {sid: r.marks for sid, r in results(db, test_id).items()}
    assert set(after) == set(before_results)
    assert sorted(after.values()) == [-4.0] * 6 + [6.0] * 6
    assert question_pct(client, test_id, 2) == 25.0  # 3 of 12 chose C
    assert question_pct(client, test_id, 4) == 25.0  # 3 of 12 chose A

    # The teacher action is untouched, still on question 2.
    kept = client.get(f"/api/tests/{test_id}/actions").json()["actions"]
    assert [(a["id"], a["question_number"], a["finding_reason"]) for a in kept] == [
        (action["id"], 2, "Only 25.0% of students answered this question correctly.")
    ]

    # Audited with the exact diff.
    entry = audit_entries(client, "answer_key.correct", test_id)[0]
    assert entry["detail"]["key_changes"] == dry["summary"]["key_changes"]
    assert entry["detail"]["students_reevaluated"] == 12

    # Its outcome now flags that the snapshot predates the correction.
    outcome = client.get(f"/api/tests/{test_id}/actions/outcomes").json()["outcomes"][0]
    assert "test_reevaluated_after_action" in outcome["caveats"]


def test_correction_changes_marks(client, scenario, db):
    test_id = scenario["test_id"]
    # Student 0 answered "A" everywhere: 1 correct (Q1) -> 4 - 3 = 1 mark.
    student0 = next(iter(sorted(results(db, test_id))))
    assert results(db, test_id)[student0].marks == 1.0

    all_a = {n: "A" for n in KEY}
    upload(client, "answer-key", setup_rows(all_a), {"test_id": test_id, "dry_run": False})

    assert results(db, test_id)[student0].marks == 16.0


def test_key_correction_requires_complete_valid_coverage(client, scenario):
    test_id = scenario["test_id"]
    data = {"test_id": test_id, "dry_run": False}

    missing = upload(client, "answer-key", HEADER + "1,A,Mechanics,Kinematics\n", data)
    assert missing["status"] == "invalid"
    assert "missing 3: Q2, Q3, Q4" in missing["errors"][0]["message"]

    extra = upload(client, "answer-key", setup_rows({**KEY, 9: "A"}), data)
    assert extra["status"] == "invalid"
    assert extra["errors"][0]["field"] == "question_number"
    assert extra["errors"][0]["value"] == 9

    bad = upload(client, "answer-key", setup_rows({**KEY, 3: "E"}), data)
    assert bad["status"] == "invalid"
    assert bad["errors"][0]["field"] == "correct_answer"
    assert bad["errors"][0]["file"] == "answer_key.csv"

    dup = upload(client, "answer-key", setup_rows() + "1,B,Mechanics,Kinematics\n", data)
    assert dup["status"] == "invalid"

    unchanged = upload(client, "answer-key", setup_rows(), data)
    assert unchanged["status"] == "valid"
    assert "nothing to change" in unchanged["warnings"][0]["message"]
    assert audit_entries(client, "answer_key.correct", test_id) == []


def test_mapping_correction_with_new_topic_needs_confirmation(client, scenario, db):
    test_id = scenario["test_id"]
    rows = setup_rows(topic="Kinematics").replace(
        "4,D,Mechanics,Kinematics", f"4,D,Mechanics,Projectiles {scenario['n']}"
    )
    data = {"test_id": test_id, "dry_run": False}

    refused = upload(client, "answer-key", rows, data)
    assert refused["status"] == "invalid"
    assert refused["errors"][0]["field"] == "confirm_new_chapters_topics"

    done = upload(client, "answer-key", rows, {**data, "confirm_new_chapters_topics": True})
    assert done["status"] == "imported"
    assert done["summary"]["mapping_changes"][0]["topic_to"] == f"Projectiles {scenario['n']}"

    db.expire_all()
    q4 = db.query(models.Question).filter_by(test_id=test_id, question_number=4).one()
    assert db.get(models.Topic, q4.topic_id).name == f"Projectiles {scenario['n']}"


def test_failed_correction_rolls_back_everything(client, scenario, db, monkeypatch):
    test_id = scenario["test_id"]
    before = results(db, test_id)
    before_marks = {sid: r.marks for sid, r in before.items()}

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure during re-evaluation")

    monkeypatch.setattr(importer, "evaluate_test", boom)

    report = upload(client, "answer-key", setup_rows({n: "A" for n in KEY}),
                    {"test_id": test_id, "dry_run": False})

    assert report["status"] == "invalid"
    assert "Nothing was imported" in report["errors"][0]["message"]

    db.expire_all()
    keys = {q.question_number: q.correct_answer
            for q in db.query(models.Question).filter_by(test_id=test_id)}
    assert keys == KEY
    assert {sid: r.marks for sid, r in results(db, test_id).items()} == before_marks
    assert audit_entries(client, "answer_key.correct", test_id) == []


# ------------------------------------------------------------------
# Answer replacement
# ------------------------------------------------------------------

def test_answer_import_and_replace_are_audited(client, scenario, db):
    test_id = scenario["test_id"]
    first = audit_entries(client, "answers.import", test_id)
    assert first and first[0]["detail"]["answer_records"] == 48

    action = client.post("/api/actions", json={
        "test_id": test_id, "question_number": 1, "action_type": "review",
    }).json()

    everyone_right = "roll_number,question_number,answer\n" + "".join(
        f"CR{scenario['n']}-{i},{q},{KEY[q]}\n" for i in range(12) for q in KEY
    )
    report = upload(client, "answers", everyone_right,
                    {"test_id": test_id, "replace": True, "dry_run": False})
    assert report["status"] == "imported"

    assert question_pct(client, test_id, 1) == 100.0
    assert all(r.marks == 16.0 for r in results(db, test_id).values())

    entry = audit_entries(client, "answers.replace", test_id)[0]
    assert entry["detail"]["replaced_answer_records"] == 48
    assert entry["detail"]["students_evaluated"] == 12

    kept = client.get(f"/api/tests/{test_id}/actions").json()["actions"]
    assert [a["id"] for a in kept] == [action["id"]]
    outcome = client.get(f"/api/tests/{test_id}/actions/outcomes").json()["outcomes"][0]
    assert "test_reevaluated_after_action" in outcome["caveats"]


# ------------------------------------------------------------------
# Test metadata
# ------------------------------------------------------------------

def test_marks_change_reevaluates(client, scenario, db):
    test_id = scenario["test_id"]
    student0 = sorted(results(db, test_id))[0]
    assert results(db, test_id)[student0].marks == 1.0   # 1 right, 3 wrong

    response = client.patch(f"/api/tests/{test_id}", json={"marks_wrong": 0})
    assert response.status_code == 200
    assert response.json()["reevaluated"] is True
    assert response.json()["test"]["marks_wrong"] == 0

    assert results(db, test_id)[student0].marks == 4.0

    entry = audit_entries(client, "test.update", test_id)[0]
    assert entry["detail"]["changes"] == {"marks_wrong": ["-1.0", "0.0"]}
    assert entry["detail"]["reevaluated"] is True


def test_name_date_subject_change_is_audited(client, scenario, db):
    test_id = scenario["test_id"]
    response = client.patch(f"/api/tests/{test_id}", json={
        "name": "Renamed Test", "test_date": "2026-07-08", "subject": "physics",
        "batch_id": 999,
    })
    body = response.json()
    assert response.status_code == 200
    assert body["changed"] == ["name", "subject", "test_date"]
    assert body["reevaluated"] is False
    assert body["test"]["batch_id"] == scenario["batch_id"]   # immutable

    db.expire_all()
    subjects = {q.subject for q in db.query(models.Question).filter_by(test_id=test_id)}
    assert subjects == {"physics"}

    changes = audit_entries(client, "test.update", test_id)[0]["detail"]["changes"]
    assert changes["test_date"] == ["2026-07-01", "2026-07-08"]


def test_metadata_validation(client, scenario):
    test_id = scenario["test_id"]
    other = upload(client, "test-setup", setup_rows(), {
        "batch_id": scenario["batch_id"], "test_name": "Other", "subject": "Physics",
        "test_date": "2026-08-01", "dry_run": False, "confirm_new_chapters_topics": True,
    })["summary"]["test_id"]

    clash = client.patch(f"/api/tests/{other}", json={
        "name": f"correction test {scenario['n']}", "test_date": "2026-07-01",
    })
    assert clash.status_code == 409

    assert client.patch(f"/api/tests/{test_id}", json={"marks_correct": 0}).status_code == 422
    assert client.patch(f"/api/tests/{test_id}", json={"name": ""}).status_code == 422
    assert client.patch("/api/tests/999999", json={"name": "x"}).status_code == 404

    unchanged = client.patch(f"/api/tests/{test_id}", json={"marks_correct": 4})
    assert unchanged.json()["changed"] == []


# ------------------------------------------------------------------
# Roster corrections
# ------------------------------------------------------------------

def _students(client, batch_id):
    return client.get(f"/api/students?batch_id={batch_id}").json()["students"]


def test_roster_correction(client, scenario):
    students = _students(client, scenario["batch_id"])
    first, second = students[0], students[1]

    renamed = client.patch(f"/api/students/{first['id']}", json={
        "name": "Corrected Name", "roll_number": f"NEW-{scenario['n']}",
    })
    assert renamed.status_code == 200
    assert renamed.json()["changed"] == ["name", "roll_number"]

    clash = client.patch(f"/api/students/{second['id']}", json={
        "roll_number": f"new-{scenario['n']}",
    })
    assert clash.status_code == 409

    detail = audit_entries(client, "student.update", first["id"])[0]["detail"]
    assert detail == {"batch_id": scenario["batch_id"], "fields_changed": ["name", "roll_number"]}


def test_student_delete_rules(client, scenario):
    with_answers = _students(client, scenario["batch_id"])[0]
    response = client.delete(f"/api/students/{with_answers['id']}")
    assert response.status_code == 409

    upload(client, "roster", "roll_number,name\nSPARE-1,Spare Student\n",
           {"batch_id": scenario["batch_id"], "dry_run": False})
    spare = next(s for s in _students(client, scenario["batch_id"]) if s["roll_number"] == "SPARE-1")

    assert client.delete(f"/api/students/{spare['id']}").status_code == 200
    assert spare["id"] not in [s["id"] for s in _students(client, scenario["batch_id"])]
    assert audit_entries(client, "student.delete", spare["id"])


# ------------------------------------------------------------------
# Test deletion
# ------------------------------------------------------------------

def test_delete_test_without_actions(client, scenario, db):
    test_id = scenario["test_id"]

    response = client.delete(f"/api/tests/{test_id}")
    assert response.status_code == 200
    assert response.json()["answer_records"] == 48

    db.expire_all()
    assert db.get(DbTest, test_id) is None
    for model in (models.Question, models.StudentAnswer, DbResult):
        assert db.query(model).filter_by(test_id=test_id).count() == 0

    assert client.get(f"/api/tests/{test_id}").status_code == 404
    entry = audit_entries(client, "test.delete", test_id)[0]
    assert entry["detail"]["questions"] == 4


def test_delete_test_with_actions_needs_confirmation(client, scenario, db):
    test_id = scenario["test_id"]
    client.post("/api/actions", json={"test_id": test_id, "action_type": "review"})

    refused = client.delete(f"/api/tests/{test_id}")
    assert refused.status_code == 409
    assert refused.json()["detail"]["teacher_actions"] == 1

    db.expire_all()
    assert db.get(DbTest, test_id) is not None
    assert db.query(models.TeacherAction).filter_by(test_id=test_id).count() == 1

    confirmed = client.delete(f"/api/tests/{test_id}?confirm_delete_actions=true")
    assert confirmed.status_code == 200
    assert confirmed.json()["teacher_actions_deleted"] == 1

    db.expire_all()
    assert db.query(models.TeacherAction).filter_by(test_id=test_id).count() == 0


# ------------------------------------------------------------------
# Access and privacy
# ------------------------------------------------------------------

def test_teacher_cannot_correct(teacher_client, scenario):
    test_id = scenario["test_id"]
    student = _students(teacher_client, scenario["batch_id"])[0]

    for method, path, body in (
        ("PATCH", f"/api/tests/{test_id}", {"name": "x"}),
        ("DELETE", f"/api/tests/{test_id}", None),
        ("PATCH", f"/api/students/{student['id']}", {"name": "x"}),
        ("DELETE", f"/api/students/{student['id']}", None),
        ("GET", "/api/audit", None),
    ):
        assert teacher_client.request(method, path, json=body).status_code == 403, path

    response = teacher_client.post(
        "/api/imports/answer-key", data={"test_id": str(test_id)},
        files={"file": ("f.csv", setup_rows().encode(), "text/csv")},
    )
    assert response.status_code == 403


def test_audit_log_contains_no_student_personal_data(client, scenario):
    # Exercise roster and answer changes first.
    student = _students(client, scenario["batch_id"])[0]
    client.patch(f"/api/students/{student['id']}", json={"name": "Private Person"})
    upload(client, "answers", scenario["answers"],
           {"test_id": scenario["test_id"], "replace": True, "dry_run": False})

    text = json.dumps(client.get("/api/audit?limit=500").json()).lower()

    assert "private person" not in text
    assert "correction student" not in text
    assert f"cr{scenario['n']}-" not in text
    # No password material (hashes or any password used in the suite).
    assert "$argon2" not in text
    for secret in ("demo-password", "correct horse battery", "reset-password-99"):
        assert secret not in text
