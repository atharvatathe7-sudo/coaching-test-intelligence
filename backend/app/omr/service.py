"""
OMR batch import for one test: recognise, normalise, validate, import.

    uploaded images
        -> checker.py          OMRChecker, in a child process
        -> normalization.py    our own sheet/answer model
        -> validation.py       roster, questions, duplicates, review states
        -> existing answer import and evaluation (services/importer.py)

OMR recognition never calculates marks. The only way recognised answers
reach the database is through the application's existing answer import,
which validates again, writes everything in one transaction and runs the
existing evaluation. This module never duplicates any of that.

Safe behaviour until a review screen exists (Stage 3):
  * any error blocks the whole batch; nothing is imported, no sheet is
    skipped
  * a batch that contains multi-marked, invalid or missing answers is
    reported as "review_required" and is NOT imported. Those answers are
    never converted into blanks, so an ambiguous mark cannot silently
    become "unattempted" in the permanent data.
  * with dry_run (the default) nothing is written at all.
"""

import csv
import io
import logging
import time
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from sqlalchemy.orm import Session

from .. import config
from ..database.models import Question, Student, Test, User
from ..services import importer
from .checker import BatchWorkspace, OMREngineError, find_unreadable, run_recognition
from .images import ImageRejected, inspect_image, safe_display_name
from .models import Issue, OMRSheet, RecognitionStatus
from .normalization import normalize_sheet
from .template import OMRTemplate, TemplateError, get_template
from .validation import (
    BatchValidation,
    check_template_covers_test,
    find_duplicate_answers,
    validate_sheets,
)

logger = logging.getLogger("coaching.omr")

REVIEW_MESSAGE = (
    "Review required: some answers are multi-marked, invalid or could not be "
    "read. Nothing was imported. Reviewing these answers is not available "
    "yet; fix the sheets and upload them again."
)


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


def answer_rows(sheets: list[OMRSheet]) -> list[tuple[str, int, str]]:
    """
    Final answer rows (roll, question, answer) for sheets that have no
    unresolved answers. Raises if a sheet still has one, or if a
    (roll, question) pair would appear twice, so ambiguity can never be
    imported by accident.
    """

    rows = []

    for sheet in sheets:
        for answer in sheet.answers:
            if answer.status is RecognitionStatus.RECOGNIZED:
                value = answer.normalized_answer
            elif answer.status is RecognitionStatus.BLANK:
                value = ""
            else:
                raise ValueError("an unresolved answer cannot be imported")
            rows.append((sheet.roll_number, answer.question_number, value))

    if find_duplicate_answers(rows):
        raise ValueError("duplicate roll number and question")

    return rows


