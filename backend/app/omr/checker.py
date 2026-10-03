"""
Runs the vendored OMRChecker on a batch of images.

This is the only module that touches OMRChecker, and it never imports it:
OMRChecker is run as a separate child process on a temporary working
folder, and only its result files are read back. Nothing outside this
package depends on OMRChecker's output format.

Safety rules, all enforced here:
  * argument list, never a shell; the command contains no user input
  * a fresh private working folder for every batch (OMRChecker appends to
    an existing results file, so output is never shared between batches)
  * images are written under names chosen here (sheet_0001.png); the
    uploaded filename is never used as a path
  * the child gets a minimal environment, no display and no secrets
  * a timeout, and the working folder is always removed afterwards
  * nothing from the child's output is shown to users; failures are
    reported with fixed messages
"""

import csv
import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import atexit
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from .images import ImageInfo
from .template import OMRTemplate
from .vendor import ENTRY_POINT, VENDOR_ROOT

logger = logging.getLogger("coaching.omr")

HEADLESS_DIR = Path(__file__).resolve().parent / "_headless"

# What OMRChecker imports when it starts (image input only). PyMuPDF and
# screeninfo are deliberately absent.
REQUIRED_MODULES = (
    "cv2", "numpy", "pandas", "matplotlib", "jsonschema",
    "deepmerge", "dotmap", "rich",
)

_FILE_ID = re.compile(r"^sheet_(\d{4})\.(?:png|jpg)$")

_slots = threading.BoundedSemaphore(config.OMR_MAX_CONCURRENT_BATCHES)
_mpl_cache: Path | None = None


class OMREngineError(RuntimeError):
    """The recogniser could not run. `public_message` is safe to show."""

    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


class OMRUnavailable(OMREngineError):
    pass


class OMRBusy(OMREngineError):
    pass


def engine_available() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in REQUIRED_MODULES)


def _work_root() -> Path | None:
    if config.DATA_DIR:
        root = config.DATA_DIR / "uploads"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return None  # the system temporary folder


def _matplotlib_cache() -> Path:
    """
    Where matplotlib keeps its font list. Rebuilding it costs about a
    second, so it is kept between batches: inside the data folder when
    there is one, otherwise in a folder removed when the server exits.
    """
    global _mpl_cache

    if config.DATA_DIR:
        path = config.DATA_DIR / "cache" / "matplotlib"
        path.mkdir(parents=True, exist_ok=True)
        return path

    if _mpl_cache is None:
        _mpl_cache = Path(tempfile.mkdtemp(prefix="coaching-mpl-"))
        atexit.register(shutil.rmtree, _mpl_cache, True)

    return _mpl_cache


@dataclass
class RecognitionRun:
    # sheet index -> OMRChecker's row for it, metadata columns included
    # (normalization.py removes them).
    rows: dict[int, dict[str, str]] = field(default_factory=dict)
    # sheet indexes OMRChecker reported as unreadable
    errored: set[int] = field(default_factory=set)
    # sheet index -> the engine's annotated image, aligned to the template
    # page (inside the working folder: copy it before the folder is removed)
    checked: dict[int, Path] = field(default_factory=dict)


class BatchWorkspace:
    """A private temporary folder for one batch, removed on exit."""

    def __init__(self, template: OMRTemplate):
        self.template = template
        self.root: Path | None = None
        self.input_dir: Path | None = None
        self.output_dir: Path | None = None
        self._count = 0
        self._originals: dict[int, Path] = {}

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="omr-", dir=_work_root()))
        self.input_dir = self.root / "in"
        self.output_dir = self.root / "out"   # created by OMRChecker itself
        self.input_dir.mkdir()

        # The layout, plus any file it refers to (such as a marker image).
        for path in self.template.directory.iterdir():
            if path.is_file() and path.name != "manifest.json":
                shutil.copyfile(path, self.input_dir / path.name)
        # Headless-safe: never open a window. The engine's annotated image
        # (aligned to the template, detections drawn on) is kept so a
        # reviewer can see what it detected.
        (self.input_dir / "config.json").write_text(
            '{"outputs": {"show_image_level": 0, "save_image_level": 0, '
            '"save_detections": true}}',
            encoding="utf-8",
        )
        return self

    def __exit__(self, *exc):
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
            if self.root.exists():
                logger.warning("OMR working folder could not be fully removed")
        return False

    def add_image(self, index: int, data: bytes, info: ImageInfo) -> None:
        """Store one image under a name we choose (never the upload's)."""
        path = self.input_dir / f"sheet_{index:04d}{info.extension}"
        path.write_bytes(data)
        self._originals[index] = path
        self._count += 1

    def original_path(self, index: int) -> Path | None:
        return self._originals.get(index)

    @property
    def image_count(self) -> int:
        return self._count


