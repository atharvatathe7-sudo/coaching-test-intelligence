"""
OMR upload: recognise a batch of sheet images and store it for review.

    uploaded images
        -> checker.py          OMRChecker, in a child process
        -> normalization.py    our own sheet/answer model
        -> a pending batch     rows + images kept locally (batches.py)
        -> review              a person settles anything doubtful
        -> batches.commit_batch  the existing answer import and evaluation

Reading sheets never changes any answer or result. The upload creates a
pending batch only; clear answers are accepted automatically, doubtful
ones (multi-mark, invalid, missing) wait for review, and the batch is
committed as a whole, atomically, once every item is settled.

OMR recognition never calculates marks.
"""

import logging
import time
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from sqlalchemy.orm import Session

from .. import config
from ..database.models import (
    OMRAnswer,
    OMRBatch,
    OMRSheet,
    Question,
    Student,
    Test,
    User,
)
from ..services import audit
from . import batches, storage
from .checker import (
    BatchWorkspace,
    OMREngineError,
    find_unreadable,
    run_recognition,
)
from .images import ImageRejected, inspect_image, safe_display_name
from .models import Issue, NEEDS_REVIEW, OMRSheet as RecognisedSheet, RecognitionStatus
from .normalization import normalize_sheet
from .rows import answer_rows, answers_csv  # noqa: F401  (re-exported)
from .template import TemplateError, get_template
from .validation import check_template_covers_test, validate_sheets

logger = logging.getLogger("coaching.omr")

_REASONS = {
    RecognitionStatus.MULTI_MARK: "MULTI_MARK",
    RecognitionStatus.INVALID: "INVALID_ANSWER",
    RecognitionStatus.REVIEW_REQUIRED: "MISSING_ANSWER_FIELD",
}


class Upload(Protocol):
    """What the service needs from an uploaded file."""

    filename: str | None

    def read(self, size: int = -1) -> bytes: ...


@dataclass
class UploadedFile:
    """An upload: the client's filename (untrusted) and a binary file object."""

    filename: str | None
    file: BinaryIO

    def read(self, size: int = -1) -> bytes:
        return self.file.read(size)


def _rejected(errors, warnings=None, template=None, seconds=0.0) -> dict:
    """The upload was refused before any batch was created."""
    return {
        "status": "rejected",
        "batch": None,
        "template": (
            {"id": template.id, "version": template.version} if template else None
        ),
        "errors": [e.as_dict() for e in errors],
        "warnings": [w.as_dict() for w in (warnings or [])],
        "processing_seconds": round(seconds, 2),
    }


def _store_sheet(
    db: Session,
    batch: OMRBatch,
    recognised: RecognisedSheet,
    workspace: BatchWorkspace,
    checked_path,
) -> None:
    """Write one sheet's rows and image files."""

    original = workspace.original_path(recognised.index)
    extension = original.suffix if original else None

    sheet = OMRSheet(
        batch_id=batch.id,
        sheet_index=recognised.index,
        original_filename=recognised.display_name[:200],
        roll_raw=(recognised.roll_raw or None) and recognised.roll_raw[:100],
        roll_number=recognised.roll_number,
        roll_source="omr",
        status="PENDING",
        unreadable=recognised.unreadable,
        image_ext=extension,
    )
    db.add(sheet)
    db.flush()                       # the id names the image files

    if original is not None:
        storage.save_image(
            storage.image_path(batch.id, sheet.id, extension),
            original.read_bytes(),
        )

    if checked_path is not None and checked_path.suffix == extension:
        storage.save_image(
            storage.image_path(batch.id, sheet.id, extension, checked=True),
            checked_path.read_bytes(),
        )
        sheet.has_checked_image = True

    for answer in recognised.answers:
        clear = answer.status not in NEEDS_REVIEW
        db.add(
            OMRAnswer(
                sheet_id=sheet.id,
                question_number=answer.question_number,
                raw_value=None if answer.raw_value is None else answer.raw_value[:20],
                recognized_answer=answer.normalized_answer,
                recognition_status=answer.status.value,
                review_reason=None if clear else _REASONS[answer.status],
                # A clear answer is settled; a doubtful one waits for a person.
                resolved=clear,
                final_answer=answer.normalized_answer if clear else None,
            )
        )


