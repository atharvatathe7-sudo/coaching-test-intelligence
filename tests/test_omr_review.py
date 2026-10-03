"""
OMR review, commit and discard (Stage 3).

A batch of sheets is stored while it awaits review. Nothing becomes a
StudentAnswer / TestResult until the batch is committed, atomically.

Expected values come from omr_support (worked out by hand) or are
calculated here from the plain answer strings, never by calling the
production calculations under test.
"""

import json
import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app import config
from backend.app.database import models
from backend.app.database.connection import SessionLocal
from backend.app.omr import batches, storage
from backend.app.omr import service as omr_service
from backend.app.omr.checker import RecognitionRun
from backend.app.services import audit, importer

from conftest import make_client
from omr_sheets import render_sheet
from omr_support import (
    EXPECTED,
    KEY,
    NAMES,
    STUDENTS,
    answer_count,
    audit_rows,
    create_batch,
    get_ctx,
    image_dir,
    make_test,
    omr_rows,
    post_batch,
    result_count,
    resolve,
    resolve_all,
    review,
    sheets_for,
    student_results,
    to_answers,
    upload_csv,
    workbook,
)


@pytest.fixture(scope="module")
def ctx(demo_database):
    return get_ctx("b")


MULTI = {"101005": {1: "AB", **{q: c for q, c in enumerate("BCDABCDAB", start=2)}}}


def clean_batch(ctx, test_id=None):
    test_id = test_id or make_test(ctx)
    return test_id, create_batch(ctx, test_id)


def multi_batch(ctx, test_id=None):
    test_id = test_id or make_test(ctx)
    return test_id, create_batch(ctx, test_id, sheets_for(overrides=MULTI))


def commit(ctx, batch_id, **body):
    return ctx["admin"].post(f"/api/omr/batches/{batch_id}/commit", json=body)


def fake_recognition(monkeypatch, rows, errored=()):
    """Inject what the recogniser 'read', keeping the rest of the pipeline real."""
    monkeypatch.setattr(
        omr_service, "run_recognition",
        lambda workspace: RecognitionRun(rows=rows, errored=set(errored)),
    )


def row(roll, **answers):
    """A recogniser row for the 10-question test (metadata columns included)."""
    base = {"file_id": "sheet_0001.png", "input_path": "/secret/in", "output_path": "/secret/out",
            "score": "99", "Roll": roll}
    base.update({f"q{q}": "A" for q in range(1, 11)})
    base.update(answers)
    return base


# =====================================================================
# Batch creation
# =====================================================================

def test_clean_batch_becomes_ready_to_commit(ctx):
    test_id, batch = clean_batch(ctx)
    assert batch["status"] == "READY_TO_COMMIT"
    assert batch["review_required_count"] == 0 and batch["accepted_sheets"] == 5
    assert batch["recognition"] == {"recognized": 38, "blank": 12, "multi_mark": 0,
                                    "invalid": 0, "review_required": 0}
    assert answer_count(test_id) == 0 and result_count(test_id) == 0


def test_multi_mark_batch_requires_review_and_blank_stays_distinct(ctx):
    test_id, batch = multi_batch(ctx)
    assert batch["status"] == "REVIEW_REQUIRED"
    assert batch["review_required_count"] == 1 and batch["accepted_sheets"] == 4
    assert batch["recognition"]["multi_mark"] == 1 and batch["recognition"]["blank"] == 12
    assert answer_count(test_id) == 0 and result_count(test_id) == 0


def test_multi_mark_is_stored_as_multi_mark_never_as_blank(ctx):
    _, batch = multi_batch(ctx)
    _, answers = omr_rows(batch["id"])
    ambiguous = [a for a in answers if a.recognition_status == "multi_mark"]

    assert len(ambiguous) == 1
    only = ambiguous[0]
    assert (only.raw_value, only.recognized_answer, only.final_answer) == ("AB", None, None)
    assert only.resolved is False and only.review_reason == "MULTI_MARK"
    # the 12 genuine blanks are different rows: settled, blank, no review
    blanks = [a for a in answers if a.recognition_status == "blank"]
    assert len(blanks) == 12 and all(a.resolved and a.review_reason is None for a in blanks)


def test_invalid_answer_requires_review(ctx, monkeypatch):
    test_id = make_test(ctx)
    fake_recognition(monkeypatch, {1: row("101001", q1="Z")})
    batch = create_batch(ctx, test_id, sheets_for(["101001"]))

    assert batch["status"] == "REVIEW_REQUIRED"
    item = next(i for i in review(ctx["admin"], batch["id"])["items"] if i["kind"] == "answer")
    assert (item["reason"], item["question_number"]) == ("INVALID_ANSWER", 1)
    assert item["detected"]["raw_value"] == "Z" and item["detected"]["recognition_status"] == "invalid"
    assert item["final_answer"] is None and item["resolved"] is False


def test_missing_answer_field_requires_review(ctx, monkeypatch):
    test_id = make_test(ctx)
    short = row("101001")
    del short["q4"]
    fake_recognition(monkeypatch, {1: short})
    batch = create_batch(ctx, test_id, sheets_for(["101001"]))

    item = next(i for i in review(ctx["admin"], batch["id"])["items"] if i["kind"] == "answer")
    assert (item["reason"], item["question_number"]) == ("MISSING_ANSWER_FIELD", 4)
    assert item["detected"]["raw_value"] is None


