"""
The vendored OMRChecker and proof that it is the audited version.

OMRChecker (https://github.com/Udayraj123/OMRChecker, MIT licence) is
included unmodified under third_party/omrchecker at one exact upstream
commit. third_party/omrchecker/UPSTREAM.json records that commit and the
git blob id of every vendored file, so the content can be compared with
upstream (`git ls-tree -r <commit>`) and any drift is detected here.

Only the files OMRChecker needs to run on images are included; upstream's
tests and samples (which contain third-party sample images) are not.
"""

import hashlib
import json
from pathlib import Path

VENDOR_ROOT = Path(__file__).resolve().parents[3] / "third_party" / "omrchecker"
MANIFEST_PATH = VENDOR_ROOT / "UPSTREAM.json"
ENTRY_POINT = VENDOR_ROOT / "main.py"

# The only version this product may use (full hash of upstream 5cf44a5).
EXPECTED_COMMIT = "5cf44a5a9c7a49e2e541c6e19aefd09a41a4d494"


def git_blob_id(data: bytes) -> str:
    """The id git gives a file with this content."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def vendored_files() -> list[Path]:
    return sorted(
        p
        for p in VENDOR_ROOT.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.name != "UPSTREAM.json"
    )


def verify_vendored() -> list[str]:
    """
    Problems found when comparing the vendored files with the manifest;
    an empty list means every file is exactly what upstream has at the
    pinned commit.
    """

    problems = []

    try:
        manifest = load_manifest()
    except (OSError, ValueError) as error:
        return [f"manifest unreadable: {type(error).__name__}"]

    if manifest.get("commit") != EXPECTED_COMMIT:
        problems.append("manifest is not for the audited commit")

    if manifest.get("license") != "MIT":
        problems.append("manifest does not record the MIT licence")

    expected = manifest.get("files", {})
    found = {
        p.relative_to(VENDOR_ROOT).as_posix(): git_blob_id(p.read_bytes())
        for p in vendored_files()
    }

    for name in sorted(expected.keys() - found.keys()):
        problems.append(f"missing: {name}")

    for name in sorted(found.keys() - expected.keys()):
        problems.append(f"unexpected file: {name}")

    for name in sorted(expected.keys() & found.keys()):
        if expected[name] != found[name]:
            problems.append(f"modified: {name}")

    if "LICENSE" not in found:
        problems.append("the upstream LICENSE file is missing")

    return problems
