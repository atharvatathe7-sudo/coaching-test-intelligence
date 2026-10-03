"""
The vendored OMRChecker is exactly the audited upstream commit, under
its MIT licence, with no PDF dependency and no third-party sample images.
"""

import re
import subprocess
import sys
from pathlib import Path

from backend.app.omr import vendor

ROOT = Path(__file__).resolve().parents[1]
AUDITED_COMMIT = "5cf44a5a9c7a49e2e541c6e19aefd09a41a4d494"


def test_pinned_to_exactly_the_audited_commit():
    manifest = vendor.load_manifest()
    assert vendor.EXPECTED_COMMIT == AUDITED_COMMIT
    assert manifest["commit"] == AUDITED_COMMIT and manifest["commit"].startswith("5cf44a5")
    assert manifest["repository"] == "https://github.com/Udayraj123/OMRChecker"
    assert manifest["modifications"].startswith("none")


def test_every_vendored_file_is_byte_identical_to_upstream():
    # blob ids come from the upstream tree at the pinned commit
    assert vendor.verify_vendored() == []


def test_verification_detects_any_change(tmp_path, monkeypatch):
    copy = tmp_path / "omrchecker"
    import shutil
    shutil.copytree(vendor.VENDOR_ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(vendor, "VENDOR_ROOT", copy)
    monkeypatch.setattr(vendor, "MANIFEST_PATH", copy / "UPSTREAM.json")
    assert vendor.verify_vendored() == []

    (copy / "src" / "core.py").write_text("# tampered\n")
    (copy / "extra.py").write_text("")
    (copy / "src" / "logger.py").unlink()
    problems = vendor.verify_vendored()
    assert "modified: src/core.py" in problems
    assert "unexpected file: extra.py" in problems
    assert "missing: src/logger.py" in problems


def test_mit_licence_and_copyright_are_preserved():
    licence = (vendor.VENDOR_ROOT / "LICENSE").read_text()
    assert licence.startswith("MIT License")
    assert "Copyright (c) 2024-present Udayraj Deshmukh and other contributors" in licence
    assert "GNU GENERAL PUBLIC LICENSE" not in licence

    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    assert AUDITED_COMMIT in notices and "OMRChecker" in notices
    assert licence.strip() in notices          # full licence text reproduced
    assert "not original" in " ".join(notices.split())


def test_no_images_or_documents_are_vendored():
    forbidden = {".png", ".jpg", ".jpeg", ".pdf", ".gif", ".bmp"}
    files = [p for p in vendor.VENDOR_ROOT.rglob("*") if p.suffix.lower() in forbidden]
    assert files == []
    assert not (vendor.VENDOR_ROOT / "samples").exists()
    assert not (vendor.VENDOR_ROOT / "src" / "tests").exists()


def test_pdf_and_gui_dependencies_are_not_introduced():
    for name in ("requirements.txt", "requirements-omr.txt"):
        text = (ROOT / "backend" / name).read_text()
        packages = {
            re.split(r"[=<>~!\s]", line, maxsplit=1)[0].lower()
            for line in text.splitlines()
            if line.strip() and not line.startswith(("#", "-r"))
        }
        assert not {"pymupdf", "fitz", "screeninfo", "opencv-python",
                    "opencv-contrib-python", "pyzbar"} & packages

    omr = (ROOT / "backend" / "requirements-omr.txt").read_text()
    pins = [l for l in omr.splitlines() if l.strip() and not l.startswith("#")]
    assert pins and all("==" in line for line in pins)    # exact versions only


def test_image_only_processing_needs_neither_pymupdf_nor_a_display(monkeypatch):
    """
    A real recognition runs with no display variable, and PyMuPDF /
    screeninfo are not among the modules the engine requires.
    """
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    from omr_sheets import render_sheet
    from backend.app.omr import checker
    from backend.app.omr.images import inspect_image
    from backend.app.omr.template import get_template

    assert "fitz" not in checker.REQUIRED_MODULES
    assert "screeninfo" not in checker.REQUIRED_MODULES

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    png = render_sheet("123456", {1: "C"})
    with checker.BatchWorkspace(get_template(None)) as workspace:
        workspace.add_image(1, png, inspect_image(png, "a.png"))
        run = checker.run_recognition(workspace)

    assert run.errored == set()
    assert run.rows[1]["Roll"] == "123456" and run.rows[1]["q1"] == "C"


def test_running_the_recogniser_does_not_modify_the_vendored_tree():
    """No bytecode, output or other file appears in third_party/omrchecker."""
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    from omr_sheets import render_sheet
    from backend.app.omr import checker
    from backend.app.omr.images import inspect_image
    from backend.app.omr.template import get_template

    def snapshot():
        return {p: p.stat().st_mtime_ns for p in vendor.VENDOR_ROOT.rglob("*")}

    before = snapshot()
    png = render_sheet("123456", {1: "A"})
    with checker.BatchWorkspace(get_template(None)) as workspace:
        workspace.add_image(1, png, inspect_image(png, "a.png"))
        checker.run_recognition(workspace)

    assert snapshot() == before
    assert vendor.verify_vendored() == []
    assert not list(vendor.VENDOR_ROOT.rglob("__pycache__"))
