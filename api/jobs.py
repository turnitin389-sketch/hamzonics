"""Dispatch background work. At most MAX_CONCURRENT_CHECKS checks run at the same
time (default 3); everyone else waits in a first-come, first-served queue.

- celery (production): one Celery worker with --concurrency=MAX_CONCURRENT_CHECKS runs
  the whole check (extract -> similarity -> AI -> PDF) as one task.
- inline (local, no Redis): an in-process queue served by MAX_CONCURRENT_CHECKS threads.
  Checks that were queued/running when the server stopped are queued again at startup.
- INLINE_SYNC=true (tests): the job runs right after the response, in the request.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

from fastapi import BackgroundTasks

from api.config import get_settings

log = logging.getLogger("hamzonics.jobs")

_queue: queue.Queue[str] = queue.Queue()
_workers: list[threading.Thread] = []
_start_lock = threading.Lock()


def _worker_loop() -> None:
    from worker.pipeline import run_check

    while True:
        submission_id = _queue.get()
        try:
            run_check(submission_id, final_attempt=True)
        except Exception:  # already recorded on the submission (failed)
            log.exception("inline job %s crashed", submission_id)
        finally:
            _queue.task_done()


def _ensure_workers() -> None:
    with _start_lock:
        while len(_workers) < get_settings().max_concurrent_checks:
            t = threading.Thread(target=_worker_loop, name=f"check-worker-{len(_workers)}", daemon=True)
            t.start()
            _workers.append(t)


def enqueue_check(submission_id: str, background: BackgroundTasks | None) -> None:
    s = get_settings()
    if s.job_runner == "inline":
        if s.inline_sync and background is not None:
            from worker.pipeline import run_check

            background.add_task(run_check, submission_id, True)
            return
        _ensure_workers()
        _queue.put(submission_id)
        return
    send_celery_check(submission_id)


def send_celery_check(submission_id: str, attempt: int = 0) -> None:
    """Queue a check with a fresh run token. Only the task carrying the CURRENT token may run
    it: when a check is re-queued after a worker crash, Redis later redelivers the old
    message too (after its visibility timeout), and that copy must not run the check again."""
    import uuid

    from api.db import get_sessionmaker
    from api.models import Submission
    from worker.celery_app import app

    token = uuid.uuid4().hex
    with get_sessionmaker()() as db:
        sub = db.get(Submission, submission_id)
        if sub is None:
            return
        sub.settings = {**(sub.settings or {}), "_token": token}
        db.commit()
    app.send_task("worker.tasks.run_check", args=[submission_id, attempt, token], queue="checks")


def recover_inline_jobs() -> int:
    """At startup (inline mode): re-queue checks left queued/running by a stopped server."""
    from sqlalchemy import select

    from api.db import get_sessionmaker
    from api.models import Status, Submission

    with get_sessionmaker()() as db:
        rows = db.scalars(
            select(Submission).where(Submission.status.in_([Status.QUEUED, Status.RUNNING]))
            .order_by(Submission.created_at)
        ).all()
        for sub in rows:
            if sub.status == Status.RUNNING:  # interrupted mid-way: start that check again
                sub.status, sub.stage, sub.progress = Status.QUEUED, "retrying", 0
        db.commit()
        ids = [s.id for s in rows]
    for sid in ids:
        enqueue_check(sid, None)
    if ids:
        log.warning("re-queued %d interrupted check(s)", len(ids))
    return len(ids)


def start_inline_maintenance(interval_s: int = 3600) -> None:
    """Inline mode has no Celery beat: delete expired checks once an hour in a thread."""

    def loop() -> None:
        from worker.maintenance import delete_expired

        while True:
            try:
                delete_expired()
            except Exception:
                log.exception("maintenance failed")
            time.sleep(interval_s)

    threading.Thread(target=loop, name="maintenance", daemon=True).start()
