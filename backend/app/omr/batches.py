"""
OMR review batches: lifecycle, review decisions, atomic commit, discard.

A batch holds what the recogniser read until a person has settled every
doubtful answer. Nothing here is a final answer: StudentAnswer and
TestResult are only written by commit_batch, in a single transaction that
also marks the batch COMMITTED.

States and the moves allowed between them:

    PROCESSING      -> REVIEW_REQUIRED | READY_TO_COMMIT | FAILED
    REVIEW_REQUIRED -> READY_TO_COMMIT | DISCARDED
    READY_TO_COMMIT -> REVIEW_REQUIRED | COMMITTED | DISCARDED
    FAILED          -> DISCARDED
    COMMITTED, DISCARDED: final

READY_TO_COMMIT may go back to REVIEW_REQUIRED because a teacher's change
(for example assigning a roll number that another sheet already has) can
re-open a problem.

The recognition columns of an answer are written once and never changed;
a teacher's decision is stored beside them, so "read AB, resolved as A"
stays on record.
"""

import logging
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import update
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
from ..services import audit, importer
from . import storage
from .models import Issue
from .rows import answers_csv
from .template import TemplateError, get_template

logger = logging.getLogger("coaching.omr")

ALLOWED_TRANSITIONS = {
    "PROCESSING": {"REVIEW_REQUIRED", "READY_TO_COMMIT", "FAILED"},
    "REVIEW_REQUIRED": {"READY_TO_COMMIT", "DISCARDED"},
    "READY_TO_COMMIT": {"REVIEW_REQUIRED", "COMMITTED", "DISCARDED"},
    "FAILED": {"DISCARDED"},
    "COMMITTED": set(),
    "DISCARDED": set(),
}

# Batches in these states can still be reviewed.
REVIEWABLE = ("REVIEW_REQUIRED", "READY_TO_COMMIT")

CHOICES = ["A", "B", "C", "D", "BLANK"]

# Sheet-level problems. Only the roll problems can be fixed by a person
# (by choosing the right student); an unreadable sheet cannot.
UNREADABLE_SHEET = "UNREADABLE_SHEET"
MISSING_ROLL = "MISSING_ROLL"
MALFORMED_ROLL = "MALFORMED_ROLL"
UNKNOWN_ROLL = "UNKNOWN_ROLL"
DUPLICATE_ROLL = "DUPLICATE_ROLL"

_SHEET_MESSAGES = {
    UNREADABLE_SHEET: "The sheet could not be read. Discard this batch and scan it again.",
    MISSING_ROLL: "No roll number was read from the sheet.",
    MALFORMED_ROLL: "The roll number read from the sheet is not valid.",
    UNKNOWN_ROLL: "The roll number is not in this test's batch roster.",
    DUPLICATE_ROLL: "Another sheet in this batch has the same roll number.",
}


class BatchError(Exception):
    """Base for errors the API turns into a clear response."""


class BatchStateError(BatchError):
    """The batch is not in a state that allows this (HTTP 409)."""


class ConflictError(BatchError):
    """Someone else changed the item first (HTTP 409)."""


class InvalidDecision(BatchError):
    """The request itself is not acceptable (HTTP 422)."""


class CommitRefused(BatchError):
    """Commit was not allowed; `problems` say why (HTTP 409)."""

    def __init__(self, problems: list[dict]):
        super().__init__("commit refused")
        self.problems = problems


def _now() -> datetime:
    return datetime.utcnow()


def transition(batch: OMRBatch, new_status: str) -> None:
    """Move a batch to a new state, or raise if that move is not allowed."""
    if new_status == batch.status:
        return

    if new_status not in ALLOWED_TRANSITIONS.get(batch.status, set()):
        raise BatchStateError(
            f"A batch that is {batch.status.lower().replace('_', ' ')} "
            f"cannot become {new_status.lower().replace('_', ' ')}."
        )

    batch.status = new_status
    batch.updated_at = _now()


