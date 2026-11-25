"""Public report verification (linked from the QR code on every report page).

GET  shows the key facts of a report (no document text, no file name).
POST takes a PDF and says whether it is byte-for-byte the report we issued.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import DB
from api.models import ReportRow, Submission, as_utc

router = APIRouter(prefix="/api/verify", tags=["verify"])
MAX_PDF_BYTES = 40 * 1024 * 1024


class VerifyInfo(BaseModel):
    submission_id: str
    submitted_at: datetime
    report_created_at: datetime
    word_count: int | None
    similarity_percent: float | None
    ai_percent: float | None
    engine_version: str
    pages: int
    sha256: str


class VerifyResult(BaseModel):
    authentic: bool
    message: str


def _report(db: DB, submission_id: str) -> tuple[Submission, ReportRow]:
    row = db.scalar(select(ReportRow).where(ReportRow.submission_id == submission_id))
    sub = db.get(Submission, submission_id) if row else None
    if row is None or sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No report was issued with this ID")
    return sub, row


@router.get("/{submission_id}", response_model=VerifyInfo)
def verify_info(submission_id: str, db: DB) -> VerifyInfo:
    sub, row = _report(db, submission_id)
    return VerifyInfo(
        submission_id=sub.id, submitted_at=as_utc(sub.created_at), report_created_at=as_utc(row.created_at),
        word_count=sub.word_count, similarity_percent=sub.similarity_percent, ai_percent=sub.ai_percent,
        engine_version=sub.engine_version,
        pages=row.pages, sha256=row.sha256,
    )


@router.post("/{submission_id}", response_model=VerifyResult)
async def verify_file(submission_id: str, db: DB, file: Annotated[UploadFile, File()]) -> VerifyResult:
    _, row = await run_in_threadpool(_report, db, submission_id)
    digest = hashlib.sha256()
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_PDF_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large to be one of our reports")
        digest.update(chunk)
    if hmac.compare_digest(digest.hexdigest(), row.sha256):
        return VerifyResult(authentic=True, message="Authentic: this PDF is exactly the report we issued.")
    return VerifyResult(
        authentic=False,
        message="Not authentic: this file is different from the report we issued (it was changed or is another file).",
    )
