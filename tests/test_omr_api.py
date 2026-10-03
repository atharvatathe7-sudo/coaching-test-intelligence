"""
OMR upload through the API (Stages 2B and 3): access control, upload
validation, safe processing, failure handling and cleanup.

Reading sheets creates a pending batch; it never creates an answer or a
result. Review, commit and discard are in test_omr_review.py.
"""

import subprocess
from pathlib import Path

import pytest

from backend.app import config
from backend.app.database import models
from backend.app.database.connection import SessionLocal
from backend.app.omr import checker, storage
from backend.app.omr.service import create_pending_batch  # noqa: F401  (import check)

from conftest import make_client
from omr_sheets import render_sheet
from omr_support import (
    answer_count,
    get_ctx,
    image_dir,
    make_test,
    omr_rows,
    post_batch,
    result_count,
    sheets_for,
)


@pytest.fixture(scope="module")
def ctx(demo_database):
    return get_ctx("a")


def batch_rows(test_id):
    db = SessionLocal()
    try:
        return db.query(models.OMRBatch).filter_by(test_id=test_id).all()
    finally:
        db.close()


# ------------------------------------------------------------------
# Access control
# ------------------------------------------------------------------

def test_unauthenticated_access_is_rejected(ctx):
    test_id = make_test(ctx)
    assert post_batch(make_client(), test_id, sheets_for(["101001"])).status_code == 401
    assert batch_rows(test_id) == []


def test_teachers_cannot_import_omr(ctx):
    test_id = make_test(ctx)
    assert post_batch(ctx["teacher"], test_id, sheets_for(["101001"])).status_code == 403
    assert batch_rows(test_id) == []


def test_other_institutes_cannot_use_this_test(ctx, client):
    """The demo institute's admin is told the test does not exist."""
    test_id = make_test(ctx)
    foreign = post_batch(client, test_id, sheets_for(["101001"]))
    missing = post_batch(client, 99999999, sheets_for(["101001"]))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert batch_rows(test_id) == []


def test_a_demo_test_cannot_be_reached_from_this_institute(ctx, test_ids):
    assert post_batch(ctx["admin"], test_ids[0], sheets_for(["101001"])).status_code == 404


@pytest.mark.parametrize("path", [
    "/api/tests/{test}/omr/import",
    "/api/omr/review/{item}",
    "/api/omr/sheets/{sheet}/roll",
    "/api/omr/batches/{batch}/commit",
    "/api/omr/batches/{batch}/discard",
])
def test_changes_without_the_csrf_header_are_refused(ctx, path):
    test_id = make_test(ctx)
    client = make_client("admin@omr-a.test", "omr-test-password")
    client.headers.pop("X-Requested-With")           # a request from another site
    url = path.format(test=test_id, item=1, sheet=1, batch=1)

    response = client.post(url, files=[("files", ("a.png", b"x", "image/png"))])

    assert response.status_code == 403
    assert answer_count(test_id) == 0 and batch_rows(test_id) == []


# ------------------------------------------------------------------
# Reading sheets creates a pending batch, never answers
# ------------------------------------------------------------------

def test_upload_creates_a_pending_batch_and_no_answers(ctx):
    test_id = make_test(ctx)
    response = post_batch(ctx["admin"], test_id, sheets_for())
    body = response.json()

    assert response.status_code == 200 and body["errors"] == []
    batch = body["batch"]
    assert batch["status"] in ("REVIEW_REQUIRED", "READY_TO_COMMIT")
    assert batch["total_sheets"] == 5 and batch["test_id"] == test_id
    assert answer_count(test_id) == 0 and result_count(test_id) == 0   # nothing permanent yet

    sheets, answers = omr_rows(batch["id"])
    assert len(sheets) == 5 and len(answers) == 50
    assert {s.roll_number for s in sheets} == set("101001 101002 101003 101004 101005".split())