@pytest.mark.parametrize(
    "roll,reason",
    [("999999", "UNKNOWN_ROLL"), ("", "MISSING_ROLL"), ("12345", "MALFORMED_ROLL")],
)
def test_roll_problems_block_the_commit_safely(ctx, monkeypatch, roll, reason):
    test_id = make_test(ctx)
    fake_recognition(monkeypatch, {1: row(roll)})
    batch = create_batch(ctx, test_id, sheets_for(["101001"]))

    assert batch["status"] == "REVIEW_REQUIRED"
    sheet_item = next(i for i in review(ctx["admin"], batch["id"])["items"] if i["kind"] == "sheet")
    assert sheet_item["reason"] == reason and sheet_item["resolvable"] is True

    refused = commit(ctx, batch["id"])
    assert refused.status_code == 409
    assert answer_count(test_id) == 0 and result_count(test_id) == 0


def test_unreadable_sheet_blocks_the_commit_and_cannot_be_assigned(ctx, monkeypatch):
    test_id = make_test(ctx)
    fake_recognition(monkeypatch, {1: row("101001")}, errored=[2])
    batch = create_batch(ctx, test_id, sheets_for(["101001", "101002"]))

    assert batch["status"] == "REVIEW_REQUIRED" and batch["error_count"] == 1
    item = next(i for i in review(ctx["admin"], batch["id"])["items"] if i["reason"] == "UNREADABLE_SHEET")
    assert item["resolvable"] is False

    response = ctx["admin"].post(f"/api/omr/sheets/{item['sheet_id']}/roll",
                                 json={"roll_number": "101002", "revision": item["revision"]})
    assert response.status_code == 422
    assert commit(ctx, batch["id"]).status_code == 409


def test_duplicate_students_are_flagged_on_both_sheets_and_can_be_fixed(ctx):
    test_id = make_test(ctx)
    files = sheets_for(["101001", "101002"]) + [("again.png", render_sheet("101001", to_answers("BBBBBBBBBB"), seed=9))]
    batch = create_batch(ctx, test_id, files)

    items = [i for i in review(ctx["admin"], batch["id"])["items"] if i["kind"] == "sheet"]
    assert [i["reason"] for i in items] == ["DUPLICATE_ROLL", "DUPLICATE_ROLL"]
    assert commit(ctx, batch["id"]).status_code == 409

    # the reviewer says the second one is really student 101003
    second = next(i for i in items if i["filename"] == "again.png")
    fixed = ctx["admin"].post(f"/api/omr/sheets/{second['sheet_id']}/roll",
                              json={"roll_number": "101003", "revision": second["revision"]})
    assert fixed.status_code == 200 and fixed.json()["batch"]["status"] == "READY_TO_COMMIT"


def test_a_roll_must_be_in_the_roster_to_be_assigned(ctx, monkeypatch):
    test_id = make_test(ctx)
    fake_recognition(monkeypatch, {1: row("999999")})
    batch = create_batch(ctx, test_id, sheets_for(["101001"]))
    item = next(i for i in review(ctx["admin"], batch["id"])["items"] if i["kind"] == "sheet")

    nope = ctx["admin"].post(f"/api/omr/sheets/{item['sheet_id']}/roll",
                             json={"roll_number": "888888", "revision": item["revision"]})
    assert nope.status_code == 422 and "roster" in nope.json()["detail"]
    # a near-miss is not "corrected" for the reviewer either
    assert ctx["admin"].post(f"/api/omr/sheets/{item['sheet_id']}/roll",
                             json={"roll_number": "10100", "revision": item["revision"]}).status_code == 422


def test_duplicate_question_rows_cannot_exist():
    _, batch_id = None, None
    db = SessionLocal()
    try:
        institute = db.query(models.Institute).first()
        user = db.query(models.User).first()
        test = db.query(models.Test).first()
        batch = models.OMRBatch(institute_id=institute.id, test_id=test.id, created_by_user_id=user.id,
                                status="REVIEW_REQUIRED", template_id="x", template_version=1)
        db.add(batch); db.flush()
        sheet = models.OMRSheet(batch_id=batch.id, sheet_index=1, original_filename="a.png", status="PENDING")
        db.add(sheet); db.flush()
        for _ in range(2):
            db.add(models.OMRAnswer(sheet_id=sheet.id, question_number=1, recognition_status="blank", resolved=True))
        with pytest.raises(IntegrityError):
            db.flush()
    finally:
        db.rollback()
        db.close()


def test_the_database_itself_keeps_unresolved_answers_without_a_final_answer():
    db = SessionLocal()
    try:
        institute = db.query(models.Institute).first()
        user = db.query(models.User).first()
        test = db.query(models.Test).first()
        batch = models.OMRBatch(institute_id=institute.id, test_id=test.id, created_by_user_id=user.id,
                                status="REVIEW_REQUIRED", template_id="x", template_version=1)
        db.add(batch); db.flush()
        sheet = models.OMRSheet(batch_id=batch.id, sheet_index=1, original_filename="a.png", status="PENDING")
        db.add(sheet); db.flush()
        db.add(models.OMRAnswer(sheet_id=sheet.id, question_number=1, recognition_status="multi_mark",
                                resolved=False, final_answer="A"))
        with pytest.raises(IntegrityError):
            db.flush()
    finally:
        db.rollback()
        db.close()


# =====================================================================
# Review
# =====================================================================