def _mark_failed(db: Session, batch_id: int, code: str) -> None:
    db.rollback()
    batch = db.get(OMRBatch, batch_id)
    if batch is not None and batch.status == "PROCESSING":
        batches.transition(batch, "FAILED")
        batch.failure_code = code
        db.commit()
    storage.remove_batch_images(batch_id)


def create_pending_batch(
    db: Session,
    test: Test,
    uploads: list[Upload],
    *,
    template_id: str | None = None,
    actor: User,
) -> dict:
    """
    Read a batch of sheet images for `test` (already resolved for the
    signed-in user's institute) and store it for review.

    Returns our response dict. Uploads that are not acceptable are
    refused before anything is stored. Raises OMREngineError (with a safe
    message) if the recogniser cannot run; the batch is then left FAILED.
    """

    started = time.monotonic()

    def elapsed():
        return time.monotonic() - started

    try:
        template = get_template(template_id)
    except TemplateError:
        return _rejected(
            [Issue("unknown_template", "The sheet template is not recognised.")]
        )

    if not uploads:
        return _rejected([Issue("no_files", "No OMR images were provided.")], template=template)

    if len(uploads) > config.MAX_OMR_FILES:
        return _rejected(
            [Issue("too_many_files",
                   f"At most {config.MAX_OMR_FILES} images can be processed at once.")],
            template=template,
        )

    test_questions = {
        q.question_number
        for q in db.query(Question).filter(Question.test_id == test.id)
    }
    roster_rolls = {
        s.roll_number.strip()
        for s in db.query(Student).filter(Student.batch_id == test.batch_id)
    }

    errors, warnings = check_template_covers_test(template, test_questions)
    if errors:
        return _rejected(errors, warnings, template)

    with BatchWorkspace(template) as workspace:
        names: dict[int, str] = {}
        upload_errors: list[Issue] = []

        for index, upload in enumerate(uploads, start=1):
            names[index] = safe_display_name(getattr(upload, "filename", None), index)

            try:
                # One byte over the limit is enough to know it is too large.
                data = upload.read(config.MAX_OMR_IMAGE_BYTES + 1)
                info = inspect_image(data, getattr(upload, "filename", None))
            except ImageRejected as reason:
                upload_errors.append(Issue("invalid_image", str(reason), sheet=names[index]))
                continue

            workspace.add_image(index, data, info)
            del data

        if not upload_errors:
            # Headers were fine; now find files whose pixels cannot be read.
            for index in sorted(find_unreadable(workspace)):
                upload_errors.append(
                    Issue("invalid_image", "The image could not be read.", sheet=names[index])
                )

        if upload_errors:
            # Nothing is stored when any file is unacceptable.
            return _rejected(upload_errors, warnings, template, elapsed())

        batch = OMRBatch(
            institute_id=actor.institute_id,
            test_id=test.id,
            created_by_user_id=actor.id,
            status="PROCESSING",
            template_id=template.id,
            template_version=template.version,
        )
        db.add(batch)
        db.commit()
        batch_id = batch.id

        try:
            recognition = run_recognition(workspace)

            sheets = [
                normalize_sheet(
                    index,
                    names[index],
                    None if index in recognition.errored else recognition.rows.get(index),
                    template,
                    test_questions,
                )
                for index in sorted(names)
            ]

            # Only its warnings are used here (fields that were ignored);
            # what needs review is derived from the stored rows.
            warnings += validate_sheets(sheets, template, roster_rolls).warnings

            for recognised in sheets:
                _store_sheet(
                    db, batch, recognised, workspace,
                    recognition.checked.get(recognised.index),
                )

            db.flush()
            batches.refresh_batch(db, batch, test)
            audit.record(
                db, actor, "omr.batch_create", "omr_batch", batch_id,
                {"test_id": test.id, "sheets": len(sheets), "template": template.id},
            )
            db.commit()
        except OMREngineError:
            _mark_failed(db, batch_id, "engine")
            raise
        except Exception:
            logger.exception("OMR batch creation failed")
            _mark_failed(db, batch_id, "storage")
            raise OMREngineError("OMR processing failed.") from None

    db.refresh(batch)

    return {
        "status": batch.status,
        "batch": batches.batch_summary(db, batch, test),
        "template": {"id": template.id, "version": template.version},
        "errors": [],
        "warnings": [w.as_dict() for w in warnings],
        "processing_seconds": round(elapsed(), 2),
    }
