"""
Local storage for the images of sheets awaiting review.

Layout, under config.OMR_STORAGE_DIR (inside the application data
directory, never the source tree):

    batches/<batch id>/sheets/<sheet id>.<png|jpg>          the upload
    batches/<batch id>/sheets/<sheet id>.checked.<png|jpg>  the aligned image
                                                            with the engine's
                                                            detections drawn on

Every file name is built here from integer ids and a fixed extension. The
uploader's filename is never used, so nothing a user sends can choose or
escape a path. Images are kept only while a batch is pending and are
removed once it is committed or discarded.
"""

import logging
import os
import shutil
from pathlib import Path

from .. import config

logger = logging.getLogger("coaching.omr")

ALLOWED_EXTENSIONS = (".png", ".jpg")


def _root() -> Path:
    return Path(config.OMR_STORAGE_DIR)


def batch_dir(batch_id: int) -> Path:
    return _root() / "batches" / str(int(batch_id))


def sheets_dir(batch_id: int) -> Path:
    return batch_dir(batch_id) / "sheets"


def image_path(batch_id: int, sheet_id: int, extension: str, checked: bool = False) -> Path:
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("unsupported image type")

    name = f"{int(sheet_id)}{'.checked' if checked else ''}{extension}"
    path = sheets_dir(batch_id) / name

    # Belt and braces: the result must lie inside the storage root.
    if not path.resolve().is_relative_to(_root().resolve()):
        raise ValueError("path outside storage")

    return path


def save_image(path: Path, data: bytes) -> None:
    """Write a file, creating private folders as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)

    for folder in (path.parent, path.parent.parent):
        try:
            os.chmod(folder, 0o700)      # no effect on Windows
        except OSError:
            pass

    path.write_bytes(data)

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def existing_image(batch_id: int, sheet_id: int, extension: str | None, checked: bool) -> Path | None:
    """The stored file, or None if there is none (never raises on bad input)."""
    if not extension:
        return None

    try:
        path = image_path(batch_id, sheet_id, extension, checked)
    except ValueError:
        return None

    return path if path.is_file() else None


def remove_batch_images(batch_id: int) -> bool:
    """
    Delete a batch's stored images. Returns True when nothing is left.

    A failure is logged (without paths in the message shown to users) and
    reported to the caller; it never raises, so database state is not
    affected by a cleanup problem.
    """

    folder = batch_dir(batch_id)

    if not folder.exists():
        return True

    try:
        shutil.rmtree(folder)
    except OSError:
        logger.exception("Could not remove stored OMR images for batch %s", batch_id)

    return not folder.exists()


def storage_bytes(batch_id: int) -> int:
    """Disk used by a batch's images (for measurement)."""
    folder = batch_dir(batch_id)
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) if folder.exists() else 0