def test_review_items_show_what_was_detected_and_the_choices(ctx):
    _, batch = multi_batch(ctx)
    body = review(ctx["admin"], batch["id"])

    assert body["open_count"] == 1 and len(body["items"]) == 1
    item = body["items"][0]
    assert (item["kind"], item["reason"], item["roll_number"], item["question_number"]) == \
        ("answer", "MULTI_MARK", "101005", 1)
    assert item["detected"] == {"raw_value": "AB", "recognition_status": "multi_mark", "letters": ["A", "B"]}
    assert item["choices"] == ["A", "B", "C", "D", "BLANK"]
    assert item["final_answer"] is None and item["resolved"] is False and item["revision"] == 0
    assert item["crop"] and item["crop"]["page_width"] == 1100
    assert item["images"]["checked"].startswith("/api/omr/sheets/") and "?view=checked" in item["images"]["checked"]


def test_no_made_up_confidence_value_is_offered(ctx):
    _, batch = multi_batch(ctx)
    text = json.dumps(review(ctx["admin"], batch["id"])).lower()
    assert "confidence" not in text and "probability" not in text


def test_authorized_user_can_view_the_image(ctx):
    _, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]
    for view, media in (("checked", "image/png"), ("original", "image/png")):
        response = ctx["admin"].get(f"/api/omr/sheets/{item['sheet_id']}/image?view={view}")
        assert response.status_code == 200 and response.headers["content-type"] == media
        assert response.headers["cache-control"] == "private, no-store"
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_unauthorized_users_cannot_view_the_image(ctx, client):
    _, batch = multi_batch(ctx)
    sheet_id = review(ctx["admin"], batch["id"])["items"][0]["sheet_id"]
    url = f"/api/omr/sheets/{sheet_id}/image"

    assert make_client().get(url).status_code == 401                 # signed out
    assert ctx["teacher"].get(url).status_code == 403                # wrong role
    foreign = client.get(url)                                        # another institute
    missing = client.get("/api/omr/sheets/99999999/image")
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()


def test_the_image_view_cannot_be_used_to_reach_other_files(ctx):
    _, batch = multi_batch(ctx)
    sheet_id = review(ctx["admin"], batch["id"])["items"][0]["sheet_id"]
    assert ctx["admin"].get(f"/api/omr/sheets/{sheet_id}/image?view=../../etc/passwd").status_code == 422


def test_admin_resolves_an_item_and_the_raw_reading_is_kept(ctx):
    _, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]

    response = resolve(ctx["admin"], item, "A")

    assert response.status_code == 200
    assert response.json()["batch"]["status"] == "READY_TO_COMMIT"
    _, answers = omr_rows(batch["id"])
    answer = next(a for a in answers if a.id == item["id"])
    # what the engine detected is untouched ...
    assert (answer.raw_value, answer.recognition_status, answer.recognized_answer, answer.review_reason) == \
        ("AB", "multi_mark", None, "MULTI_MARK")
    # ... and the decision is stored separately, with who and when
    assert (answer.final_answer, answer.resolved, answer.reviewed) == ("A", True, True)
    assert answer.reviewed_by_user_id is not None and answer.reviewed_at is not None and answer.revision == 1


def test_a_reviewer_can_choose_blank_which_is_stored_as_blank(ctx):
    _, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]
    assert resolve(ctx["admin"], item, "BLANK").status_code == 200
    answer = next(a for a in omr_rows(batch["id"])[1] if a.id == item["id"])
    assert (answer.final_answer, answer.resolved, answer.recognition_status) == (None, True, "multi_mark")
    shown = next(i for i in review(ctx["admin"], batch["id"])["items"] if i["id"] == item["id"])
    assert shown["final_answer"] == "BLANK" and shown["detected"]["raw_value"] == "AB"


def test_teachers_cannot_change_review_results(ctx):
    _, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]
    response = resolve(ctx["teacher"], item, "A")
    assert response.status_code == 403
    assert next(a for a in omr_rows(batch["id"])[1] if a.id == item["id"]).resolved is False


def test_choices_are_limited_to_the_allowed_answers(ctx):
    _, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]
    for bad in ("E", "AB", "", "blank", None):
        r = ctx["admin"].post(f"/api/omr/review/{item['id']}", json={"final_answer": bad, "revision": 0})
        assert r.status_code == 422


def test_only_items_that_need_review_can_be_changed(ctx):
    _, batch = multi_batch(ctx)
    clear = next(a for a in omr_rows(batch["id"])[1] if a.review_reason is None)
    r = ctx["admin"].post(f"/api/omr/review/{clear.id}", json={"final_answer": "B", "revision": 0})
    assert r.status_code == 422 and "does not need review" in r.json()["detail"]
    assert next(a for a in omr_rows(batch["id"])[1] if a.id == clear.id).final_answer == clear.final_answer


def test_unresolved_items_prevent_the_commit_and_resolving_them_allows_it(ctx):
    test_id, batch = multi_batch(ctx)

    refused = commit(ctx, batch["id"])
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["message"] == "The batch cannot be committed." and detail["problems"]
    assert answer_count(test_id) == 0 and result_count(test_id) == 0

    resolve_all(ctx["admin"], batch["id"], "A")
    summary = ctx["admin"].get(f"/api/omr/batches/{batch['id']}").json()
    assert summary["status"] == "READY_TO_COMMIT" and summary["review_required_count"] == 0
    assert commit(ctx, batch["id"]).status_code == 200


def test_a_decision_can_be_changed_with_the_current_revision(ctx):
    _, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]
    assert resolve(ctx["admin"], item, "A").status_code == 200

    again = next(i for i in review(ctx["admin"], batch["id"])["items"] if i["id"] == item["id"])
    assert again["revision"] == 1 and again["final_answer"] == "A"
    assert resolve(ctx["admin"], again, "B").status_code == 200
    assert next(a for a in omr_rows(batch["id"])[1] if a.id == item["id"]).final_answer == "B"


