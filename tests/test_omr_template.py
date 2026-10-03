"""
The project-owned marked prototype template (prototype-marked-60q):
deterministic artwork, alignment on photographs, accurate crops, and the
unreadable-sheet path.

All sheets are synthetic and drawn by the project's own generator; no
upstream or community images are used. Results on synthetic sheets say
nothing about real printed sheets or real phone photographs.
"""

import random
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.app.omr import sheet_design
from backend.app.omr.checker import BatchWorkspace, run_recognition
from backend.app.omr.images import inspect_image
from backend.app.omr.normalization import normalize_sheet
from backend.app.omr.template import get_template

from omr_sheets import photograph
from omr_support import (
    EXPECTED,
    STUDENTS,
    create_batch,
    get_ctx,
    make_test,
    post_batch,
    review,
    student_results,
    to_answers,
)

MARKED = "prototype-marked-60q"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ctx(demo_database):
    return get_ctx("c")


def test_marker_and_sheet_generation_are_deterministic():
    template = get_template(MARKED)
    committed = cv2.imread(str(template.directory / template.marker_file), cv2.IMREAD_GRAYSCALE)
    assert np.array_equal(committed, sheet_design.marker_image())          # the file is the generator's output

    a = sheet_design.render_sheet(template, "123456", {1: "A", 2: "AB"}, labels=True, seed=3)
    b = sheet_design.render_sheet(template, "123456", {1: "A", 2: "AB"}, labels=True, seed=3)
    assert np.array_equal(a, b) and a.shape == (1720, 1220)                # 1100x1600 page + 2 x 60 margin


def test_printable_blank_sheet_script(tmp_path):
    out = tmp_path / "sheet.png"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_prototype_sheet.py"), "--out", str(out)],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    image = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
    assert image.shape == (1720, 1220)
    assert (image < 20).sum() > 10_000                                      # the four black markers are there


def test_the_template_is_described_and_documented():
    template = get_template(MARKED)
    assert (template.id, template.version, template.roll_digits) == (MARKED, 1, 6)
    assert template.question_numbers == tuple(range(1, 61)) and template.options == ("A", "B", "C", "D")
    assert (template.directory / "README.md").is_file()


def _random_answers(rng, doubtful):
    answers = {}
    for q in range(1, 61):
        if q in doubtful:
            answers[q] = "".join(sorted(rng.sample("ABCD", 2)))
        else:
            answers[q] = rng.choice(["A", "B", "C", "D", "A", "B", ""])
    return answers


def test_photographed_sheets_are_read_exactly():
    """Rotated, tilted, shrunk, off-centre, noisy JPEG photographs of marked sheets."""
    template = get_template(MARKED)
    rng = random.Random(11)
    truth = []
    with BatchWorkspace(template) as workspace:
        for i in range(1, 9):
            roll = f"{200000 + i}"
            answers = _random_answers(rng, doubtful={7, 8} if i % 2 else set())
            data = photograph(roll, answers, seed=i, rotation=3.0, tilt=0.02)
            workspace.add_image(i, data, inspect_image(data, "p.jpg"))
            truth.append((roll, answers))
        run = run_recognition(workspace)

    assert run.errored == set() and sorted(run.rows) == list(range(1, 9))

    wrong = 0
    for i, (roll, answers) in enumerate(truth, start=1):
        sheet = normalize_sheet(i, "p", run.rows[i], template, set(range(1, 61)))
        assert sheet.roll_number == roll, i
        for a in sheet.answers:
            drawn = answers[a.question_number]
            want = "multi_mark" if len(drawn) > 1 else "blank" if drawn == "" else "recognized"
            ok = a.status.value == want and (want != "recognized" or a.normalized_answer == drawn)
            if want == "multi_mark":
                ok = ok and a.raw_value == drawn
            wrong += not ok
    assert wrong == 0, f"{wrong} of {8 * 60} answers differ from what was drawn"


def test_crop_regions_line_up_with_the_bubbles_in_the_stored_image(ctx):
    """The crop for a question really contains the bubble that was marked."""
    test_id = make_test(ctx)
    answers = {q: "A" for q in range(1, 11)}
    answers[5] = "C"
    data = photograph("101001", answers, seed=4)
    batch = create_batch(ctx, test_id, [("p.jpg", data)], template_id=MARKED)
    sheet_id = None

    from omr_support import omr_rows
    sheets, _ = omr_rows(batch["id"])
    sheet_id = sheets[0].id
    response = ctx["admin"].get(f"/api/omr/sheets/{sheet_id}/image?view=checked")
    assert response.status_code == 200
    checked = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_GRAYSCALE)

    template = get_template(MARKED)
    region = template.question_region(5)
    assert checked.shape[::-1] == (region["page_width"], region["page_height"])      # template coordinates
    # q5 is in the left block: x origin 100, row 5 -> y = 470 + 4*36
    row_y, bubble = 470 + 4 * 36, 30
    mean = lambda col: checked[row_y:row_y + bubble, 100 + col * 50:100 + col * 50 + bubble].mean()
    assert mean(2) < mean(0) - 40                      # the C bubble is dark, A is not
    # the crop rectangle contains that whole row of bubbles
    assert region["x"] <= 100 and region["x"] + region["width"] >= 100 + 3 * 50 + bubble
    assert region["y"] <= row_y and region["y"] + region["height"] >= row_y + bubble


def test_a_marked_template_batch_goes_through_review_and_commit(ctx):
    test_id = make_test(ctx)
    files = []
    for i, (roll, letters) in enumerate(STUDENTS.items(), start=1):
        files.append((f"photo_{roll}.jpg", photograph(roll, to_answers(letters), seed=i)))
    batch = create_batch(ctx, test_id, files, template_id=MARKED)

    assert batch["status"] == "READY_TO_COMMIT" and batch["template"]["id"] == MARKED
    response = ctx["admin"].post(f"/api/omr/batches/{batch['id']}/commit", json={})
    assert response.status_code == 200
    assert student_results(ctx["admin"], test_id) == EXPECTED


def test_a_sheet_without_markers_is_unreadable_not_guessed(ctx):
    """No markers to align on: the sheet is reported, never read blindly."""
    test_id = make_test(ctx)
    rng = np.random.default_rng(1)
    blank = np.clip(rng.normal(190, 12, (1600, 1100)), 0, 255).astype(np.uint8)
    ok, png = cv2.imencode(".png", blank)

    good = photograph("101001", to_answers(STUDENTS["101001"]), seed=2)
    batch = create_batch(ctx, test_id, [("good.jpg", good), ("nomarkers.png", png.tobytes())], template_id=MARKED)

    assert batch["status"] == "REVIEW_REQUIRED" and batch["error_count"] == 1
    items = review(ctx["admin"], batch["id"])["items"]
    assert [(i["reason"], i["filename"], i["resolvable"]) for i in items] == [("UNREADABLE_SHEET", "nomarkers.png", False)]
    assert ctx["admin"].post(f"/api/omr/batches/{batch['id']}/commit", json={}).status_code == 409
