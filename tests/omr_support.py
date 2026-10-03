"""
Shared fixtures and ground truth for the OMR tests.

The expected numbers below are worked out by hand, never by calling the
production calculations being tested.

Test "OMR Test" (10 questions, marking +4 / -1 / 0), answer key:

    Q1 A  Q2 B  Q3 C  Q4 D  Q5 A  Q6 B  Q7 C  Q8 D  Q9 A  Q10 B

Students and what they marked ("-" = left blank):

  101001  A B C D A B C D A B           10 correct                -> 40
  101002  A C C - A B D D - B           correct Q1 Q3 Q5 Q6 Q8 Q10 (6)
                                        wrong   Q2 Q7 (2)
                                        blank   Q4 Q9 (2)        -> 24 - 2 = 22
  101003  - - - - - - - - - -           10 blank                  -> 0
  101004  B B A D B A C A A A           correct Q2 Q4 Q7 Q9 (4)
                                        wrong   Q1 Q3 Q5 Q6 Q8 Q10 (6)
                                                                 -> 16 - 6 = 10
  101005  A B C D A B C D A B           10 correct                -> 40
"""

import io
from pathlib import Path

from openpyxl import load_workbook

from backend.app.database import models
from backend.app.database.connection import SessionLocal

import manage
from conftest import make_client
from omr_sheets import render_sheet

PASSWORD = "omr-test-password"
KEY = "ABCDABCDAB"

STUDENTS = {
    "101001": "ABCDABCDAB",
    "101002": "ACC-ABDD-B",
    "101003": "----------",
    "101004": "BBADBACAAA",
    "101005": "ABCDABCDAB",
}
EXPECTED = {            # roll: (marks, correct, wrong, blank)
    "101001": (40, 10, 0, 0),
    "101002": (22, 6, 2, 2),
    "101003": (0, 0, 0, 10),
    "101004": (10, 4, 6, 0),
    "101005": (40, 10, 0, 0),
}
# Roll 101004's name is formula-like on purpose (for the Excel checks).
NAMES = {"101001": "Asha", "101002": "Ben", "101003": "Chitra",
         "101004": "=EVIL()+1", "101005": "Zoë 日本語"}

_counter = {"n": 0}
_contexts: dict[str, dict] = {}