def expire_if_stale(db: Session, batch: OMRBatch) -> None:
    """A batch stuck PROCESSING was interrupted: show it as FAILED."""
    if batch.status != "PROCESSING":
        return

    age = _now() - batch.updated_at
    if age > timedelta(seconds=config.OMR_PROCESSING_STALE_SECONDS):
        transition(batch, "FAILED")
        batch.failure_code = "interrupted"
        db.commit()


# --------------------------------------------------------------------
# Reading the current state
# --------------------------------------------------------------------

def _roster_rolls(db: Session, test: Test) -> set[str]:
    return {
        s.roll_number.strip()
        for s in db.query(Student).filter(Student.batch_id == test.batch_id)
    }


def sheet_issues(db: Session, batch: OMRBatch, test: Test) -> dict[int, list[str]]:
    """
    The problems each sheet has right now, worked out from the current
    roll numbers and roster (so a teacher's change is taken into account).
    """

    sheets = db.query(OMRSheet).filter(OMRSheet.batch_id == batch.id).all()
    roster = _roster_rolls(db, test)
    seen = Counter(s.roll_number for s in sheets if s.roll_number and not s.unreadable)
    issues: dict[int, list[str]] = {}

    for sheet in sheets:
        found = []

        if sheet.unreadable:
            found.append(UNREADABLE_SHEET)
        elif not sheet.roll_number:
            blank = not (sheet.roll_raw or "").strip()
            found.append(MISSING_ROLL if blank else MALFORMED_ROLL)
        elif sheet.roll_number not in roster:
            found.append(UNKNOWN_ROLL)
        elif seen[sheet.roll_number] > 1:
            found.append(DUPLICATE_ROLL)

        issues[sheet.id] = found

    return issues


def refresh_batch(db: Session, batch: OMRBatch, test: Test) -> None:
    """
    Recompute sheet statuses and the batch's counts and state from the
    stored rows. Does not commit.
    """

    issues = sheet_issues(db, batch, test)
    sheets = (
        db.query(OMRSheet).filter(OMRSheet.batch_id == batch.id)
        .order_by(OMRSheet.sheet_index).all()
    )
    open_by_sheet = Counter(
        sheet_id
        for (sheet_id,) in db.query(OMRAnswer.sheet_id)
        .join(OMRSheet, OMRSheet.id == OMRAnswer.sheet_id)
        .filter(OMRSheet.batch_id == batch.id, OMRAnswer.resolved.is_(False))
    )
    reviewed_sheets = {
        sheet_id
        for (sheet_id,) in db.query(OMRAnswer.sheet_id)
        .join(OMRSheet, OMRSheet.id == OMRAnswer.sheet_id)
        .filter(OMRSheet.batch_id == batch.id, OMRAnswer.reviewed.is_(True))
    }

    accepted = open_items = errors = 0

    for sheet in sheets:
        found = issues[sheet.id]
        open_answers = open_by_sheet[sheet.id]

        if sheet.unreadable:
            sheet.status = "INVALID"
            errors += 1
        elif found or open_answers:
            sheet.status = "REVIEW_REQUIRED"
            open_items += open_answers + len(found)
        elif sheet.id in reviewed_sheets or sheet.roll_source == "teacher":
            sheet.status = "REVIEWED"
            accepted += 1
        else:
            sheet.status = "ACCEPTED"
            accepted += 1

    batch.total_sheets = len(sheets)
    batch.accepted_sheets = accepted
    batch.review_required_count = open_items
    batch.error_count = errors
    batch.updated_at = _now()

    if batch.status in REVIEWABLE or batch.status == "PROCESSING":
        transition(batch, "REVIEW_REQUIRED" if (open_items or errors) else "READY_TO_COMMIT")


