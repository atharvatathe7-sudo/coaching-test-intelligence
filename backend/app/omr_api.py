"""
OMR import and review (Stages 2B and 3).

    POST /api/tests/{test_id}/omr/import       read sheets into a pending batch
    GET  /api/tests/{test_id}/omr/batches      the test's batches
    GET  /api/omr/templates                    available sheet templates
    GET  /api/omr/batches/{id}                 batch summary
    GET  /api/omr/batches/{id}/review          what needs review
    GET  /api/omr/sheets/{id}/image            a stored sheet image
    POST /api/omr/review/{item_id}             settle a doubtful answer
    POST /api/omr/sheets/{id}/roll             say which student a sheet is
    POST /api/omr/batches/{id}/commit          make the answers real
    POST /api/omr/batches/{id}/discard         throw the batch away

Permissions: administrators only, like every other data import. Every
object is resolved through security.access for the signed-in user's
institute, so another institute's batch, sheet or image is reported
exactly like a missing one. Each decision is recorded with the user who
made it. Nothing returned contains a file path or an engine detail.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .database.connection import get_db
from .database.models import OMRAnswer, OMRBatch, OMRSheet, Test, User
from .omr import batches, storage
from .omr.checker import OMRBusy, OMREngineError, OMRUnavailable
from .omr.service import UploadedFile, create_pending_batch
from .omr.template import list_templates
from .security import access
from .security.access import owned_omr_answer, owned_omr_batch, owned_omr_sheet, owned_test
from .security.dependencies import require_admin

logger = logging.getLogger("coaching.omr")

router = APIRouter(dependencies=[Depends(require_admin)])

_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg"}


class ReviewDecision(BaseModel):
    final_answer: Literal["A", "B", "C", "D", "BLANK"]
    # The revision the reviewer saw; a mismatch means someone else changed it.
    revision: int = Field(ge=0)


class RollAssignment(BaseModel):
    roll_number: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=0)


class CommitRequest(BaseModel):
    replace: bool = False


def _test_of(db: Session, batch: OMRBatch) -> Test:
    return db.get(Test, batch.test_id)


def _domain_errors(call):
    """Run a batches.* call and turn its errors into fixed HTTP responses."""
    try:
        return call()
    except batches.CommitRefused as refused:
        raise HTTPException(
            status_code=409,
            detail={"message": "The batch cannot be committed.", "problems": refused.problems},
        ) from None
    except (batches.BatchStateError, batches.ConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except batches.InvalidDecision as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


# ---------------------------------------------------------------- upload

@router.post("/api/tests/{test_id}/omr/import")
def omr_import(
    files: list[UploadFile] = File(default=[]),
    template_id: str = Form(""),
    test: Test = Depends(owned_test),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Read a batch of answer-sheet images for this test and store it for
    review. No answer or result is created; that happens at commit.
    """

    try:
        return create_pending_batch(
            db,
            test,
            [UploadedFile(upload.filename, upload.file) for upload in files],
            template_id=template_id,
            actor=user,
        )
    except OMRBusy as error:
        raise HTTPException(status_code=429, detail=error.public_message) from None
    except OMRUnavailable as error:
        raise HTTPException(status_code=503, detail=error.public_message) from None
    except OMREngineError as error:
        raise HTTPException(status_code=502, detail=error.public_message) from None


@router.get("/api/omr/templates")
def omr_templates():
    return {
        "templates": [
            {
                "id": t.id,
                "version": t.version,
                "description": t.description,
                "questions": len(t.question_numbers),
            }
            for t in list_templates()
        ]
    }


# ----------------------------------------------------------------- batches

@router.get("/api/tests/{test_id}/omr/batches")
def list_batches(
    test: Test = Depends(owned_test),
    db: Session = Depends(get_db),
):
    found = (
        db.query(OMRBatch)
        .filter(OMRBatch.test_id == test.id, OMRBatch.status != "DISCARDED")
        .order_by(OMRBatch.id.desc())
        .limit(50)
        .all()
    )
    for batch in found:
        batches.expire_if_stale(db, batch)

    return {"batches": [batches.batch_summary(db, b, test) for b in found]}


@router.get("/api/omr/batches/{batch_id}")
def get_batch(
    batch: OMRBatch = Depends(owned_omr_batch),
    db: Session = Depends(get_db),
):
    batches.expire_if_stale(db, batch)
    return batches.batch_summary(db, batch, _test_of(db, batch))


@router.get("/api/omr/batches/{batch_id}/review")
def get_review(
    batch: OMRBatch = Depends(owned_omr_batch),
    db: Session = Depends(get_db),
):
    batches.expire_if_stale(db, batch)
    test = _test_of(db, batch)
    items = batches.review_items(db, batch, test)

    return {
        "batch": batches.batch_summary(db, batch, test),
        "items": items,
        "open_count": sum(1 for i in items if not i["resolved"]),
    }


# ------------------------------------------------------------------ images

@router.get("/api/omr/sheets/{sheet_id}/image")
def get_sheet_image(
    view: Literal["checked", "original"] = Query("checked"),
    sheet: OMRSheet = Depends(owned_omr_sheet),
    db: Session = Depends(get_db),
):
    """A stored image. Looked up by id only; the client never sees a path."""

    path = storage.existing_image(
        sheet.batch_id, sheet.id, sheet.image_ext, checked=(view == "checked")
    )

    if path is None and view == "checked":
        path = storage.existing_image(sheet.batch_id, sheet.id, sheet.image_ext, checked=False)

    if path is None:
        raise HTTPException(status_code=404, detail="The image is no longer available.")

    return FileResponse(
        path,
        media_type=_MEDIA_TYPES[sheet.image_ext],
        headers={
            # Student data: never cached by the browser or a proxy.
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ------------------------------------------------------------------ review

@router.post("/api/omr/review/{item_id}")
def review_answer(
    decision: ReviewDecision,
    answer: OMRAnswer = Depends(owned_omr_answer),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    sheet = db.get(OMRSheet, answer.sheet_id)
    batch = db.get(OMRBatch, sheet.batch_id)
    test = _test_of(db, batch)

    _domain_errors(lambda: batches.resolve_answer(
        db, batch, test, answer, user, decision.final_answer, decision.revision
    ))

    db.refresh(batch)
    return {"batch": batches.batch_summary(db, batch, test)}


@router.post("/api/omr/sheets/{sheet_id}/roll")
def assign_sheet_roll(
    assignment: RollAssignment,
    sheet: OMRSheet = Depends(owned_omr_sheet),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    batch = db.get(OMRBatch, sheet.batch_id)
    test = _test_of(db, batch)

    _domain_errors(lambda: batches.assign_roll(
        db, batch, test, sheet, user, assignment.roll_number, assignment.revision
    ))

    db.refresh(batch)
    return {"batch": batches.batch_summary(db, batch, test)}


# ---------------------------------------------------------- commit / discard

@router.post("/api/omr/batches/{batch_id}/commit")
def commit(
    request: CommitRequest = CommitRequest(),
    batch: OMRBatch = Depends(owned_omr_batch),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    test = _test_of(db, batch)
    outcome = _domain_errors(lambda: batches.commit_batch(db, batch, test, user, replace=request.replace))

    db.refresh(batch)
    return {"batch": batches.batch_summary(db, batch, test), **outcome}


@router.post("/api/omr/batches/{batch_id}/discard")
def discard(
    batch: OMRBatch = Depends(owned_omr_batch),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    test = _test_of(db, batch)
    outcome = _domain_errors(lambda: batches.discard_batch(db, batch, user))

    db.refresh(batch)
    return {"batch": batches.batch_summary(db, batch, test), **outcome}