def test_stored_images_live_in_the_data_directory_under_internal_names(ctx):
    test_id = make_test(ctx)
    batch = post_batch(ctx["admin"], test_id, sheets_for(["101001", "101002"],
                       names={"101001": "../../evil name.png"})).json()["batch"]
    sheets, _ = omr_rows(batch["id"])

    root = Path(config.OMR_STORAGE_DIR).resolve()
    files = sorted(p for p in image_dir(batch["id"]).rglob("*") if p.is_file())

    assert files and all(p.resolve().is_relative_to(root) for p in files)
    assert not any(str(Path(__file__).resolve().parents[1]) in str(p) for p in files)  # not in the repo
    names = {p.name for p in files}
    for sheet in sheets:
        assert f"{sheet.id}.png" in names and f"{sheet.id}.checked.png" in names
    assert not any("evil" in n for n in names)           # the upload's name is never a path


def test_templates_are_listed(ctx):
    body = ctx["admin"].get("/api/omr/templates").json()
    assert {"prototype-60q", "prototype-marked-60q"} <= {t["id"] for t in body["templates"]}
    assert all("path" not in t and "directory" not in t for t in body["templates"])


# ------------------------------------------------------------------
# Uploads that must be refused before anything is stored
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,data",
    [
        ("notes.png", b"this is not an image" * 100),
        ("empty.png", b""),
        ("doc.pdf", b"%PDF-1.4\n" + b"x" * 500),
        ("sheet.gif", b"GIF89a" + b"x" * 500),
    ],
)
def test_invalid_images_are_rejected_and_nothing_is_stored(ctx, monkeypatch, name, data):
    test_id = make_test(ctx)
    ran = []
    import backend.app.omr.service as service
    monkeypatch.setattr(service, "run_recognition", lambda ws: ran.append(1))

    body = post_batch(ctx["admin"], test_id, sheets_for(["101001"]) + [(name, data)]).json()

    assert body["status"] == "rejected" and body["batch"] is None
    assert [e["code"] for e in body["errors"]] == ["invalid_image"]
    assert body["errors"][0]["sheet"] == name
    assert ran == [] and batch_rows(test_id) == [] and answer_count(test_id) == 0


def test_oversized_image_is_rejected(ctx, monkeypatch):
    test_id = make_test(ctx)
    monkeypatch.setattr(config, "MAX_OMR_IMAGE_BYTES", 50_000)
    body = post_batch(ctx["admin"], test_id, sheets_for(["101001"])).json()
    assert body["status"] == "rejected" and "larger than" in body["errors"][0]["message"]
    assert batch_rows(test_id) == []


def test_oversized_request_is_refused_before_it_is_read(ctx, monkeypatch):
    test_id = make_test(ctx)
    monkeypatch.setattr(config, "MAX_OMR_REQUEST_BYTES", 100_000)
    response = post_batch(ctx["admin"], test_id, sheets_for(["101001"]))
    assert response.status_code == 413 and "OMR uploads may be up to" in response.json()["detail"]
    assert batch_rows(test_id) == []


def test_too_many_files_and_no_files_are_refused(ctx, monkeypatch):
    test_id = make_test(ctx)
    monkeypatch.setattr(config, "MAX_OMR_FILES", 2)
    many = post_batch(ctx["admin"], test_id, sheets_for(["101001", "101002", "101003"])).json()
    assert many["errors"][0]["code"] == "too_many_files"

    none = ctx["admin"].post(f"/api/tests/{test_id}/omr/import", data={}).json()
    assert none["status"] == "rejected" and none["errors"][0]["code"] == "no_files"
    assert batch_rows(test_id) == []


