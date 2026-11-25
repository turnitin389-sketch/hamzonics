"""Public flow: upload (no account) -> queued -> done; delete with token; limits."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from engine.extract import count_words
from tests import fixtures as fx


def upload(client: TestClient, path: Path, key: str | None = None, **data):  # type: ignore[no-untyped-def]
    with path.open("rb") as fh:
        return client.post(
            "/api/submissions",
            data={"idempotency_key": key or uuid.uuid4().hex, **data},
            files={"file": (path.name, fh, "application/octet-stream")},
        )


def paste(client: TestClient, text: str, opt_in: bool = True):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/submissions",
        data={"idempotency_key": uuid.uuid4().hex, "text": text, "repository_opt_in": str(opt_in).lower()},
    )


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_upload_pdf_and_docx_until_done(client: TestClient, tmp_path: Path, app_env: Path) -> None:
    pdf = fx.make_pdf(tmp_path / "essay.pdf", [fx.essay(2)])
    docx = fx.make_docx(tmp_path / "essay.docx", fx.essay(3).split("\n\n"))

    for path, expected_words in ((pdf, count_words(fx.essay(2))), (docx, count_words(fx.essay(3)) + 3)):
        r = upload(client, path)
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "queued" and body["delete_token"]
        sub_id = body["id"]

        # The inline runner finishes the job right after the response is sent.
        s = client.get(f"/api/submissions/{sub_id}").json()
        assert s["status"] == "done", s
        assert s["progress"] == 100
        assert s["word_count"] == expected_words
        assert s["delete_token"] is None  # only ever returned once
        assert s["created_at"].endswith(("Z", "+00:00"))

        t = client.get(f"/api/submissions/{sub_id}/text").json()
        assert count_words(t["clean_text"]) == expected_words
        # The upload itself is removed once the check is done.
        assert not any((app_env / "uploads" / sub_id).glob("original.*"))


def test_no_listing_of_other_peoples_checks(client: TestClient) -> None:
    paste(client, fx.essay(1))
    assert client.get("/api/submissions").status_code in (404, 405)


def test_paste_text(client: TestClient) -> None:
    r = paste(client, fx.essay(1))
    assert r.status_code == 202, r.text
    s = client.get(f"/api/submissions/{r.json()['id']}").json()
    assert s["status"] == "done" and s["word_count"] == count_words(fx.essay(1))


def test_idempotency_key_creates_one_submission(client: TestClient, tmp_path: Path) -> None:
    pdf = fx.make_pdf(tmp_path / "essay.pdf", [fx.essay(1)])
    key = uuid.uuid4().hex
    first = upload(client, pdf, key)
    second = upload(client, pdf, key)
    assert first.status_code == 202 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_rejects_fake_file_and_bad_input(client: TestClient, tmp_path: Path) -> None:
    fake = tmp_path / "virus.pdf"
    fake.write_bytes(b"MZ\x90\x00" + b"\x00" * 100)
    assert upload(client, fake).status_code == 415
    renamed = tmp_path / "essay.pdf"
    renamed.write_bytes(b"<html><script>alert(1)</script> just text pretending to be a pdf</html>")
    r = upload(client, renamed)
    assert r.status_code == 415 and "not a real PDF" in r.json()["detail"]
    assert client.post("/api/submissions", data={"idempotency_key": uuid.uuid4().hex}).status_code == 422
    assert client.get("/api/submissions/not-a-uuid").status_code == 404
    assert client.get("/api/submissions/00000000-0000-0000-0000-000000000000").status_code == 404


def test_word_limit(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from api.config import get_settings

    monkeypatch.setenv("MAX_WORDS", "50")
    get_settings.cache_clear()
    r = paste(client, fx.essay(1))
    s = client.get(f"/api/submissions/{r.json()['id']}").json()
    assert s["status"] == "failed" and "limit" in s["error"]


def test_flags_stored_and_returned(client: TestClient, tmp_path: Path) -> None:
    from tests.engine.test_flags import ORIGINAL, _tampered_docx

    sub_id = upload(client, _tampered_docx(tmp_path / "t.docx")).json()["id"]
    s = client.get(f"/api/submissions/{sub_id}").json()
    assert s["status"] == "done"
    assert {f["type"]: f["count"] for f in s["flags"]} == {
        "lookalike_characters": 4,
        "invisible_characters": 1,
        "hidden_text_vanish": 15,
        "hidden_text_color": 16,
        "hidden_text_tiny": 8,
    }
    flags = client.get(f"/api/submissions/{sub_id}/flags").json()
    assert flags[0]["type"] == "lookalike_characters" and len(flags[0]["locations"]) == 4
    text = client.get(f"/api/submissions/{sub_id}/text").json()["clean_text"]
    assert text.startswith(ORIGINAL)


def test_delete_needs_the_token(client: TestClient, tmp_path: Path, app_env: Path) -> None:
    body = upload(client, fx.make_pdf(tmp_path / "d.pdf", [fx.essay(1)])).json()
    sub_id, token = body["id"], body["delete_token"]
    assert client.delete(f"/api/submissions/{sub_id}").status_code == 403
    assert client.delete(f"/api/submissions/{sub_id}", headers={"X-Delete-Token": "wrong"}).status_code == 403
    assert client.delete(f"/api/submissions/{sub_id}", headers={"X-Delete-Token": token}).status_code == 200
    assert not (app_env / "uploads" / sub_id).exists()
    assert client.get(f"/api/submissions/{sub_id}").status_code == 404


def test_rate_limit_and_full_queue(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from api.config import get_settings

    monkeypatch.setenv("CHECKS_PER_IP_PER_HOUR", "2")
    get_settings.cache_clear()
    assert paste(client, fx.essay(1)).status_code == 202
    assert paste(client, fx.essay(2)).status_code == 202
    r = paste(client, fx.essay(3))
    assert r.status_code == 429 and "per hour" in r.json()["detail"]

    monkeypatch.setenv("CHECKS_PER_IP_PER_HOUR", "0")
    monkeypatch.setenv("MAX_QUEUE", "0")
    get_settings.cache_clear()
    assert paste(client, fx.essay(3)).status_code == 503


def test_queue_endpoint(client: TestClient) -> None:
    q = client.get("/api/queue").json()
    assert q == {"running": 0, "queued": 0, "max_concurrent": 3}


def test_retention_deletes_old_checks_but_keeps_repository_copy(client: TestClient) -> None:
    from datetime import timedelta

    from api.db import get_sessionmaker
    from api.models import SourceRow, Submission, utcnow
    from worker.maintenance import delete_expired

    sid = paste(client, fx.essay(2)).json()["id"]
    with get_sessionmaker()() as db:
        sub = db.get(Submission, sid)
        sub.created_at = utcnow() - timedelta(days=40)
        db.commit()
    assert delete_expired() == 1
    assert client.get(f"/api/submissions/{sid}").status_code == 404
    with get_sessionmaker()() as db:
        repo = db.query(SourceRow).filter(SourceRow.type == "submission").one()
        assert repo.submission_id is None and "Submitted to" in repo.title