def _child_environment(workspace: BatchWorkspace) -> dict[str, str]:
    env = {
        "PYTHONDONTWRITEBYTECODE": "1",    # do not write into the vendored tree
        "PYTHONPATH": str(HEADLESS_DIR),   # the screeninfo stand-in
        "PYTHONIOENCODING": "utf-8",
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(_matplotlib_cache()),
        "OPENCV_LOG_LEVEL": "ERROR",
    }
    # Only what a Python process needs to start and to find the same
    # installed packages as the server (HOME / USERPROFILE locate the
    # per-user site-packages); no display, no secrets.
    for key in ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "TMPDIR",
                "LANG", "LC_ALL", "VIRTUAL_ENV", "PYTHONUSERBASE"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _read_rows(directory: Path, pattern: str) -> list[dict[str, str]]:
    rows = []
    for path in sorted(directory.glob(pattern)):
        with open(path, newline="", encoding="utf-8-sig") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def _index_of(row: dict[str, str]) -> int | None:
    match = _FILE_ID.match((row.get("file_id") or "").strip())
    return int(match.group(1)) if match else None


# Run in a child process (never in the web application): which images can
# the image library actually decode? No user-supplied text is interpolated.
_DECODE_CHECK = (
    "import os, sys\n"
    "import cv2\n"
    "folder = sys.argv[1]\n"
    "for name in sorted(os.listdir(folder)):\n"
    "    if name.startswith('sheet_') and name.endswith(('.png', '.jpg')):\n"
    "        if cv2.imread(os.path.join(folder, name), cv2.IMREAD_GRAYSCALE) is None:\n"
    "            print(int(name[6:10]))\n"
)


def find_unreadable(workspace: BatchWorkspace) -> set[int]:
    """
    Indexes of images whose pixel data cannot be decoded.

    The upload check only reads headers. A file with a valid header but a
    damaged body would make OMRChecker itself fail for the whole batch, so
    these are found first and reported per file.
    """

    if not engine_available():
        raise OMRUnavailable("OMR processing is not installed on this server.")

    try:
        completed = subprocess.run(
            [sys.executable, "-c", _DECODE_CHECK, str(workspace.input_dir)],
            cwd=str(VENDOR_ROOT),
            env=_child_environment(workspace),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=config.OMR_TIMEOUT_BASE_SECONDS
            + config.OMR_TIMEOUT_PER_SHEET_SECONDS * workspace.image_count,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("OMR image check timed out")
        raise OMREngineError("OMR processing took too long and was stopped.") from None
    except OSError:
        logger.exception("OMR image check could not be started")
        raise OMREngineError("OMR processing could not be started.") from None

    if completed.returncode != 0:
        logger.error("OMR image check failed (exit %s)", completed.returncode)
        raise OMREngineError("OMR processing failed.")

    return {int(line) for line in completed.stdout.split() if line.isdigit()}


def run_recognition(workspace: BatchWorkspace) -> RecognitionRun:
    """Run OMRChecker on the workspace's images and read back the results."""

    if not engine_available():
        raise OMRUnavailable("OMR processing is not installed on this server.")

    if not ENTRY_POINT.is_file():
        raise OMRUnavailable("OMR processing is not available on this server.")

    timeout = (
        config.OMR_TIMEOUT_BASE_SECONDS
        + config.OMR_TIMEOUT_PER_SHEET_SECONDS * workspace.image_count
    )
    command = [
        sys.executable,
        str(ENTRY_POINT),
        "-i", str(workspace.input_dir),
        "-o", str(workspace.output_dir),
    ]

    # Taken immediately before the try/finally that always releases it.
    if not _slots.acquire(blocking=False):
        raise OMRBusy("OMR processing is busy. Please try again in a moment.")

    try:
        completed = subprocess.run(
            command,
            cwd=str(VENDOR_ROOT),
            env=_child_environment(workspace),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("OMR child process timed out after %s s", timeout)
        raise OMREngineError("OMR processing took too long and was stopped.") from None
    except OSError:
        logger.exception("OMR child process could not be started")
        raise OMREngineError("OMR processing could not be started.") from None
    finally:
        _slots.release()

    if completed.returncode != 0:
        # Log for the operator with our working folder's path hidden;
        # users only ever see the fixed message.
        tail = (completed.stderr or completed.stdout or "")[-1500:]
        logger.error(
            "OMR child process failed (exit %s): %s",
            completed.returncode,
            tail.replace(str(workspace.root), "<work>"),
        )
        raise OMREngineError("OMR processing failed.")

    run = RecognitionRun()
    out = workspace.output_dir

    if out is not None and out.is_dir():
        for row in _read_rows(out / "Results", "Results_*.csv"):
            index = _index_of(row)
            if index is not None:
                run.rows[index] = row
        for row in _read_rows(out / "Manual", "ErrorFiles.csv"):
            index = _index_of(row)
            if index is not None:
                run.errored.add(index)

        # Annotated images; multi-marked sheets may be filed in a subfolder.
        for folder in (out / "CheckedOMRs", out / "CheckedOMRs" / "_MULTI_"):
            if not folder.is_dir():
                continue
            for path in folder.iterdir():
                match = _FILE_ID.match(path.name)
                if match and path.is_file():
                    run.checked.setdefault(int(match.group(1)), path)

    return run