def test_listing_shows_the_tests_pending_batches(ctx):
    test_id, batch = multi_batch(ctx)
    listed = ctx["admin"].get(f"/api/tests/{test_id}/omr/batches").json()["batches"]
    assert [b["id"] for b in listed] == [batch["id"]] and listed[0]["status"] == "REVIEW_REQUIRED"


# =====================================================================
# Commit
# =====================================================================

def stored_answers(test_id):
    db = SessionLocal()
    try:
        rows = (
            db.query(models.Student.roll_number, models.Question.question_number, models.StudentAnswer.answer)
            .join(models.StudentAnswer, models.StudentAnswer.student_id == models.Student.id)
            .join(models.Question, models.Question.id == models.StudentAnswer.question_id)
            .filter(models.StudentAnswer.test_id == test_id)
        )
        return {(r, q): a for r, q, a in rows}
    finally:
        db.close()


def test_commit_creates_the_expected_answers_and_results(ctx):
    test_id, batch = clean_batch(ctx)

    response = commit(ctx, batch["id"])
    body = response.json()

    assert response.status_code == 200 and body["batch"]["status"] == "COMMITTED"
    assert body["students_evaluated"] == 5 and body["images_removed"] is True

    expected = {(roll, q): (None if ch == "-" else ch)
                for roll, letters in STUDENTS.items() for q, ch in enumerate(letters, start=1)}
    assert stored_answers(test_id) == expected               # 50 answers, blanks stored as NULL
    assert result_count(test_id) == 5
    assert student_results(ctx["admin"], test_id) == EXPECTED   # existing evaluation, hand-calculated marks


def test_commit_records_the_omr_source_and_batch_in_the_audit_trail(ctx):
    test_id, batch = clean_batch(ctx)
    commit(ctx, batch["id"])

    imported = [r for r in audit_rows("answers.import", test_id) if r[4].get("source") == "omr"]
    assert len(imported) == 1
    assert imported[0][4]["omr_batch_id"] == batch["id"] and imported[0][4]["answer_records"] == 50
    assert [r[0] for r in audit_rows(entity_id=batch["id"], entity_type="omr_batch")] == ["omr.batch_create", "omr.batch_commit"]


def test_a_committed_batch_keeps_its_recognition_history_but_not_its_images(ctx):
    _, batch = multi_batch(ctx)
    resolve_all(ctx["admin"], batch["id"], "A")
    sheets_before = len(omr_rows(batch["id"])[0])
    commit(ctx, batch["id"])

    sheets, answers = omr_rows(batch["id"])
    assert len(sheets) == sheets_before and {s.status for s in sheets} == {"COMMITTED"}
    assert any(a.raw_value == "AB" and a.final_answer == "A" for a in answers)   # "read AB, chose A"
    assert not image_dir(batch["id"]).exists()
    summary = ctx["admin"].get(f"/api/omr/batches/{batch['id']}").json()
    assert summary["images_removed"] is True
    sheet_id = sheets[0].id
    assert ctx["admin"].get(f"/api/omr/sheets/{sheet_id}/image").status_code == 404


def test_existing_analytics_are_correct_after_an_omr_commit(ctx):
    """Question and chapter figures, calculated here from the plain answer strings."""
    test_id, batch = clean_batch(ctx)
    commit(ctx, batch["id"])

    questions = ctx["admin"].get(f"/api/tests/{test_id}/analytics/questions").json()["questions"]
    for q in questions:
        number = q["question_number"]
        marked = [letters[number - 1] for letters in STUDENTS.values()]
        correct = sum(1 for m in marked if m == KEY[number - 1])
        blank = sum(1 for m in marked if m == "-")
        assert (q["correct_count"], q["blank_count"], q["wrong_count"]) == (correct, blank, 5 - correct - blank), number

    chapters = {c["chapter_name"]: c for c in
                ctx["admin"].get(f"/api/tests/{test_id}/analytics/chapters-topics").json()["chapters"]}
    for name, numbers in (("Mechanics", range(1, 6)), ("Optics", range(6, 11))):
        want = sum(1 for n in numbers for letters in STUDENTS.values() if letters[n - 1] == KEY[n - 1])
        assert chapters[name]["correct"] == want and chapters[name]["responses"] == 25


def test_excel_export_works_after_an_omr_commit(ctx):
    test_id, batch = clean_batch(ctx)
    commit(ctx, batch["id"])

    book = workbook(ctx["admin"], test_id)
    students = {r[0].value: [c.value for c in r] for r in book["Student Results"].iter_rows(min_row=2)}
    assert students["101002"][2] == 22 and students["101003"][2] == 0
    assert students["101004"][1] == "'=EVIL()+1"          # formula-like name stays text
    for sheet in book:
        for r in sheet.iter_rows():
            assert all(c.data_type != "f" for c in r)
    # nothing from the upload (filenames, paths) reached the workbook
    text = " ".join(str(c.value) for s in book for r in s.iter_rows() for c in r if c.value)
    assert "scan_" not in text and ".png" not in text


