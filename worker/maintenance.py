"""Periodic housekeeping (Celery beat every 15 minutes; a thread in inline mode).

- Stuck jobs: a check still `running` (or `queued` after a lost message) long after the
  job time limit is put back in the queue once; the second time it is failed.
- Retention: checks older than RETENTION_DAYS are deleted (upload, text, PDF). Their
  repository copy, if the uploader allowed it, stays so later checks can match it.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from api.config import get_settings
from api.db import get_sessionmaker
from api.models import Status, Submission, as_utc, utcnow
from worker.pipeline import INTERNAL_ERROR, _fail

log = logging.getLogger("hamzonics.maintenance")


def recover_stuck(enqueue) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """`enqueue(submission_id)` puts a check back in the queue."""
    s = get_settings()
    cutoff = utcnow() - timedelta(seconds=2 * s.job_time_limit_s)
    requeued = failed = 0
    with get_sessionmaker()() as db:
        rows = db.scalars(
            select(Submission).where(Submission.status == Status.RUNNING, Submission.created_at < cutoff)
        ).all()
        for sub in rows:
            started = as_utc(sub.started_at or sub.created_at)
            if started >= cutoff:
                continue
            settings = dict(sub.settings or {})
            if settings.get("_recovered"):
                _fail(db, sub, INTERNAL_ERROR)
                failed += 1
                continue
            settings["_recovered"] = 1  # keys starting with "_" are internal, never part of result_key
            sub.settings = settings
            sub.status, sub.stage, sub.progress, sub.started_at = Status.QUEUED, "retrying", 0, utcnow()
            db.commit()
            enqueue(sub.id)
            requeued += 1
    return {"requeued": requeued, "failed": failed}


def delete_expired() -> int:
    from api.routers.submissions import delete_check

    days = get_settings().retention_days
    if days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=days)
    deleted = 0
    with get_sessionmaker()() as db:
        ids = db.scalars(
            select(Submission.id).where(Submission.created_at < cutoff,
                                        Submission.status.in_([Status.DONE, Status.FAILED])).limit(500)
        ).all()
        for sid in ids:
            sub = db.get(Submission, sid)
            if sub is not None:
                delete_check(db, sub)
                deleted += 1
    if deleted:
        log.info("retention: deleted %d check(s) older than %d days", deleted, days)
    return deleted


def run_maintenance() -> dict[str, int]:
    from api.jobs import send_celery_check

    stuck = recover_stuck(lambda sid: send_celery_check(sid, attempt=1))
    return {**stuck, "expired_deleted": delete_expired()}