def _corrupt_png():
    """A valid PNG header (so it passes the upload check) with a damaged body."""
    import struct, zlib
    from backend.app.omr.images import PNG_SIGNATURE

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (PNG_SIGNATURE
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1100, 1800, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", b"garbage-not-zlib") + chunk(b"IEND", b""))


def test_an_unreadable_image_is_named_and_stores_nothing(ctx):
    test_id = make_test(ctx)
    files = sheets_for(["101001", "101002"]) + [("damaged.png", _corrupt_png())]
    body = post_batch(ctx["admin"], test_id, files).json()

    assert body["status"] == "rejected" and body["batch"] is None
    assert [(e["code"], e["sheet"]) for e in body["errors"]] == [("invalid_image", "damaged.png")]
    assert batch_rows(test_id) == []


def test_unknown_template_and_incompatible_test_are_rejected(ctx):
    test_id = make_test(ctx)
    unknown = post_batch(ctx["admin"], test_id, sheets_for(["101001"]), template_id="nope").json()
    assert unknown["status"] == "rejected" and unknown["errors"][0]["code"] == "unknown_template"

    big = make_test(ctx, questions=61)            # more questions than the template has
    refused = post_batch(ctx["admin"], big, sheets_for(["101001"])).json()
    assert refused["status"] == "rejected" and refused["errors"][0]["code"] == "template_incompatible"
    assert batch_rows(test_id) == [] and batch_rows(big) == []


def test_questions_outside_the_test_are_reported_not_stored(ctx):
    test_id = make_test(ctx)                      # 10 questions; the template has 60
    extra = {q: ch for q, ch in enumerate("ABCDABCDAB", start=1)}
    extra.update({11: "A", 12: "B"})
    body = post_batch(ctx["admin"], test_id, [("s.png", render_sheet("101001", extra, seed=2))]).json()

    assert any(w["code"] == "template_fields_ignored" for w in body["warnings"])
    assert any(w["code"] == "ignored_fields_marked" for w in body["warnings"])
    _, answers = omr_rows(body["batch"]["id"])
    assert sorted(a.question_number for a in answers) == list(range(1, 11))


# ------------------------------------------------------------------
# Safe processing
# ------------------------------------------------------------------

def test_hostile_filenames_are_never_used_as_paths(ctx):
    test_id = make_test(ctx)
    hostile = {"101001": "../../../../tmp/pwned.png",
               "101002": "..\\..\\windows\\evil.png",
               "101003": "=HYPERLINK(\"http://evil\",\"x\").png"}
    body = post_batch(ctx["admin"], test_id, sheets_for(["101001", "101002", "101003"], names=hostile)).json()

    assert body["batch"]["total_sheets"] == 3
    assert not Path("/tmp/pwned.png").exists()
    sheets, _ = omr_rows(body["batch"]["id"])
    labels = sorted(s.original_filename for s in sheets)
    assert "pwned.png" in labels and "evil.png" in labels      # directories removed
    assert not any("/" in n or "\\" in n for n in labels)


def test_responses_contain_no_paths_or_engine_internals(ctx):
    test_id = make_test(ctx)
    created = post_batch(ctx["admin"], test_id, sheets_for())
    batch_id = created.json()["batch"]["id"]
    texts = [
        created.text,
        post_batch(ctx["admin"], test_id, sheets_for(["101001"]) + [("x.png", b"junk")]).text,
        ctx["admin"].get(f"/api/omr/batches/{batch_id}").text,
        ctx["admin"].get(f"/api/omr/batches/{batch_id}/review").text,
        ctx["admin"].get(f"/api/tests/{test_id}/omr/batches").text,
    ]
    for text in texts:
        for forbidden in (str(config.OMR_STORAGE_DIR), "/tmp", "omr-", "third_party", "Traceback",
                          "sheet_0", "input_path", "output_path", "Results_", "CheckedOMRs", "/home/"):
            assert forbidden not in text, forbidden


def _fail_nth_call(monkeypatch, nth, stderr):
    """Let the first nth-1 subprocess calls run for real, then fail."""
    real, calls = subprocess.run, {"n": 0}

    def fake(command, **kwargs):
        calls["n"] += 1
        if calls["n"] == nth:
            return subprocess.CompletedProcess(command, 1, "", stderr)
        return real(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake)


def test_engine_failure_gives_a_fixed_message_marks_the_batch_failed_and_cleans_up(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    test_id = make_test(ctx)
    _fail_nth_call(monkeypatch, 2, f"Traceback in {tmp_path}")     # the recognition run itself

    response = post_batch(ctx["admin"], test_id, sheets_for(["101001"]))

    assert response.status_code == 502
    assert response.json() == {"detail": "OMR processing failed."}
    assert "Traceback" not in response.text and str(tmp_path) not in response.text
    assert list((tmp_path / "uploads").iterdir()) == []                  # working folder removed
    batch = batch_rows(test_id)[0]
    assert batch.status == "FAILED" and batch.failure_code == "engine"
    assert not image_dir(batch.id).exists()
    assert answer_count(test_id) == 0 and omr_rows(batch.id) == ([], [])


def test_failure_of_the_image_check_stores_nothing(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    test_id = make_test(ctx)
    _fail_nth_call(monkeypatch, 1, "boom")                                # before any batch exists

    response = post_batch(ctx["admin"], test_id, sheets_for(["101001"]))

    assert response.status_code == 502 and response.json() == {"detail": "OMR processing failed."}
    assert batch_rows(test_id) == [] and list((tmp_path / "uploads").iterdir()) == []


def test_timeout_is_reported_safely(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    test_id = make_test(ctx)

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(args, 1)

    monkeypatch.setattr(subprocess, "run", slow)
    response = post_batch(ctx["admin"], test_id, sheets_for(["101001"]))
    assert response.status_code == 502 and "took too long" in response.json()["detail"]
    assert list((tmp_path / "uploads").iterdir()) == []


def test_missing_engine_is_a_clean_503(ctx, monkeypatch):
    test_id = make_test(ctx)
    monkeypatch.setattr(checker, "engine_available", lambda: False)
    response = post_batch(ctx["admin"], test_id, sheets_for(["101001"]))
    assert response.status_code == 503 and "not installed" in response.json()["detail"]


def test_busy_limit_is_reported_and_the_slot_is_always_released(ctx, monkeypatch):
    import threading
    test_id = make_test(ctx)
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(checker, "_slots", slots)

    slots.acquire()                                    # another batch is running
    busy = post_batch(ctx["admin"], test_id, sheets_for(["101001"]))
    assert busy.status_code == 429 and "busy" in busy.json()["detail"]
    slots.release()

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom"))
    assert post_batch(ctx["admin"], test_id, sheets_for(["101001"])).status_code == 502
    monkeypatch.undo()
    monkeypatch.setattr(checker, "_slots", slots)

    assert post_batch(ctx["admin"], test_id, sheets_for(["101001"])).status_code == 200


def test_recogniser_is_run_safely_and_headless(ctx, monkeypatch):
    test_id = make_test(ctx)
    seen = {}
    real_run = subprocess.run

    def spy(command, **kwargs):
        seen.update(command=command, **kwargs)
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("COACHING_SECRET_THING", "do-not-leak")
    post_batch(ctx["admin"], test_id, sheets_for(["101001"], names={"101001": "evil; rm -rf $HOME.png"}))

    assert isinstance(seen["command"], list) and seen["shell"] is False   # no shell
    assert all("evil" not in part for part in seen["command"])            # no user input
    assert seen["cwd"] == str(checker.VENDOR_ROOT)
    assert "DISPLAY" not in seen["env"] and "COACHING_SECRET_THING" not in seen["env"]
    assert seen["env"]["MPLBACKEND"] == "Agg" and seen["timeout"] > 0


def test_each_batch_gets_a_fresh_output_folder(ctx, tmp_path, monkeypatch):
    """OMRChecker appends to an existing results file, so folders are never shared."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    test_id = make_test(ctx)
    outputs = []
    real = checker.run_recognition

    def record(workspace):
        outputs.append(workspace.output_dir)
        assert not workspace.output_dir.exists()          # nothing left from earlier
        return real(workspace)

    import backend.app.omr.service as service
    monkeypatch.setattr(service, "run_recognition", record)

    a = post_batch(ctx["admin"], test_id, sheets_for(["101001", "101002"])).json()["batch"]
    b = post_batch(ctx["admin"], test_id, sheets_for(["101001", "101002"])).json()["batch"]

    assert len(set(outputs)) == 2 and not any(p.exists() for p in outputs)
    # a shared results file would have produced 4 rows the second time
    assert a["total_sheets"] == b["total_sheets"] == 2
    assert len(omr_rows(b["id"])[1]) == 20


def test_temporary_files_are_removed_after_success_and_after_refusals(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    test_id = make_test(ctx)

    post_batch(ctx["admin"], test_id, sheets_for(["101001"]))                        # accepted
    post_batch(ctx["admin"], test_id, sheets_for(["101001"]) + [("x.png", b"j")])    # refused early
    post_batch(ctx["admin"], test_id, sheets_for(["101001"]), template_id="nope")    # refused early

    assert list((tmp_path / "uploads").iterdir()) == []