def answers_csv(rows: list[tuple[str, int, str]]) -> bytes:
    """The rows in the format the existing answer import reads."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["roll_number", "question_number", "answer"])
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _sheet_summary(sheet: OMRSheet, state: str) -> dict:
    counts = {status.value: 0 for status in RecognitionStatus}
    for answer in sheet.answers:
        counts[answer.status.value] += 1
    return {
        "sheet": sheet.display_name,
        "roll_number": sheet.roll_number,
        "status": state,
        "answers": counts,
    }


def _response(
    *,
    status: str,
    committed: bool,
    template: OMRTemplate | None,
    errors: list[Issue],
    warnings: list[Issue],
    validation: BatchValidation | None = None,
    sheets: list[OMRSheet] | None = None,
    import_summary: dict | None = None,
    message: str | None = None,
    seconds: float = 0.0,
    submitted: int = 0,
) -> dict:
    counts = validation.counts if validation else {
        "submitted": submitted, "processed": 0, "accepted": 0, "unreadable": 0,
        "duplicate": 0, "unknown_student": 0, "recognized": 0, "blank": 0,
        "multi_mark": 0, "invalid": 0, "review_required": 0,
    }
    states = validation.sheet_states if validation else {}

    return {
        "status": status,                      # accepted | review_required | rejected | imported
        "committed": committed,
        "message": message,
        "template": (
            {"id": template.id, "version": template.version} if template else None
        ),
        "counts": counts,
        "sheets": [
            _sheet_summary(s, states.get(s.index, "rejected"))
            for s in (sheets or [])
        ],
        "review_items": validation.review_items if validation else [],
        "review_items_total": validation.review_items_total if validation else 0,
        "errors": [i.as_dict() for i in errors],
        "warnings": [i.as_dict() for i in warnings],
        "import": import_summary,
        "processing_seconds": round(seconds, 2),
    }


def process_omr_batch(
    db: Session,
    test: Test,
    uploads: list[Upload],
    *,
    template_id: str | None = None,
    replace: bool = False,
    dry_run: bool = True,
    actor: User | None = None,
) -> dict:
    """
    Run a batch for `test` (already resolved for the signed-in user's
    institute by the caller). Returns our own response schema. Raises
    OMREngineError (with a safe message) if the recogniser cannot run.
    """

    started = time.monotonic()

    def finish(**kwargs):
        return _response(
            seconds=time.monotonic() - started, submitted=len(uploads), **kwargs
        )

    try:
        template = get_template(template_id)
    except TemplateError:
        return finish(
            status="rejected", committed=False, template=None,
            errors=[Issue("unknown_template", "The sheet template is not recognised.")],
            warnings=[],
        )

    if not uploads:
        return finish(
            status="rejected", committed=False, template=template,
            errors=[Issue("no_files", "No OMR images were provided.")], warnings=[],
        )

    if len(uploads) > config.MAX_OMR_FILES:
        return finish(
            status="rejected", committed=False, template=template,
            errors=[Issue("too_many_files",
                          f"At most {config.MAX_OMR_FILES} images can be processed at once.")],
            warnings=[],
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
        return finish(
            status="rejected", committed=False, template=template,
            errors=errors, warnings=warnings,
        )

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
                    Issue("invalid_image", "The image could not be read.",
                          sheet=names[index])
                )

        if upload_errors:
            # Nothing is processed when any file is unacceptable.
            return finish(
                status="rejected", committed=False, template=template,
                errors=upload_errors, warnings=warnings,
            )

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

    validation = validate_sheets(sheets, template, roster_rolls)
    errors = list(validation.errors)
    warnings += validation.warnings

    if errors:
        return finish(
            status="rejected", committed=False, template=template, errors=errors,
            warnings=warnings, validation=validation, sheets=sheets,
        )

    if validation.status == "review_required":
        return finish(
            status="review_required", committed=False, template=template,
            errors=[], warnings=warnings, validation=validation, sheets=sheets,
            message=REVIEW_MESSAGE,
        )

    # Everything is unambiguous: hand it to the existing answer import,
    # which validates again and (unless dry_run) commits atomically and
    # evaluates.
    try:
        raw = answers_csv(answer_rows(sheets))
    except ValueError:
        logger.error("OMR answer rows were inconsistent after validation")
        return finish(
            status="rejected", committed=False, template=template,
            errors=[Issue("internal_inconsistency",
                          "The recognised answers were inconsistent and were not imported.")],
            warnings=warnings, validation=validation, sheets=sheets,
        )

    report = importer.import_answers(
        db, test, raw, replace=replace, dry_run=dry_run,
        requested_test_id=test.id, actor=actor,
    )

    warnings += [Issue("import_warning", w["message"]) for w in report["warnings"]]

    if report["status"] == "invalid":
        errors = [Issue("import_rejected", e["message"]) for e in report["errors"]]
        return finish(
            status="rejected", committed=False, template=template, errors=errors,
            warnings=warnings, validation=validation, sheets=sheets,
        )

    committed = report["status"] == "imported"

    return finish(
        status="imported" if committed else "accepted",
        committed=committed, template=template, errors=[], warnings=warnings,
        validation=validation, sheets=sheets, import_summary=report["summary"],
    )
