"""Celery worker crash recovery (found in the Docker test: a killed worker left a check
'running' for an hour, until Redis' visibility timeout)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests import fixtures as fx
from tests.api.test_flow import paste


def test_orphaned_running_check_is_requeued_with_new_token(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from api.db import get_sessionmaker
    from api.models import Submission
    from worker import tasks

    sid = paste(client, fx.essay(1)).json()["id"]
    with get_sessionmaker()() as db:
        sub = db.get(Submission, sid)
        sub.status, sub.stage, sub.progress = "running", "similarity", 50
        sub.settings = {"_token": "old"}
        db.commit()

    sent: list[tuple] = []
    monkeypatch.setattr("worker.celery_app.app.send_task", lambda name, args, queue: sent.append((name, args, queue)))
    tasks.requeue_orphaned_checks()

    assert len(sent) == 1 and sent[0][1][0] == sid and sent[0][1][1] == 1
    new_token = sent[0][1][2]
    with get_sessionmaker()() as db:
        sub = db.get(Submission, sid)
        assert sub.status == "queued" and sub.settings["_token"] == new_token != "old"
    assert tasks._token_is_current(sid, new_token)
    assert not tasks._token_is_current(sid, "old")  # the stale redelivered copy is ignored
    assert tasks._token_is_current(sid, None)  # messages without a token still run


def test_token_is_not_part_of_the_result_key() -> None:
    from worker.frozen import compute_result_key

    assert compute_result_key("abc", {"_token": "1"}) == compute_result_key("abc", {"_token": "2"})