def recognition_counts(db: Session, batch: OMRBatch) -> dict:
    """How the recogniser classified every answer (from the stored rows)."""
    counts = Counter(
        status
        for (status,) in db.query(OMRAnswer.recognition_status)
        .join(OMRSheet, OMRSheet.id == OMRAnswer.sheet_id)
        .filter(OMRSheet.batch_id == batch.id)
    )
    return {
        key: counts.get(key, 0)
        for key in ("recognized", "blank", "multi_mark", "invalid", "review_required")
    }


def batch_summary(db: Session, batch: OMRBatch, test: Test) -> dict:
    return {
        "id": batch.id,
        "test_id": batch.test_id,
        "test_name": test.name,
        "test_date": test.test_date.isoformat(),
        "status": batch.status,
        "created_at": batch.created_at.isoformat(),
        "updated_at": batch.updated_at.isoformat(),
        "template": {"id": batch.template_id, "version": batch.template_version},
        "total_sheets": batch.total_sheets,
        "accepted_sheets": batch.accepted_sheets,
        "review_required_count": batch.review_required_count,
        "error_count": batch.error_count,
        "recognition": recognition_counts(db, batch),
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else None,
        "discarded_at": batch.discarded_at.isoformat() if batch.discarded_at else None,
        "images_removed": batch.images_removed_at is not None,
        "failure_code": batch.failure_code,
    }


def _image_urls(sheet: OMRSheet, batch: OMRBatch) -> dict:
    if batch.images_removed_at is not None or sheet.image_ext is None:
        return {"original": None, "checked": None}
    base = f"/api/omr/sheets/{sheet.id}/image"
    return {
        "original": f"{base}?view=original",
        "checked": f"{base}?view=checked" if sheet.has_checked_image else None,
    }


def review_items(db: Session, batch: OMRBatch, test: Test) -> list[dict]:
    """Everything a person has to look at, with what the engine detected."""

    try:
        template = get_template(batch.template_id)
    except TemplateError:
        template = None

    sheets = {
        s.id: s for s in db.query(OMRSheet).filter(OMRSheet.batch_id == batch.id)
    }
    issues = sheet_issues(db, batch, test)
    reviewers = {u.id: u.name for u in db.query(User).filter(User.institute_id == batch.institute_id)}
    items: list[dict] = []

    for sheet in sorted(sheets.values(), key=lambda s: s.sheet_index):
        for code in issues[sheet.id]:
            items.append({
                "id": sheet.id,
                "kind": "sheet",
                "reason": code,
                "message": _SHEET_MESSAGES[code],
                "resolvable": code != UNREADABLE_SHEET,
                "resolved": False,
                "sheet_id": sheet.id,
                "sheet_index": sheet.sheet_index,
                "filename": sheet.original_filename,
                "detected": {"roll_raw": sheet.roll_raw},
                "roll_number": sheet.roll_number,
                "roll_source": sheet.roll_source,
                "revision": sheet.revision,
                "images": _image_urls(sheet, batch),
            })

    answers = (
        db.query(OMRAnswer)
        .join(OMRSheet, OMRSheet.id == OMRAnswer.sheet_id)
        .filter(OMRSheet.batch_id == batch.id, OMRAnswer.review_reason.is_not(None))
        .order_by(OMRSheet.sheet_index, OMRAnswer.question_number)
    )

    for answer in answers:
        sheet = sheets[answer.sheet_id]
        crop = (
            template.question_region(answer.question_number)
            if template and sheet.has_checked_image
            else None
        )
        final = None
        if answer.resolved:
            final = answer.final_answer or "BLANK"

        items.append({
            "id": answer.id,
            "kind": "answer",
            "reason": answer.review_reason,
            "resolved": answer.resolved,
            "sheet_id": sheet.id,
            "sheet_index": sheet.sheet_index,
            "filename": sheet.original_filename,
            "roll_number": sheet.roll_number,
            "question_number": answer.question_number,
            # What the OMR engine detected. Never changed by a review.
            "detected": {
                "raw_value": answer.raw_value,
                "recognition_status": answer.recognition_status,
                "letters": list(answer.raw_value) if answer.recognition_status == "multi_mark" and answer.raw_value else [],
            },
            "choices": CHOICES,
            # What the reviewer chose.
            "final_answer": final,
            "reviewed_at": answer.reviewed_at.isoformat() if answer.reviewed_at else None,
            "reviewed_by": reviewers.get(answer.reviewed_by_user_id),
            "revision": answer.revision,
            "crop": crop,
            "images": _image_urls(sheet, batch),
        })

    return items