def upload_csv(client, path, text, data):
    response = client.post(
        f"/api/imports/{path}",
        data={k: str(v) for k, v in data.items()},
        files={"file": ("f.csv", text.encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def get_ctx(tag="a"):
    """
    An institute with an admin, a teacher and a roster of the five
    students above. Built once per test session for each tag.
    """
    if tag in _contexts:
        return _contexts[tag]

    db = SessionLocal()
    try:
        institute = models.Institute(name=f"OMR Institute {tag.upper()}")
        db.add(institute)
        db.flush()
        manage.make_user(db, institute.id, "OMR Admin", f"admin@omr-{tag}.test", "admin", PASSWORD)
        manage.make_user(db, institute.id, "OMR Teacher", f"teacher@omr-{tag}.test", "teacher", PASSWORD)
        db.commit()
        institute_id = institute.id
    finally:
        db.close()

    admin = make_client(f"admin@omr-{tag}.test", PASSWORD)
    teacher = make_client(f"teacher@omr-{tag}.test", PASSWORD)
    batch = admin.post("/api/batches", json={"name": "OMR Batch"}).json()

    roster = "roll_number,name\n" + "".join(f'{r},"{n}"\n' for r, n in NAMES.items())
    assert upload_csv(admin, "roster", roster, dict(batch_id=batch["id"], dry_run=False))["status"] == "imported"

    _contexts[tag] = {
        "admin": admin, "teacher": teacher, "batch_id": batch["id"],
        "institute_id": institute_id,
    }
    return _contexts[tag]


def make_test(ctx, name=None, questions=10, key=KEY):
    """A new test in the OMR batch with its answer key; returns its id."""
    _counter["n"] += 1
    key_csv = "question_number,correct_answer,chapter,topic\n" + "".join(
        f"{q},{key[(q - 1) % len(key)]},{'Mechanics' if q <= 5 else 'Optics'},"
        f"{'Kinematics' if q <= 5 else 'Lenses'}\n"
        for q in range(1, questions + 1)
    )
    result = upload_csv(
        ctx["admin"], "test-setup", key_csv,
        dict(batch_id=ctx["batch_id"], test_name=name or f"OMR Test {_counter['n']}",
             subject="Physics", test_date="2026-10-02", dry_run=False,
             confirm_new_chapters_topics=True),
    )
    assert result["status"] == "imported", result
    return result["summary"]["test_id"]


def to_answers(letters):
    return {q: ("" if ch == "-" else ch) for q, ch in enumerate(letters, start=1)}


def sheets_for(rolls=None, overrides=None, names=None):
    """[(filename, png bytes)] for the given students (default: all five)."""
    files = []
    for i, roll in enumerate(rolls or STUDENTS, start=1):
        value = (overrides or {}).get(roll, STUDENTS[roll])
        answers = to_answers(value) if isinstance(value, str) else value
        name = (names or {}).get(roll, f"scan_{roll}.png")
        files.append((name, render_sheet(roll, answers, seed=i)))
    return files


def post_batch(client, test_id, files, **form):
    return client.post(
        f"/api/tests/{test_id}/omr/import",
        files=[("files", (name, data, "image/png")) for name, data in files],
        data={k: str(v) for k, v in form.items()},
    )


def create_batch(ctx, test_id, files=None, **form):
    """Upload and return (batch summary dict). Fails the test if refused."""
    response = post_batch(ctx["admin"], test_id, files if files is not None else sheets_for(), **form)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["batch"] is not None, body
    return body["batch"]


def review(client, batch_id):
    response = client.get(f"/api/omr/batches/{batch_id}/review")
    assert response.status_code == 200, response.text
    return response.json()


def resolve(client, item, choice):
    return client.post(
        f"/api/omr/review/{item['id']}",
        json={"final_answer": choice, "revision": item["revision"]},
    )


def resolve_all(client, batch_id, choice="A"):
    """Settle every open item in a batch with the same choice."""
    for item in review(client, batch_id)["items"]:
        if item["kind"] == "answer" and not item["resolved"]:
            assert resolve(client, item, choice).status_code == 200


def answer_count(test_id):
    db = SessionLocal()
    try:
        return db.query(models.StudentAnswer).filter_by(test_id=test_id).count()
    finally:
        db.close()


def result_count(test_id):
    db = SessionLocal()
    try:
        return db.query(models.TestResult).filter_by(test_id=test_id).count()
    finally:
        db.close()


def student_results(client, test_id):
    rows = client.get(f"/api/tests/{test_id}/analytics/students").json()["students"]
    return {r["roll_number"]: (r["marks"], r["correct"], r["wrong"], r["blank"]) for r in rows}


def audit_rows(action=None, entity_id=None, entity_type=None):
    db = SessionLocal()
    try:
        query = db.query(models.AuditLog)
        if action:
            query = query.filter(models.AuditLog.action == action)
        if entity_id is not None:
            query = query.filter(models.AuditLog.entity_id == entity_id)
        if entity_type:
            query = query.filter(models.AuditLog.entity_type == entity_type)
        return [(r.action, r.entity_type, r.entity_id, r.user_id, r.detail) for r in query.order_by(models.AuditLog.id)]
    finally:
        db.close()


def omr_rows(batch_id):
    """(sheets, answers) stored for a batch."""
    db = SessionLocal()
    try:
        sheets = db.query(models.OMRSheet).filter_by(batch_id=batch_id).all()
        ids = [s.id for s in sheets]
        answers = db.query(models.OMRAnswer).filter(models.OMRAnswer.sheet_id.in_(ids)).all() if ids else []
        return sheets, answers
    finally:
        db.close()


def workbook(client, test_id):
    response = client.get(f"/api/tests/{test_id}/export.xlsx")
    assert response.status_code == 200
    return load_workbook(io.BytesIO(response.content))


def image_dir(batch_id):
    from backend.app.omr import storage
    return storage.batch_dir(batch_id)
