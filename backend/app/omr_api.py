"""
OMR image import (Stage 2B).

    POST /api/tests/{test_id}/omr/import

Admin-only, like the CSV imports. The test is resolved for the signed-in
user's institute, so another institute's test is reported exactly like a
missing one. The response uses our own schema (omr/service.py); nothing
from the recogniser, no file paths and no internal errors are returned.
"""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .database.connection import get_db
from .database.models import Test, User
from .omr.checker import OMRBusy, OMREngineError, OMRUnavailable
from .omr.service import UploadedFile, process_omr_batch
from .security.access import owned_test
from .security.dependencies import require_admin

logger = logging.getLogger("coaching.omr")

router = APIRouter(
    prefix="/api/tests",
    dependencies=[Depends(require_admin)],
)


@router.post("/{test_id}/omr/import")
def omr_import(
    files: list[UploadFile] = File(default=[]),
    template_id: str = Form(""),
    replace: bool = Form(False),
    dry_run: bool = Form(True),
    test: Test = Depends(owned_test),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Recognise a batch of answer-sheet images for this test.

    With dry_run (the default) nothing is saved. A batch is imported only
    when every sheet validates and no answer needs review; otherwise the
    whole batch is left unimported.
    """

    try:
        return process_omr_batch(
            db,
            test,
            [UploadedFile(upload.filename, upload.file) for upload in files],
            template_id=template_id,
            replace=replace,
            dry_run=dry_run,
            actor=user,
        )
    except OMRBusy as error:
        raise HTTPException(status_code=429, detail=error.public_message) from None
    except OMRUnavailable as error:
        raise HTTPException(status_code=503, detail=error.public_message) from None
    except OMREngineError as error:
        raise HTTPException(status_code=502, detail=error.public_message) from None
