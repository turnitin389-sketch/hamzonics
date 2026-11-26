"""Public checks: upload a document (or pasted text), follow its progress in the queue,
read the report, download the PDF, delete it.

There are no accounts. A check is reached only through its random id (a UUID4 that
cannot be guessed); there is no endpoint that lists other people's checks. Deleting
needs the delete token returned once at creation (the browser keeps it).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api.config import get_settings
from api.deps import DB, IpHash
from api.jobs import enqueue_check
from api.models import DocumentText, ReportRow, SourceRow, Status, Submission, new_id, utcnow
from api.schemas import AIOut, FlagOut, FlagSummary, MessageOut, QueueOut, SimilarityOut, SubmissionOut, SubmissionTextOut
from api.services import ai_view, default_filters, similarity_view
from engine.extract import FileKind, UnsupportedFileType, detect_file_type
from engine.similarity.merge import Filters
from engine.version import ENGINE_VERSION

router = APIRouter(prefix="/api", tags=["checks"])

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_ID_RE = re.compile(r"^[0-9a-f-]{36}$")
_CHUNK = 1024 * 1024


def _get(db: DB, submission_id: str) -> Submission:
    sub = db.get(Submission, submission_id) if _ID_RE.match(submission_id) else None
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Check not found (it may have been deleted)")
    return sub


def _queue_position(db: DB, sub: Submission) -> int | None:
    if sub.status != Status.QUEUED:
        return None
    ahead = db.scalar(
        select(func.count()).select_from(Submission).where(
            Submission.status == Status.QUEUED, Submission.created_at < sub.created_at
        )
    )
    return int(ahead or 0) + 1


def _out(db: DB, sub: Submission, delete_token: str | None = None) -> SubmissionOut:
    return SubmissionOut(
        id=sub.id,
        status=sub.status,
        progress=sub.progress,
        stage=sub.stage,
        error=sub.error,
        queue_position=_queue_position(db, sub),
        original_filename=sub.original_filename,
        file_type=sub.file_type,
        file_size=sub.file_size,
        word_count=sub.word_count,
        page_count=sub.page_count,
        ocr_pages=sub.ocr_pages,
        repository_opt_in=sub.repository_opt_in,
        engine_version=sub.engine_version,
        flags=[FlagSummary(type=f.type, count=f.count) for f in sub.flags],
        similarity_percent=sub.similarity_percent,
        ai_percent=sub.ai_percent,
        ai_available=None if sub.ai_result is None else bool(sub.ai_result.get("available")),
        created_at=sub.created_at,
        started_at=sub.started_at,
        finished_at=sub.finished_at,
        delete_token=delete_token,
    )


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    buf = bytearray()
    while chunk := await upload.read(_CHUNK):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File is larger than {limit // (1024 * 1024)} MB")
    return bytes(buf)


def _safe_filename(name: str | None, kind: FileKind) -> str:
    base = Path(name or f"document.{kind.value}").name
    base = re.sub(r"[^\w.\- ()؀-ۿ]", "_", base).strip() or f"document.{kind.value}"
    return base[:200]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.get("/queue", response_model=QueueOut)
def queue_status(db: DB) -> QueueOut:
    counts = dict(db.execute(
        select(Submission.status, func.count()).where(Submission.status.in_([Status.QUEUED, Status.RUNNING]))
        .group_by(Submission.status)
    ).all())
    return QueueOut(running=int(counts.get(Status.RUNNING, 0)), queued=int(counts.get(Status.QUEUED, 0)),
                    max_concurrent=get_settings().max_concurrent_checks)


@router.post("/submissions", response_model=SubmissionOut, status_code=status.HTTP_202_ACCEPTED)
async def create_submission(
    background: BackgroundTasks,
    response: Response,
    db: DB,
    ip: IpHash,
    idempotency_key: Annotated[str, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    repository_opt_in: Annotated[bool, Form()] = True,
) -> SubmissionOut:
    """Only reading the upload happens on the event loop; all database work runs in a
    worker thread so a busy database can never stall other requests."""
    settings = get_settings()
    if not _IDEMPOTENCY_RE.match(idempotency_key):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid idempotency key")

    has_file = file is not None and bool(file.filename)
    has_text = bool(text and text.strip())
    if has_file == has_text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload one file or paste text (not both)")

    if has_file:
        assert file is not None
        data = await _read_limited(file, settings.max_upload_bytes)
        try:
            kind = detect_file_type(data)
        except UnsupportedFileType as exc:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
        # A ".pdf" / ".docx" ... that is really something else (e.g. HTML or plain text renamed).
        claimed = Path(file.filename or "").suffix.lower().lstrip(".")
        if claimed in {"pdf", "docx", "odt", "rtf"} and claimed != kind.value:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                f"This file is named .{claimed} but is not a real {claimed.upper()} file. "
                                "Save it again from the original program and upload it.")
        filename = _safe_filename(file.filename, kind)
    else:
        assert text is not None
        data = text.encode("utf-8")
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Pasted text is too large")
        kind, filename = FileKind.TXT, "pasted-text.txt"

    out, code = await run_in_threadpool(
        _store_submission, db, ip, idempotency_key, data, kind, filename, repository_opt_in, background
    )
    response.status_code = code
    return out


def _store_submission(
    db: DB,
    ip: str,
    idempotency_key: str,
    data: bytes,
    kind: FileKind,
    filename: str,
    repository_opt_in: bool,
    background: BackgroundTasks,
) -> tuple[SubmissionOut, int]:
    settings = get_settings()
    # Double-click / network retry: return the check that already exists (no new token).
    existing = db.scalar(select(Submission).where(Submission.idempotency_key == idempotency_key))
    if existing is not None:
        if existing.ip_hash != ip:
            raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate request key")
        return _out(db, existing), status.HTTP_200_OK

    if settings.checks_per_ip_per_hour > 0:
        recent = db.scalar(select(func.count()).select_from(Submission).where(
            Submission.ip_hash == ip, Submission.created_at >= utcnow() - timedelta(hours=1)))
        if (recent or 0) >= settings.checks_per_ip_per_hour:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                f"Limit reached: {settings.checks_per_ip_per_hour} checks per hour. Please try again later.")
    waiting = db.scalar(select(func.count()).select_from(Submission).where(Submission.status == Status.QUEUED))
    if (waiting or 0) >= settings.max_queue:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The queue is full right now. Please try again in a few minutes.")

    sub_id = new_id()
    delete_token = secrets.token_urlsafe(24)
    folder = Path(settings.upload_dir) / sub_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"original.{kind.value}"
    path.write_bytes(data)

    sub = Submission(
        id=sub_id,
        idempotency_key=idempotency_key,
        delete_token_hash=_token_hash(delete_token),
        ip_hash=ip,
        status=Status.QUEUED,
        stage="queued",
        progress=0,
        original_filename=filename,
        file_type=kind.value,
        file_size=len(data),
        file_path=str(path),
        file_sha256=hashlib.sha256(data).hexdigest(),
        engine_version=ENGINE_VERSION,
        settings={},
        repository_opt_in=repository_opt_in,
    )
    db.add(sub)
    try:
        db.commit()
    except IntegrityError:
        # Two identical requests raced; the other one won.
        db.rollback()
        shutil.rmtree(folder, ignore_errors=True)
        winner = db.scalar(select(Submission).where(Submission.idempotency_key == idempotency_key))
        if winner is None:
            raise
        return _out(db, winner), status.HTTP_200_OK

    enqueue_check(sub.id, background)
    db.refresh(sub)
    return _out(db, sub, delete_token), status.HTTP_202_ACCEPTED


@router.get("/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: str, db: DB) -> SubmissionOut:
    return _out(db, _get(db, submission_id))


def _done(sub: Submission, what: str) -> None:
    if sub.status != Status.DONE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{what} not ready yet")


@router.get("/submissions/{submission_id}/text", response_model=SubmissionTextOut)
def get_submission_text(submission_id: str, db: DB) -> SubmissionTextOut:
    """Available as soon as the document has been read (also while the check is still running:
    the progress screen shows the text being scanned)."""
    sub = _get(db, submission_id)
    doc = db.get(DocumentText, sub.id)
    if doc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Text is not ready yet")
    return SubmissionTextOut(
        id=sub.id, word_count=sub.word_count or 0, clean_text=doc.clean_text, pages=doc.offsets.get("pages", [])
    )


@router.get("/submissions/{submission_id}/flags", response_model=list[FlagOut])
def get_submission_flags(submission_id: str, db: DB) -> list[FlagOut]:
    sub = _get(db, submission_id)
    _done(sub, "Flags are")
    return [FlagOut(type=f.type, count=f.count, locations=f.locations) for f in sub.flags]


@router.get("/submissions/{submission_id}/similarity", response_model=SimilarityOut)
def get_submission_similarity(
    submission_id: str,
    db: DB,
    exclude_quotes: bool | None = None,
    exclude_bibliography: bool | None = None,
    min_words: Annotated[int | None, Query(ge=0, le=1000)] = None,
    exclude_source: Annotated[list[str], Query()] = [],  # noqa: B006 (FastAPI query list)
) -> SimilarityOut:
    """Similarity recomputed from the stored matches with the given filters
    (missing filters use the report defaults)."""
    sub = _get(db, submission_id)
    doc = db.get(DocumentText, sub.id)
    if sub.status != Status.DONE or doc is None or sub.word_count is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Similarity results are not ready yet")
    d = default_filters()
    return similarity_view(db, sub, Filters(
        d.exclude_quotes if exclude_quotes is None else exclude_quotes,
        d.exclude_bibliography if exclude_bibliography is None else exclude_bibliography,
        d.min_words if min_words is None else min_words,
        frozenset(exclude_source),
    ))


@router.get("/submissions/{submission_id}/ai", response_model=AIOut)
def get_submission_ai(submission_id: str, db: DB) -> AIOut:
    sub = _get(db, submission_id)
    _done(sub, "AI results are")
    return ai_view(db, sub)


@router.get("/submissions/{submission_id}/report.pdf")
def download_report(
    submission_id: str, db: DB, part: Annotated[Literal["all", "similarity", "ai"], Query()] = "all",
) -> FileResponse:
    """Download a current full, Similarity-only, or AI-only PDF report."""
    sub = _get(db, submission_id)
    _done(sub, "The report is")
    from worker.report import generate_part_report, generate_report, pdf_artifact_is_current

    stem = re.sub(r"[^\w\-]+", "_", Path(sub.original_filename).stem)[:60] or "document"
    if part != "all":
        path = generate_part_report(db, sub, part)
        label = "similarity" if part == "similarity" else "ai"
        return FileResponse(
            path, media_type="application/pdf", filename=f"{stem}-hamzonics-{label}-report.pdf",
            headers={"Cache-Control": "private, no-store"},
        )

    row = db.scalar(select(ReportRow).where(ReportRow.submission_id == sub.id))
    path = Path(row.pdf_path) if row else None
    if (
        row is None
        or path is None
        or not pdf_artifact_is_current(path)
        or hashlib.sha256(path.read_bytes()).hexdigest() != row.sha256
    ):
        row = generate_report(db, sub)
        path = Path(row.pdf_path)
    return FileResponse(
        path, media_type="application/pdf", filename=f"{stem}-hamzonics-report.pdf",
        headers={"Cache-Control": "private, no-store"},
    )


def delete_check(db: DB, sub: Submission) -> None:
    """Remove a check, its upload and PDF. A repository copy keeps its text (unlinked)."""
    folder = Path(sub.file_path).parent
    report = db.scalar(select(ReportRow).where(ReportRow.submission_id == sub.id))
    pdf = Path(report.pdf_path) if report else None
    from worker.report import part_report_path, pdf_artifact_marker_path

    part_pdfs = [part_report_path(sub.id, part) for part in ("similarity", "ai")]
    repo = db.scalar(select(SourceRow).where(SourceRow.submission_id == sub.id))
    if repo is not None:
        repo.submission_id = None
    db.delete(sub)
    db.commit()
    shutil.rmtree(folder, ignore_errors=True)
    for artifact in (pdf, *part_pdfs):
        if artifact is not None:
            artifact.unlink(missing_ok=True)
            pdf_artifact_marker_path(artifact).unlink(missing_ok=True)


@router.delete("/submissions/{submission_id}", response_model=MessageOut)
def delete_submission(
    submission_id: str, db: DB, x_delete_token: Annotated[str, Header()] = "",
) -> MessageOut:
    sub = _get(db, submission_id)
    if not x_delete_token or not hmac.compare_digest(_token_hash(x_delete_token), sub.delete_token_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the browser that uploaded this check can delete it")
    if sub.status == Status.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "This check is running. Delete it after it finishes.")
    if sub.repository_opt_in:
        # The uploader withdraws the document: also remove it from the repository.
        repo = db.scalar(select(SourceRow).where(SourceRow.submission_id == sub.id))
        if repo is not None:
            db.delete(repo)
            db.flush()
    delete_check(db, sub)
    return MessageOut(message="Check deleted")
