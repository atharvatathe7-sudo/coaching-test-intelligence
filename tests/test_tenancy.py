"""
Tenant isolation (Milestone 4C).

Institute B is created the way a real second institute would be: by the
operator bootstrap (scripts/manage.py), then B's admin imports a roster,
a test setup and answers through the API, and B's teacher records an
action. Every check then confirms institute A (the demo institute)
cannot read, change or reference any of it, and gets the same response
as for an object that does not exist.
"""

import io
from contextlib import redirect_stdout

import pytest
from alembic import command
from sqlalchemy import text

from backend.app.database import models
from backend.app.database.connection import SessionLocal, make_engine

import manage
from conftest import alembic_config, make_client

B_PASSWORD = "institute-b-password"


def _upload(test_client, path, csv_text, data):
    response = test_client.post(
        f"/api/imports/{path}",
        data={k: str(v) for k, v in data.items()},
        files={"file": ("f.csv", csv_text.encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def institute_b(demo_database):
    """Institute B with its own admin, teacher, batch, test and action."""
    db = SessionLocal()
    try:
        institute = models.Institute(name="Institute B")
        db.add(institute)
        db.flush()
        manage.make_user(db, institute.id, "B Admin", "admin@b.test", "admin", B_PASSWORD)
        manage.make_user(db, institute.id, "B Teacher", "teacher@b.test", "teacher", B_PASSWORD)
        db.commit()
        institute_id = institute.id
    finally:
        db.close()

    admin_b = make_client("admin@b.test", B_PASSWORD)
    teacher_b = make_client("teacher@b.test", B_PASSWORD)

    batch = admin_b.post("/api/batches", json={"name": "B Batch"}).json()

    roster = "roll_number,name\n" + "".join(f"B{i},B Student {i}\n" for i in range(12))
    assert _upload(admin_b, "roster", roster,
                   {"batch_id": batch["id"], "dry_run": False})["status"] == "imported"

    setup = _upload(
        admin_b, "test-setup",
        "question_number,correct_answer,chapter,topic\n"
        "1,A,B Secret Chapter,B Secret Topic\n2,B,Mechanics,Kinematics\n",
        {"batch_id": batch["id"], "test_name": "B Test", "subject": "Physics",
         "test_date": "2026-05-01", "dry_run": False,
         "confirm_new_chapters_topics": True},
    )
    assert setup["status"] == "imported", setup
    # B's own "Mechanics" is created for B, not borrowed from A.
    assert setup["summary"]["new_chapters"] == 2

    answers = "roll_number,question_number,answer\n" + "".join(
        f"B{i},{q},A\n" for i in range(12) for q in (1, 2)
    )
    test_id = setup["summary"]["test_id"]
    assert _upload(admin_b, "answers", answers,
                   {"test_id": test_id, "dry_run": False})["status"] == "imported"

    db = SessionLocal()
    try:
        b_chapter = db.query(models.Chapter).filter_by(
            institute_id=institute_id, name="B Secret Chapter"
        ).one()
        b_topic = db.query(models.Topic).filter_by(chapter_id=b_chapter.id).one()
        b_student = db.query(models.Student).filter_by(batch_id=batch["id"]).first()
        chapter_id, topic_id, student_id = b_chapter.id, b_topic.id, b_student.id
    finally:
        db.close()

    action = teacher_b.post(
        "/api/actions",
        json={"test_id": test_id, "question_number": 1, "action_type": "reteach",
              "chapter_id": chapter_id, "topic_id": topic_id},
    ).json()

    return {
        "institute_id": institute_id,
        "admin": admin_b,
        "teacher": teacher_b,
        "batch_id": batch["id"],
        "test_id": test_id,
        "chapter_id": chapter_id,
        "topic_id": topic_id,
        "student_id": student_id,
        "action_id": action["id"],
    }


def _b_action(b):
    """
    B's action. conftest's clean_actions removes actions after each test,
    so it is recreated by B's teacher when needed.
    """
    db = SessionLocal()
    try:
        if db.get(models.TeacherAction, b["action_id"]) is not None:
            return b["action_id"]
    finally:
        db.close()

    response = b["teacher"].post(
        "/api/actions",
        json={"test_id": b["test_id"], "question_number": 1, "action_type": "reteach"},
    )
    b["action_id"] = response.json()["id"]
    return b["action_id"]


@pytest.fixture(params=["admin", "teacher"])
def a_client(request, client, teacher_client):
    """Institute A, as admin and as teacher."""
    return client if request.param == "admin" else teacher_client


# ------------------------------------------------------------------
# Sanity: B really works, so A's 404s are isolation, not breakage
# ------------------------------------------------------------------

def test_institute_b_can_use_its_own_data(institute_b):
    b = institute_b
    for path in (
        f"/api/tests/{b['test_id']}", f"/api/tests/{b['test_id']}/analytics/batch",
        f"/api/tests/{b['test_id']}/questions/1/investigation",
        f"/api/tests/{b['test_id']}/actions", f"/api/tests/{b['test_id']}/actions/outcomes",
    ):
        assert b["teacher"].get(path).status_code == 200, path

    tests = b["teacher"].get("/api/tests").json()["tests"]
    assert [t["id"] for t in tests] == [b["test_id"]]


# ------------------------------------------------------------------
# Reads
# ------------------------------------------------------------------

def test_a_lists_never_include_b(a_client, institute_b):
    b = institute_b

    batches = a_client.get("/api/batches").json()["batches"]
    assert b["batch_id"] not in [x["id"] for x in batches]
    assert {x["institute_id"] for x in batches} == {1}

    students = a_client.get("/api/students").json()["students"]
    assert b["student_id"] not in [s["id"] for s in students]
    assert all(not s["roll_number"].startswith("B") for s in students)

    tests = a_client.get("/api/tests").json()["tests"]
    assert b["test_id"] not in [t["id"] for t in tests]


def test_a_cannot_list_b_students_by_batch(a_client, institute_b):
    response = a_client.get(f"/api/students?batch_id={institute_b['batch_id']}")
    assert response.status_code == 404


@pytest.mark.parametrize("suffix", [
    "", "/questions", "/analytics/questions", "/analytics/chapters-topics",
    "/analytics/students", "/analytics/batch", "/action-report",
    "/questions/1/investigation", "/actions", "/actions/outcomes",
])
def test_a_cannot_read_b_test_data(a_client, institute_b, suffix):
    b_response = a_client.get(f"/api/tests/{institute_b['test_id']}{suffix}")
    missing = a_client.get(f"/api/tests/999999{suffix}")

    assert b_response.status_code == 404
    # Indistinguishable from a test that does not exist.
    assert b_response.json() == missing.json()


def test_a_cannot_compare_against_b(a_client, institute_b):
    b_test = institute_b["test_id"]
    assert a_client.get(f"/api/tests/1/compare/{b_test}").status_code == 404
    assert a_client.get(f"/api/tests/{b_test}/compare/1").status_code == 404


# ------------------------------------------------------------------
# Writes
# ------------------------------------------------------------------

def test_a_cannot_modify_b_actions(a_client, institute_b, db):
    action_id = _b_action(institute_b)

    response = a_client.patch(
        f"/api/actions/{action_id}", json={"status": "completed", "note": "hijack"}
    )
    assert response.status_code == 404

    db.expire_all()
    action = db.get(models.TeacherAction, action_id)
    assert action.status == "planned"
    assert action.note is None


def test_a_cannot_create_actions_on_b_test(a_client, institute_b):
    response = a_client.post(
        "/api/actions", json={"test_id": institute_b["test_id"], "action_type": "review"}
    )
    assert response.status_code == 404


def test_a_cannot_use_b_chapters_or_topics(a_client, institute_b):
    b = institute_b
    for body in (
        {"chapter_id": b["chapter_id"]},
        {"topic_id": b["topic_id"]},
        {"chapter_id": b["chapter_id"], "topic_id": b["topic_id"]},
    ):
        response = a_client.post(
            "/api/actions", json={"test_id": 1, "action_type": "review", **body}
        )
        assert response.status_code == 404, body


def test_a_admin_cannot_import_into_b(client, institute_b, db):
    b = institute_b

    def counts():
        db.expire_all()
        return (
            db.query(models.Student).filter_by(batch_id=b["batch_id"]).count(),
            db.query(models.Test).filter_by(batch_id=b["batch_id"]).count(),
            db.query(models.StudentAnswer).filter_by(test_id=b["test_id"]).count(),
        )

    before = counts()

    roster = _upload(client, "roster", "roll_number,name\nX1,Intruder\n",
                     {"batch_id": b["batch_id"], "dry_run": False})
    setup = _upload(client, "test-setup",
                    "question_number,correct_answer,chapter,topic\n1,A,C,T\n",
                    {"batch_id": b["batch_id"], "test_name": "Intrusion",
                     "subject": "Physics", "test_date": "2026-06-01",
                     "dry_run": False, "confirm_new_chapters_topics": True})
    answers = _upload(client, "answers", "roll_number,question_number,answer\nB1,1,D\n",
                      {"test_id": b["test_id"], "replace": True, "dry_run": False})

    for report, field in ((roster, "batch_id"), (setup, "batch_id"), (answers, "test_id")):
        assert report["status"] == "invalid"
        assert report["errors"][0]["field"] == field
        assert "not found" in report["errors"][0]["message"]

    assert counts() == before


def test_a_admin_cannot_evaluate_b(client, institute_b):
    assert client.post(f"/api/tests/{institute_b['test_id']}/evaluate").status_code == 404


def test_a_admin_cannot_manage_b_users(client, institute_b, db):
    b_admin = db.query(models.User).filter_by(email="admin@b.test").one()

    emails = [u["email"] for u in client.get("/api/users").json()["users"]]
    assert "admin@b.test" not in emails and "teacher@b.test" not in emails

    assert client.patch(f"/api/users/{b_admin.id}", json={"is_active": False}).status_code == 404
    assert client.post(
        f"/api/users/{b_admin.id}/password", json={"new_password": "x" * 12}
    ).status_code == 404

    db.expire_all()
    assert db.get(models.User, b_admin.id).is_active


def test_new_users_join_the_admins_institute(client, db):
    created = client.post(
        "/api/users",
        json={"name": "N", "email": "joined@a.test", "password": "x" * 12,
              "institute_id": 999},
    ).json()
    db.expire_all()
    assert db.get(models.User, created["id"]).institute_id == 1


def test_batch_institute_comes_from_user(client):
    created = client.post(
        "/api/batches", json={"name": "Forged", "institute_id": 999}
    ).json()
    assert created["institute_id"] == 1


# ------------------------------------------------------------------
# Syllabus ownership
# ------------------------------------------------------------------

def test_imports_never_reuse_another_institutes_chapters(client, institute_b, db):
    batch_id = client.post("/api/batches", json={"name": "Syllabus Probe"}).json()["id"]
    report = _upload(
        client, "test-setup",
        "question_number,correct_answer,chapter,topic\n1,A,B Secret Chapter,B Secret Topic\n",
        {"batch_id": batch_id, "test_name": "Probe", "subject": "Physics",
         "test_date": "2026-06-02"},
    )

    # A sees B's chapter name as new: B's chapter is invisible to A.
    assert report["summary"]["new_chapters"] == 1
    assert report["summary"]["new_topics"] == 1


def test_outcomes_ignore_targets_from_another_institute(client, institute_b, db):
    """Defence in depth: even a forged row cannot measure B's topic."""
    from backend.app.services.action_outcomes import resolve_target

    action = models.TeacherAction(
        test_id=1, chapter_id=institute_b["chapter_id"], action_type="review",
        status="planned",
    )
    assert resolve_target(db, action, institute_id=1) is None
    assert resolve_target(db, action, institute_id=institute_b["institute_id"]) is not None


# ------------------------------------------------------------------
# Teacher action ownership inside one institute
# ------------------------------------------------------------------

def test_teachers_edit_only_their_own_actions(client, teacher_client):
    admin_action = client.post(
        "/api/actions", json={"test_id": 1, "action_type": "review"}
    ).json()
    own = teacher_client.post(
        "/api/actions", json={"test_id": 1, "action_type": "review"}
    ).json()

    me = teacher_client.get("/api/auth/me").json()["user"]
    assert own["created_by_user_id"] == me["id"]

    assert teacher_client.patch(
        f"/api/actions/{admin_action['id']}", json={"status": "completed"}
    ).status_code == 403
    assert teacher_client.patch(
        f"/api/actions/{own['id']}", json={"status": "completed"}
    ).status_code == 200

    # Admins can edit any action in their institute.
    assert client.patch(
        f"/api/actions/{own['id']}", json={"note": "checked"}
    ).status_code == 200


# ------------------------------------------------------------------
# Migration safety
# ------------------------------------------------------------------

def test_syllabus_migration_refuses_shared_chapters(tmp_path):
    """0003 must not guess an owner for a chapter used by two institutes."""
    engine = make_engine(f"sqlite:///{tmp_path / 'shared.db'}")
    config = alembic_config()

    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0002")

        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        for sql in (
            "INSERT INTO institutes (id, name, created_at) VALUES (1,'A','2026-01-01'),(2,'B','2026-01-01')",
            "INSERT INTO batches (id, institute_id, name, created_at) VALUES (1,1,'a','2026-01-01'),(2,2,'b','2026-01-01')",
            "INSERT INTO chapters (id, subject, name) VALUES (1,'Physics','Shared')",
            "INSERT INTO topics (id, chapter_id, name) VALUES (1,1,'T')",
            "INSERT INTO tests (id, batch_id, name, subject, test_date, marks_correct, marks_wrong, marks_blank, created_at)"
            " VALUES (1,1,'t1','Physics','2026-01-01',4,-1,0,'2026-01-01'),(2,2,'t2','Physics','2026-01-01',4,-1,0,'2026-01-01')",
            "INSERT INTO questions (test_id, question_number, subject, chapter_id, topic_id, correct_answer, difficulty)"
            " VALUES (1,1,'Physics',1,1,'A','medium'),(2,1,'Physics',1,1,'A','medium')",
        ):
            connection.execute(text(sql))
        connection.commit()

        with pytest.raises(RuntimeError, match="more than one institute"), redirect_stdout(io.StringIO()):
            command.upgrade(config, "head")

    engine.dispose()


def test_audit_log_is_institute_scoped(client, institute_b):
    a_entries = client.get("/api/audit?limit=500").json()["entries"]
    b_entries = institute_b["admin"].get("/api/audit?limit=500").json()["entries"]

    b_ids = {e["id"] for e in b_entries}
    assert b_ids, "institute B's imports should have been audited"
    assert b_ids.isdisjoint({e["id"] for e in a_entries})
    assert {e["user"]["name"] for e in b_entries} <= {"B Admin", "B Teacher"}
