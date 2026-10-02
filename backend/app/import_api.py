from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from .database.connection import get_db
from .database.models import User
from .security import access
from .security.dependencies import require_admin
from .services import importer

# Imports are admin-only.
router = APIRouter(
    prefix="/api/imports",
    dependencies=[Depends(require_admin)],
)

# All import endpoints return the same report:
#   {"status": "valid" | "invalid" | "imported", "errors": [...],
#    "warnings": [...], "summary": {...}}
# Validation problems are reported in the body (HTTP 200); nothing is
# written unless status is "imported".


@router.post("/roster")
async def import_roster(
    batch_id: int = Form(...),
    dry_run: bool = Form(True),
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # Another institute's batch is reported exactly like a missing one.
    return importer.import_roster(
        db,
        access.find_batch(db, user, batch_id),
        await file.read(),
        dry_run=dry_run,
        requested_batch_id=batch_id,
        actor=user,
    )


@router.post("/test-setup")
async def import_test_setup(
    batch_id: int = Form(...),
    test_name: str = Form(""),
    subject: str = Form(""),
    test_date: str = Form(""),
    marks_correct: str = Form("4"),
    marks_wrong: str = Form("-1"),
    marks_blank: str = Form("0"),
    dry_run: bool = Form(True),
    confirm_new_chapters_topics: bool = Form(False),
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return importer.import_test_setup(
        db,
        batch=access.find_batch(db, user, batch_id),
        requested_batch_id=batch_id,
        test_name=test_name,
        subject=subject,
        test_date=test_date,
        marks_correct=marks_correct,
        marks_wrong=marks_wrong,
        marks_blank=marks_blank,
        raw=await file.read(),
        dry_run=dry_run,
        confirm_new_chapters_topics=confirm_new_chapters_topics,
        actor=user,
    )


@router.post("/answers")
async def import_answers(
    test_id: int = Form(...),
    replace: bool = Form(False),
    dry_run: bool = Form(True),
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return importer.import_answers(
        db,
        access.find_test(db, user, test_id),
        await file.read(),
        replace=replace,
        dry_run=dry_run,
        requested_test_id=test_id,
        actor=user,
    )


@router.post("/answer-key")
async def correct_answer_key(
    test_id: int = Form(...),
    dry_run: bool = Form(True),
    confirm_new_chapters_topics: bool = Form(False),
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Correct a test's answer key / chapter-topic mapping. Same columns as
    the test setup; every question must be listed. Re-evaluates the test.
    """
    return importer.correct_answer_key(
        db,
        access.find_test(db, user, test_id),
        await file.read(),
        dry_run=dry_run,
        confirm_new_chapters_topics=confirm_new_chapters_topics,
        requested_test_id=test_id,
        actor=user,
    )