# --------------------------------------------------------------------
# Review decisions
# --------------------------------------------------------------------

def _require_reviewable(batch: OMRBatch) -> None:
    if batch.status not in REVIEWABLE:
        raise BatchStateError(
            f"This batch is {batch.status.lower().replace('_', ' ')} and can no longer be reviewed."
        )


def resolve_answer(
    db: Session,
    batch: OMRBatch,
    test: Test,
    answer: OMRAnswer,
    actor: User,
    final_answer: str,
    revision: int,
) -> None:
    """
    Record a reviewer's decision for one doubtful answer.

    `revision` is the one the reviewer saw. If someone else changed the
    item in the meantime the update does not apply and ConflictError is
    raised, so two reviewers cannot silently overwrite each other.
    """

    _require_reviewable(batch)

    if answer.review_reason is None:
        raise InvalidDecision("This answer does not need review.")

    if final_answer not in CHOICES:
        raise InvalidDecision("Choose A, B, C, D or blank.")

    # One atomic, conditional UPDATE: it only matches the revision seen.
    applied = db.execute(
        update(OMRAnswer)
        .where(OMRAnswer.id == answer.id, OMRAnswer.revision == revision)
        .values(
            resolved=True,
            final_answer=None if final_answer == "BLANK" else final_answer,
            reviewed=True,
            reviewed_at=_now(),
            reviewed_by_user_id=actor.id,
            revision=revision + 1,
        )
    )

    if applied.rowcount != 1:
        db.rollback()
        raise ConflictError("This answer was changed by someone else. Reload to see the latest.")

    db.expire(answer)
    sheet = db.get(OMRSheet, answer.sheet_id)
    sheet.reviewed_at = _now()
    sheet.reviewed_by_user_id = actor.id

    audit.record(
        db, actor, "omr.review", "omr_batch", batch.id,
        {"kind": "answer", "item_id": answer.id, "reason": answer.review_reason},
    )
    db.flush()
    refresh_batch(db, batch, test)
    db.commit()


def assign_roll(
    db: Session,
    batch: OMRBatch,
    test: Test,
    sheet: OMRSheet,
    actor: User,
    roll_number: str,
    revision: int,
) -> None:
    """
    A reviewer says which student a sheet belongs to. The roll must be
    exactly one in the test's roster: nothing is guessed or created.
    """

    _require_reviewable(batch)

    if sheet.unreadable:
        raise InvalidDecision("An unreadable sheet cannot be assigned. Scan it again.")

    roll = roll_number.strip()

    if roll not in _roster_rolls(db, test):
        raise InvalidDecision("That roll number is not in this test's batch roster.")

    applied = db.execute(
        update(OMRSheet)
        .where(OMRSheet.id == sheet.id, OMRSheet.revision == revision)
        .values(
            roll_number=roll,
            roll_source="teacher",
            reviewed_at=_now(),
            reviewed_by_user_id=actor.id,
            revision=revision + 1,
        )
    )

    if applied.rowcount != 1:
        db.rollback()
        raise ConflictError("This sheet was changed by someone else. Reload to see the latest.")

    db.expire(sheet)
    audit.record(
        db, actor, "omr.review", "omr_batch", batch.id,
        {"kind": "roll", "item_id": sheet.id, "reason": "ROLL_ASSIGNED"},
    )
    db.flush()
    refresh_batch(db, batch, test)
    db.commit()