def test_commit_is_atomic_when_a_step_fails(ctx, monkeypatch):
    test_id, batch = clean_batch(ctx)

    real_record = audit.record

    def failing(db, actor, action, *args, **kwargs):
        if action == "omr.batch_commit":              # the very last step
            raise RuntimeError("simulated failure")
        return real_record(db, actor, action, *args, **kwargs)

    monkeypatch.setattr(audit, "record", failing)
    response = commit(ctx, batch["id"])
    monkeypatch.undo()

    assert response.status_code == 409
    assert response.json()["detail"]["problems"][0]["code"] == "commit_failed"
    assert "simulated" not in response.text
    # nothing was written: no answers, no results, no half-finished state
    assert answer_count(test_id) == 0 and result_count(test_id) == 0
    assert [r for r in audit_rows("answers.import", test_id)] == []
    still = ctx["admin"].get(f"/api/omr/batches/{batch['id']}").json()
    assert still["status"] == "READY_TO_COMMIT" and still["committed_at"] is None
    assert image_dir(batch["id"]).exists()            # images kept for the retry

    # the batch is still usable: the same commit now succeeds
    assert commit(ctx, batch["id"]).status_code == 200
    assert answer_count(test_id) == 50


def test_commit_is_atomic_when_the_evaluation_fails(ctx, monkeypatch):
    test_id, batch = clean_batch(ctx)

    def boom(*args, **kwargs):
        raise RuntimeError("evaluation exploded")

    monkeypatch.setattr(importer, "evaluate_test", boom)
    response = commit(ctx, batch["id"])
    monkeypatch.undo()

    assert response.status_code == 409 and "exploded" not in response.text
    assert answer_count(test_id) == 0 and result_count(test_id) == 0
    assert ctx["admin"].get(f"/api/omr/batches/{batch['id']}").json()["status"] == "READY_TO_COMMIT"


def test_existing_answers_block_the_commit_unless_replace_is_chosen(ctx):
    test_id = make_test(ctx)
    csv = "roll_number,question_number,answer\n" + "".join(
        f"{roll},{q},{'' if ch == '-' else ch}\n" for roll, ls in STUDENTS.items() for q, ch in enumerate(ls, 1))
    assert upload_csv(ctx["admin"], "answers", csv, dict(test_id=test_id, dry_run=False))["status"] == "imported"
    before = stored_answers(test_id)

    batch = create_batch(ctx, test_id, sheets_for(overrides={"101001": "BBBBBBBBBB"}))
    refused = commit(ctx, batch["id"])

    assert refused.status_code == 409
    assert any("already exist" in p["message"] for p in refused.json()["detail"]["problems"])
    assert stored_answers(test_id) == before                     # untouched
    assert ctx["admin"].get(f"/api/omr/batches/{batch['id']}").json()["status"] == "READY_TO_COMMIT"


def test_replacing_existing_answers_needs_replace_and_keeps_the_safety_backup(ctx, monkeypatch):
    test_id = make_test(ctx)
    csv = "roll_number,question_number,answer\n" + "".join(
        f"{roll},{q},{'' if ch == '-' else ch}\n" for roll, ls in STUDENTS.items() for q, ch in enumerate(ls, 1))
    upload_csv(ctx["admin"], "answers", csv, dict(test_id=test_id, dry_run=False))

    backups = []
    monkeypatch.setattr(importer, "pre_operation_backup", lambda reason: backups.append(reason))

    batch = create_batch(ctx, test_id, sheets_for(overrides={"101001": "BBBBBBBBBB"}))
    response = commit(ctx, batch["id"], replace=True)

    assert response.status_code == 200
    assert backups == ["replace-answers"]                         # the same safeguard as a CSV replace
    assert stored_answers(test_id)[("101001", 1)] == "B"
    entry = audit_rows("answers.replace", test_id)[0]
    assert entry[4]["source"] == "omr" and entry[4]["omr_batch_id"] == batch["id"]
    assert entry[4]["replaced_answer_records"] == 50


def test_a_failed_replace_leaves_the_existing_answers_exactly_as_they_were(ctx, monkeypatch):
    test_id = make_test(ctx)
    csv = "roll_number,question_number,answer\n" + "".join(
        f"{roll},{q},{'' if ch == '-' else ch}\n" for roll, ls in STUDENTS.items() for q, ch in enumerate(ls, 1))
    upload_csv(ctx["admin"], "answers", csv, dict(test_id=test_id, dry_run=False))
    before, marks_before = stored_answers(test_id), student_results(ctx["admin"], test_id)

    batch = create_batch(ctx, test_id, sheets_for(overrides={"101001": "BBBBBBBBBB"}))
    real_record = audit.record

    def failing(db, actor, action, *args, **kwargs):
        if action == "omr.batch_commit":
            raise RuntimeError("late failure")
        return real_record(db, actor, action, *args, **kwargs)

    monkeypatch.setattr(audit, "record", failing)
    response = commit(ctx, batch["id"], replace=True)
    monkeypatch.undo()

    assert response.status_code == 409
    assert stored_answers(test_id) == before                       # not partially replaced
    assert student_results(ctx["admin"], test_id) == marks_before == EXPECTED
    assert ctx["admin"].get(f"/api/omr/batches/{batch['id']}").json()["status"] == "READY_TO_COMMIT"


def test_commit_checks_the_test_as_it_is_now(ctx):
    """If the test's questions changed after the batch was read, commit refuses."""
    test_id, batch = clean_batch(ctx)
    db = SessionLocal()
    try:
        first = db.query(models.Question).filter_by(test_id=test_id, question_number=1).one()
        db.add(models.Question(test_id=test_id, question_number=11, subject="Physics",
                               chapter_id=first.chapter_id, topic_id=first.topic_id, correct_answer="A"))
        db.commit()
    finally:
        db.close()

    refused = commit(ctx, batch["id"])
    assert refused.status_code == 409
    assert "questions_changed" in {p["code"] for p in refused.json()["detail"]["problems"]}
    assert answer_count(test_id) == 0


