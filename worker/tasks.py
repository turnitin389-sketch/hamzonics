"""Celery task wrappers around worker.pipeline.

- One task runs a whole check. The worker runs with --concurrency=MAX_CONCURRENT_CHECKS
  and prefetch 1, so at most that many checks run at once and the rest wait in Redis
  in arrival order.
- One automatic retry on unexpected errors (incl. the soft time limit); the second
  failure marks the check failed.
- Crash recovery: when the worker starts, checks left `running` by a killed worker are
  queued again at once (worker_ready), instead of waiting for Redis' visibility timeout.
  Each queued message carries a run token; a stale redelivered copy is ignored.
"""

from __future__ import annotations

import logging

from celery import Task
from celery.signals import worker_ready

from worker.celery_app import app
from worker.pipeline import run_check as _run_check

log = logging.getLogger("hamzonics.tasks")
RETRY_DELAY_S = 30


def _token_is_current(submission_id: str, token: str | None) -> bool:
    if token is None:  # message from before run tokens existed
        return True
    from api.db import get_sessionmaker
    from api.models import Submission

    with get_sessionmaker()() as db:
        sub = db.get(Submission, submission_id)
        return sub is not None and (sub.settings or {}).get("_token") == token


@app.task(name="worker.tasks.run_check", bind=True, max_retries=None)
def run_check(self: Task, submission_id: str, attempt: int = 0, token: str | None = None) -> None:
    if not _token_is_current(submission_id, token):
        log.info("ignoring stale message for %s (check was re-queued)", submission_id)
        return
    try:
        _run_check(submission_id, final_attempt=attempt >= 1)
    except Exception as exc:
        if attempt >= 1:
            raise
        raise self.retry(args=[submission_id, attempt + 1, token], countdown=RETRY_DELAY_S, exc=exc) from exc


@app.task(name="worker.tasks.maintenance")
def maintenance() -> dict:
    from worker.maintenance import run_maintenance

    return run_maintenance()


@worker_ready.connect
def requeue_orphaned_checks(**_kwargs) -> None:  # type: ignore[no-untyped-def]
    """Single worker container: anything still `running` when it starts was being run by
    the previous (killed or crashed) worker process."""
    from sqlalchemy import select

    from api.db import get_sessionmaker
    from api.jobs import send_celery_check
    from api.models import Status, Submission

    with get_sessionmaker()() as db:
        ids = db.scalars(select(Submission.id).where(Submission.status == Status.RUNNING)).all()
        for sid in ids:
            sub = db.get(Submission, sid)
            sub.status, sub.stage, sub.progress = Status.QUEUED, "retrying", 0
        db.commit()
    for sid in ids:
        send_celery_check(sid, attempt=1)
    if ids:
        log.warning("re-queued %d check(s) interrupted by a worker restart", len(ids))
