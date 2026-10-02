from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from .database.connection import get_db
from .services import importer

router = APIRouter(prefix="/api/imports")

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
    db: Session = Depends(get_db),
):
    return importer.import_roster(
        db,
        batch_id,
        await file.read(),
        dry_run=dry_run,
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
    db: Session = Depends(get_db),
):
    return importer.import_test_setup(
        db,
        batch_id=batch_id,
        test_name=test_name,
        subject=subject,
        test_date=test_date,
        marks_correct=marks_correct,
        marks_wrong=marks_wrong,
        marks_blank=marks_blank,
        raw=await file.read(),
        dry_run=dry_run,
        confirm_new_chapters_topics=confirm_new_chapters_topics,
    )


@router.post("/answers")
async def import_answers(
    test_id: int = Form(...),
    replace: bool = Form(False),
    dry_run: bool = Form(True),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    return importer.import_answers(
        db,
        test_id,
        await file.read(),
        replace=replace,
        dry_run=dry_run,
    )
