"""Queue behaviour: at most MAX_CONCURRENT_CHECKS (3) checks run at once, the rest wait
in arrival order; interrupted checks are re-queued at startup."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.extract import ExtractionError, FileKind, extract_document
from tests import fixtures as fx
from tests.api.test_flow import paste


def test_progress_callback_error_is_not_reported_as_damaged_file(tmp_path: Path) -> None:
    """A database error while saving progress used to be shown as 'DOCX file damaged'."""
    path = fx.make_docx(tmp_path / "ok.docx", [fx.essay(1)])

    class DatabaseIsLocked(Exception):
        pass

    def progress(done: int, total: int) -> None:
        raise DatabaseIsLocked("database is locked")

    with pytest.raises(DatabaseIsLocked):
        extract_document(path, FileKind.DOCX, progress=progress)
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"PK\x03\x04 not really a docx")
    with pytest.raises(ExtractionError):
        extract_document(bad, FileKind.DOCX)


def _wait_done(client: TestClient, sid: str, seconds: float = 90) -> dict:
    end = time.time() + seconds
    while time.time() < end:
        s = client.get(f"/api/submissions/{sid}").json()
        if s["status"] in ("done", "failed"):
            return s
        time.sleep(0.1)
    raise AssertionError(f"submission {sid} did not finish")


def test_three_at_a_time_then_queue(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from api import jobs
    from api.config import get_settings
    from worker import pipeline

    monkeypatch.setenv("INLINE_SYNC", "false")
    get_settings.cache_clear()

    running = 0
    peak = 0
    lock = threading.Lock()
    real = pipeline.process_analysis

    def slow_analysis(submission_id: str, final_attempt: bool = True) -> None:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.6)
        try:
            real(submission_id, final_attempt)
        finally:
            with lock:
                running -= 1

    monkeypatch.setattr(pipeline, "process_analysis", slow_analysis)
    ids = [paste(client, fx.essay(1) + f" Number {i}.").json()["id"] for i in range(7)]
    time.sleep(0.3)
    positions = [client.get(f"/api/submissions/{i}").json()["queue_position"] for i in ids]
    assert [p for p in positions if p is not None] == sorted(p for p in positions if p is not None)
    assert any(p is not None for p in positions[3:]), "later checks should be waiting in the queue"
    q = client.get("/api/queue").json()
    assert q["running"] <= 3 and q["max_concurrent"] == 3
    assert all(_wait_done(client, i)["status"] == "done" for i in ids)
    assert peak == 3, f"expected exactly 3 checks at once, saw {peak}"
    assert len(jobs._workers) == 3


def test_restart_recovery(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from api import jobs
    from api.config import get_settings
    from api.db import get_sessionmaker
    from api.models import Submission

    monkeypatch.setenv("INLINE_SYNC", "false")
    get_settings.cache_clear()
    sid = paste(client, fx.essay(2)).json()["id"]
    _wait_done(client, sid)
    with get_sessionmaker()() as db:
        s = db.get(Submission, sid)
        s.status, s.stage, s.progress = "running", "similarity", 60
        db.commit()
    assert jobs.recover_inline_jobs() == 1
    assert _wait_done(client, sid)["status"] == "done"