def test_commit_checks_the_roster_as_it_is_now(ctx):
    test_id, batch = clean_batch(ctx)
    db = SessionLocal()
    try:
        # the student's roll number is corrected in the roster after the scan
        student = db.query(models.Student).filter_by(batch_id=ctx["batch_id"], roll_number="101003").one()
        student.roll_number = "101033"
        db.commit()
    finally:
        db.close()

    try:
        refused = commit(ctx, batch["id"])
        assert refused.status_code == 409
        assert "unknown_roll" in {p["code"] for p in refused.json()["detail"]["problems"]}
        assert answer_count(test_id) == 0
    finally:
        db = SessionLocal()
        db.query(models.Student).filter_by(batch_id=ctx["batch_id"], roll_number="101033").update(
            {"roll_number": "101003"})
        db.commit(); db.close()


# =====================================================================
# Independent end-to-end test
# =====================================================================

def test_end_to_end_with_review_matches_independently_calculated_results(ctx):
    """
    Images -> recognition -> pending batch -> two doubtful answers ->
    review -> commit -> evaluation -> analytics -> Excel.

    The sheets differ from the plain STUDENTS table in exactly two places:
      101005 Q1 was marked "AB"; the reviewer chooses A (the key's answer)
      101002 Q2 was marked "BC"; the reviewer chooses BLANK
    Expected figures below are calculated by hand:
      101002: correct Q1 Q3 Q5 Q6 Q8 Q10 (6), wrong Q7 (1), blank Q2 Q4 Q9 (3)
              -> 6*4 - 1 = 23
      the other four students are as in omr_support.EXPECTED
    """
    test_id = make_test(ctx)
    overrides = {
        "101005": {1: "AB", **{q: c for q, c in enumerate("BCDABCDAB", start=2)}},
        "101002": {1: "A", 2: "BC", 3: "C", 4: "", 5: "A", 6: "B", 7: "D", 8: "D", 9: "", 10: "B"},
    }
    batch = create_batch(ctx, test_id, sheets_for(overrides=overrides))
    assert batch["status"] == "REVIEW_REQUIRED" and batch["recognition"]["multi_mark"] == 2
    assert answer_count(test_id) == 0                                  # nothing permanent yet

    items = {(i["roll_number"], i["question_number"]): i for i in review(ctx["admin"], batch["id"])["items"]}
    assert set(items) == {("101005", 1), ("101002", 2)}
    assert items[("101005", 1)]["detected"]["raw_value"] == "AB"
    assert items[("101002", 2)]["detected"]["raw_value"] == "BC"

    assert resolve(ctx["admin"], items[("101005", 1)], "A").status_code == 200
    assert ctx["admin"].get(f"/api/omr/batches/{batch['id']}").json()["status"] == "REVIEW_REQUIRED"   # one left
    assert resolve(ctx["admin"], items[("101002", 2)], "BLANK").status_code == 200
    assert ctx["admin"].get(f"/api/omr/batches/{batch['id']}").json()["status"] == "READY_TO_COMMIT"

    assert commit(ctx, batch["id"]).status_code == 200

    final = {roll: letters for roll, letters in STUDENTS.items()}
    final["101002"] = "A-C-ABDD-B"
    assert stored_answers(test_id) == {
        (roll, q): (None if ch == "-" else ch) for roll, ls in final.items() for q, ch in enumerate(ls, 1)}

    expected = dict(EXPECTED)
    expected["101002"] = (23, 6, 1, 3)
    assert student_results(ctx["admin"], test_id) == expected

    # question 2: only 101001 (B) and 101003 is blank, 101002 now blank, 101004 B, 101005 B
    q2 = next(q for q in ctx["admin"].get(f"/api/tests/{test_id}/analytics/questions").json()["questions"]
              if q["question_number"] == 2)
    assert (q2["correct_count"], q2["wrong_count"], q2["blank_count"]) == (3, 0, 2)

    # Excel: marks and formula-safe names
    book = workbook(ctx["admin"], test_id)
    rows = {r[0].value: [c.value for c in r] for r in book["Student Results"].iter_rows(min_row=2)}
    assert [rows[r][2] for r in ("101001", "101002", "101003", "101004", "101005")] == [40, 23, 0, 10, 40]
    summary = {r[0].value: r[1].value for r in book["Test Summary"].iter_rows() if r[0].value}
    assert summary["Students evaluated"] == 5 and summary["Highest marks"] == 40


# =====================================================================
# Discard
# =====================================================================

def test_discard_removes_pending_records_and_images_and_is_audited(ctx):
    test_id, batch = multi_batch(ctx)
    assert image_dir(batch["id"]).exists()

    response = ctx["admin"].post(f"/api/omr/batches/{batch['id']}/discard")

    assert response.status_code == 200
    assert response.json()["batch"]["status"] == "DISCARDED" and response.json()["images_removed"] is True
    assert omr_rows(batch["id"]) == ([], [])
    assert not image_dir(batch["id"]).exists()
    assert answer_count(test_id) == 0
    entries = audit_rows("omr.batch_discard", batch["id"])
    assert len(entries) == 1 and entries[0][3] is not None and entries[0][4]["sheets"] == 5