# --------------------------------------------------------------------
# Commit
# --------------------------------------------------------------------

def _problem(code: str, message: str, **where) -> dict:
    return Issue(code, message, **where).as_dict()


def commit_problems(db: Session, batch: OMRBatch, test: Test) -> list[dict]:
    """
    Check the whole batch against the test as it is now. Returns the
    reasons commit must be refused; empty means it may go ahead.
    """

    problems: list[dict] = []

    try:
        template = get_template(batch.template_id)
    except TemplateError:
        return [_problem("template_missing", "The sheet template for this batch is no longer available.")]

    if template.version != batch.template_version:
        problems.append(_problem("template_changed", "The sheet template changed after this batch was read."))

    test_questions = {
        q.question_number for q in db.query(Question).filter(Question.test_id == test.id)
    }
    if not test_questions:
        problems.append(_problem("test_has_no_questions", "This test has no questions."))

    sheets = db.query(OMRSheet).filter(OMRSheet.batch_id == batch.id).order_by(OMRSheet.sheet_index).all()
    if not sheets:
        problems.append(_problem("no_sheets", "This batch has no sheets."))

    for sheet_id, codes in sheet_issues(db, batch, test).items():
        sheet = next(s for s in sheets if s.id == sheet_id)
        for code in codes:
            problems.append(_problem(code.lower(), _SHEET_MESSAGES[code], sheet=sheet.original_filename))

    for sheet in sheets:
        if sheet.unreadable:
            continue

        answers = db.query(OMRAnswer).filter(OMRAnswer.sheet_id == sheet.id).all()
        questions = [a.question_number for a in answers]

        if len(questions) != len(set(questions)):
            problems.append(_problem("duplicate_question", "A question appears twice on a sheet.", sheet=sheet.original_filename))

        if set(questions) != test_questions:
            problems.append(_problem(
                "questions_changed",
                "The sheet's questions no longer match the test's questions.",
                sheet=sheet.original_filename,
            ))

        for answer in answers:
            if not answer.resolved:
                problems.append(_problem(
                    "unresolved_answer", "An answer still needs review.",
                    sheet=sheet.original_filename, question_number=answer.question_number,
                ))
            elif answer.final_answer not in (None, "A", "B", "C", "D"):
                problems.append(_problem(
                    "invalid_final_answer", "An answer is not A, B, C, D or blank.",
                    sheet=sheet.original_filename, question_number=answer.question_number,
                ))

    return problems