def test_discard_leaves_existing_answers_and_results_untouched(ctx):
    test_id = make_test(ctx)
    csv = "roll_number,question_number,answer\n" + "".join(
        f"{roll},{q},{'' if ch == '-' else ch}\n" for roll, ls in STUDENTS.items() for q, ch in enumerate(ls, 1))
    upload_csv(ctx["admin"], "answers", csv, dict(test_id=test_id, dry_run=False))
    answers, marks, results = stored_answers(test_id), student_results(ctx["admin"], test_id), result_count(test_id)

    batch = create_batch(ctx, test_id, sheets_for(overrides=MULTI))
    ctx["admin"].post(f"/api/omr/batches/{batch['id']}/discard")

    assert stored_answers(test_id) == answers and student_results(ctx["admin"], test_id) == marks == EXPECTED
    assert result_count(test_id) == results


def test_repeated_discard_is_safe_and_not_logged_twice(ctx):
    _, batch = multi_batch(ctx)
    first = ctx["admin"].post(f"/api/omr/batches/{batch['id']}/discard")
    second = ctx["admin"].post(f"/api/omr/batches/{batch['id']}/discard")

    assert first.json()["already_discarded"] is False
    assert second.status_code == 200 and second.json()["already_discarded"] is True
    assert len(audit_rows("omr.batch_discard", batch["id"])) == 1


def test_a_failed_image_cleanup_is_reported_and_retried(ctx, monkeypatch):
    _, batch = multi_batch(ctx)
    monkeypatch.setattr(storage.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(OSError("busy")))

    first = ctx["admin"].post(f"/api/omr/batches/{batch['id']}/discard")
    assert first.status_code == 200
    assert first.json()["images_removed"] is False and first.json()["batch"]["status"] == "DISCARDED"
    assert "busy" not in first.text and image_dir(batch["id"]).exists()      # honest: not claimed deleted
    monkeypatch.undo()

    retry = ctx["admin"].post(f"/api/omr/batches/{batch['id']}/discard")      # idempotent, retries cleanup
    assert retry.json()["images_removed"] is True and not image_dir(batch["id"]).exists()


def test_a_committed_batch_cannot_be_discarded_and_a_discarded_one_cannot_be_committed(ctx):
    _, committed = clean_batch(ctx)
    commit(ctx, committed["id"])
    assert ctx["admin"].post(f"/api/omr/batches/{committed['id']}/discard").status_code == 409

    _, discarded = clean_batch(ctx)
    ctx["admin"].post(f"/api/omr/batches/{discarded['id']}/discard")
    assert commit(ctx, discarded["id"]).status_code == 409


# =====================================================================
# Tenant isolation and access
# =====================================================================

def test_other_institutes_cannot_reach_a_batch_in_any_way(ctx, client):
    test_id, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]
    bid = batch["id"]

    attempts = [
        ("get", f"/api/omr/batches/{bid}", None),
        ("get", f"/api/omr/batches/{bid}/review", None),
        ("get", f"/api/tests/{test_id}/omr/batches", None),
        ("get", f"/api/omr/sheets/{item['sheet_id']}/image", None),
        ("post", f"/api/omr/review/{item['id']}", {"final_answer": "A", "revision": 0}),
        ("post", f"/api/omr/sheets/{item['sheet_id']}/roll", {"roll_number": "101001", "revision": 0}),
        ("post", f"/api/omr/batches/{bid}/commit", {}),
        ("post", f"/api/omr/batches/{bid}/discard", None),
    ]
    for method, url, body in attempts:
        response = client.get(url) if method == "get" else client.post(url, json=body)
        assert response.status_code == 404, (method, url, response.status_code)

    # ... and nothing changed
    assert ctx["admin"].get(f"/api/omr/batches/{bid}").json()["status"] == "REVIEW_REQUIRED"
    assert next(a for a in omr_rows(bid)[1] if a.id == item["id"]).resolved is False


@pytest.mark.parametrize("method,url", [
    ("get", "/api/omr/batches/1"), ("get", "/api/omr/batches/1/review"),
    ("get", "/api/omr/sheets/1/image"), ("get", "/api/omr/templates"),
    ("get", "/api/tests/1/omr/batches"), ("post", "/api/omr/review/1"),
    ("post", "/api/omr/sheets/1/roll"), ("post", "/api/omr/batches/1/commit"),
    ("post", "/api/omr/batches/1/discard"), ("post", "/api/tests/1/omr/import"),
])
def test_every_omr_endpoint_requires_sign_in_and_the_admin_role(ctx, method, url):
    anonymous = make_client()
    teacher = ctx["teacher"]
    send = lambda c: c.get(url) if method == "get" else c.post(url, json={})
    assert send(anonymous).status_code == 401
    assert send(teacher).status_code == 403


# =====================================================================
# Audit
# =====================================================================

def test_each_stage_is_audited_with_the_user_and_without_personal_data(ctx):
    test_id, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]
    resolve(ctx["admin"], item, "A")
    commit(ctx, batch["id"])

    entries = audit_rows(entity_id=batch["id"], entity_type="omr_batch")
    assert [e[0] for e in entries] == ["omr.batch_create", "omr.review", "omr.batch_commit"]
    admin_id = next(e[3] for e in entries)
    assert admin_id is not None and all(e[3] == admin_id for e in entries)   # who did each step
    assert entries[1][4] == {"kind": "answer", "item_id": item["id"], "reason": "MULTI_MARK"}

    everything = json.dumps([e[4] for e in entries] + [r[4] for r in audit_rows("answers.import", test_id)]).lower()
    for roll in STUDENTS:
        assert roll not in everything                     # no roll numbers
    for name in NAMES.values():
        assert name.lower() not in everything             # no student names
    for secret in ("password", "token", "session", "cookie", "csrf", ".png", "/tmp", "scan_"):
        assert secret not in everything
    assert '"ab"' not in everything                       # not the raw reading either
    assert "image" not in everything and "bytes" not in everything


# =====================================================================
# Lifecycle and concurrency
# =====================================================================

@pytest.mark.parametrize("start,target,allowed", [
    ("PROCESSING", "READY_TO_COMMIT", True), ("PROCESSING", "FAILED", True),
    ("REVIEW_REQUIRED", "READY_TO_COMMIT", True), ("REVIEW_REQUIRED", "DISCARDED", True),
    ("READY_TO_COMMIT", "COMMITTED", True), ("READY_TO_COMMIT", "REVIEW_REQUIRED", True),
    ("FAILED", "DISCARDED", True),
    ("COMMITTED", "REVIEW_REQUIRED", False), ("COMMITTED", "DISCARDED", False),
    ("COMMITTED", "READY_TO_COMMIT", False), ("DISCARDED", "COMMITTED", False),
    ("DISCARDED", "REVIEW_REQUIRED", False), ("REVIEW_REQUIRED", "COMMITTED", False),
    ("FAILED", "COMMITTED", False), ("PROCESSING", "COMMITTED", False),
])
def test_state_transitions(start, target, allowed):
    batch = models.OMRBatch(status=start, updated_at=datetime.utcnow())
    if allowed:
        batches.transition(batch, target)
        assert batch.status == target
    else:
        with pytest.raises(batches.BatchStateError):
            batches.transition(batch, target)
        assert batch.status == start


def test_a_committed_batch_can_no_longer_be_reviewed_or_changed(ctx):
    _, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]
    resolve(ctx["admin"], item, "A")
    commit(ctx, batch["id"])

    again = resolve(ctx["admin"], {"id": item["id"], "revision": 1}, "B")
    assert again.status_code == 409 and "can no longer be reviewed" in again.json()["detail"]
    assert next(a for a in omr_rows(batch["id"])[1] if a.id == item["id"]).final_answer == "A"


def test_a_stale_revision_is_a_clear_conflict_not_a_silent_overwrite(ctx):
    _, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]

    first = resolve(ctx["admin"], item, "A")                       # reviewer 1
    second = resolve(ctx["admin"], item, "B")                      # reviewer 2 still on revision 0

    assert first.status_code == 200
    assert second.status_code == 409 and "changed by someone else" in second.json()["detail"]
    assert next(a for a in omr_rows(batch["id"])[1] if a.id == item["id"]).final_answer == "A"


def test_two_simultaneous_decisions_cannot_both_win(ctx):
    _, batch = multi_batch(ctx)
    item = review(ctx["admin"], batch["id"])["items"][0]
    other = make_client("admin@omr-b.test", "omr-test-password")
    barrier, outcomes = threading.Barrier(2), []

    def attempt(client, choice):
        barrier.wait()
        outcomes.append((choice, resolve(client, item, choice).status_code))

    threads = [threading.Thread(target=attempt, args=(ctx["admin"], "A")),
               threading.Thread(target=attempt, args=(other, "C"))]
    [t.start() for t in threads]; [t.join() for t in threads]

    assert sorted(code for _, code in outcomes) == [200, 409]
    winner = next(choice for choice, code in outcomes if code == 200)
    assert next(a for a in omr_rows(batch["id"])[1] if a.id == item["id"]).final_answer == winner


def test_two_simultaneous_commits_apply_once(ctx):
    test_id, batch = clean_batch(ctx)
    other = make_client("admin@omr-b.test", "omr-test-password")
    barrier, codes = threading.Barrier(2), []

    def attempt(client):
        barrier.wait()
        codes.append(client.post(f"/api/omr/batches/{batch['id']}/commit", json={}).status_code)

    threads = [threading.Thread(target=attempt, args=(c,)) for c in (ctx["admin"], other)]
    [t.start() for t in threads]; [t.join() for t in threads]

    assert sorted(codes) == [200, 409]
    assert answer_count(test_id) == 50 and result_count(test_id) == 5
    assert len([e for e in audit_rows("omr.batch_commit", batch["id"])]) == 1


def test_repeated_commit_is_refused_without_changing_anything(ctx):
    test_id, batch = clean_batch(ctx)
    assert commit(ctx, batch["id"]).status_code == 200
    again = commit(ctx, batch["id"])

    assert again.status_code == 409 and "already been committed" in again.json()["detail"]
    assert answer_count(test_id) == 50 and len(audit_rows("omr.batch_commit", batch["id"])) == 1


def test_an_interrupted_batch_is_shown_as_failed_and_can_be_discarded(ctx):
    test_id = make_test(ctx)
    db = SessionLocal()
    try:
        old = datetime.utcnow() - timedelta(seconds=config.OMR_PROCESSING_STALE_SECONDS + 60)
        stuck = models.OMRBatch(
            institute_id=ctx["institute_id"], test_id=test_id, created_by_user_id=1,
            status="PROCESSING", template_id="prototype-60q", template_version=1,
            created_at=old, updated_at=old)
        db.add(stuck); db.commit()
        batch_id = stuck.id
    finally:
        db.close()

    shown = ctx["admin"].get(f"/api/omr/batches/{batch_id}").json()
    assert shown["status"] == "FAILED" and shown["failure_code"] == "interrupted"
    assert ctx["admin"].post(f"/api/omr/batches/{batch_id}/discard").json()["batch"]["status"] == "DISCARDED"