def commit_batch(
    db: Session,
    batch: OMRBatch,
    test: Test,
    actor: User,
    replace: bool = False,
) -> dict:
    """
    Turn a fully reviewed batch into real answers and results.

    Everything happens in one transaction: the check, the answers, the
    evaluation, the audit entries and the batch's COMMITTED state are
    committed together or not at all. If anything fails the batch stays
    exactly as it was and can be corrected.

    Existing answers are only replaced when `replace` is true, through the
    same import code (and the same safety backup) as a CSV import.
    """

    if batch.status == "COMMITTED":
        raise BatchStateError("This batch has already been committed.")

    if batch.status == "DISCARDED":
        raise BatchStateError("This batch was discarded.")

    if batch.status != "READY_TO_COMMIT":
        raise CommitRefused([_problem(
            "not_ready", "The batch still has answers or sheets that need review.",
        )] + commit_problems(db, batch, test))

    problems = commit_problems(db, batch, test)
    if problems:
        raise CommitRefused(problems)

    rows = []
    for sheet in db.query(OMRSheet).filter(OMRSheet.batch_id == batch.id).order_by(OMRSheet.sheet_index):
        for answer in (
            db.query(OMRAnswer).filter(OMRAnswer.sheet_id == sheet.id).order_by(OMRAnswer.question_number)
        ):
            rows.append((sheet.roll_number, answer.question_number, answer.final_answer or ""))

    raw = answers_csv(rows)
    batch_id = batch.id

    try:
        # Claim the batch first: the first write takes the database write
        # lock, so a second simultaneous commit waits and then finds the
        # batch already committed.
        claimed = db.execute(
            update(OMRBatch)
            .where(OMRBatch.id == batch_id, OMRBatch.status == "READY_TO_COMMIT")
            .values(updated_at=_now())
        )
        if claimed.rowcount != 1:
            db.rollback()
            raise BatchStateError("This batch was changed by someone else. Reload and try again.")

        report = importer.import_answers(
            db, test, raw, replace=replace, dry_run=False,
            requested_test_id=test.id, actor=actor,
            commit=False, source="omr", audit_extra={"omr_batch_id": batch_id},
        )

        if report["status"] == "invalid":
            db.rollback()
            raise CommitRefused([
                _problem("import_rejected", e["message"]) for e in report["errors"]
            ])

        db.expire(batch)
        now = _now()
        transition(batch, "COMMITTED")
        batch.committed_at = now
        batch.committed_by_user_id = actor.id
        db.query(OMRSheet).filter(OMRSheet.batch_id == batch_id).update(
            {"status": "COMMITTED"}, synchronize_session=False
        )
        audit.record(
            db, actor, "omr.batch_commit", "omr_batch", batch_id,
            {
                "test_id": test.id,
                "sheets": batch.total_sheets,
                "replaced": bool(replace),
                "students_evaluated": report["summary"].get("students_evaluated"),
            },
        )
        db.commit()
    except BatchError:
        raise
    except Exception:
        db.rollback()
        logger.exception("OMR batch commit failed")
        raise CommitRefused([
            _problem("commit_failed", "The batch could not be committed. Nothing was changed.")
        ]) from None

    # Only now that the database is safely committed are the images
    # removed. A cleanup failure never affects the committed data.
    cleaned = _remove_images(db, batch_id)

    return {
        "students_evaluated": report["summary"].get("students_evaluated"),
        "images_removed": cleaned,
    }


def _remove_images(db: Session, batch_id: int) -> bool:
    if not storage.remove_batch_images(batch_id):
        return False

    try:
        db.query(OMRBatch).filter(OMRBatch.id == batch_id).update(
            {"images_removed_at": _now()}, synchronize_session=False
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not record OMR image removal")

    return True


# --------------------------------------------------------------------
# Discard
# --------------------------------------------------------------------

def discard_batch(db: Session, batch: OMRBatch, actor: User) -> dict:
    """
    Throw away a pending batch: its rows and images. Existing answers and
    results are not touched. Repeating it is harmless (it just retries any
    image cleanup that failed before).
    """

    batch_id = batch.id

    if batch.status == "DISCARDED":
        cleaned = batch.images_removed_at is not None or _remove_images(db, batch_id)
        return {"already_discarded": True, "images_removed": cleaned}

    if batch.status == "COMMITTED":
        raise BatchStateError("A committed batch cannot be discarded.")

    try:
        expire_if_stale(db, batch)
        transition(batch, "DISCARDED")
        sheet_ids = [
            sid for (sid,) in db.query(OMRSheet.id).filter(OMRSheet.batch_id == batch_id)
        ]
        if sheet_ids:
            db.query(OMRAnswer).filter(OMRAnswer.sheet_id.in_(sheet_ids)).delete(
                synchronize_session=False
            )
            db.query(OMRSheet).filter(OMRSheet.batch_id == batch_id).delete(
                synchronize_session=False
            )
        batch.discarded_at = _now()
        batch.discarded_by_user_id = actor.id
        audit.record(
            db, actor, "omr.batch_discard", "omr_batch", batch_id,
            {"test_id": batch.test_id, "sheets": len(sheet_ids)},
        )
        db.commit()
    except BatchError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("OMR batch discard failed")
        raise

    return {"already_discarded": False, "images_removed": _remove_images(db, batch_id)}
