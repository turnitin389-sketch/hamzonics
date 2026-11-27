"""PDF report: all sections present, highlights align with text offsets, page header/footer,
QR verification, tampered PDFs fail."""

from __future__ import annotations

import hashlib
import html
import io
import re

import pytest
from fastapi.testclient import TestClient

from tests.api.test_similarity_api import _paste, _seed_corpus, mixed_text
from tests.engine.test_ai import AI, FakeScorer


SECTIONS = [
    "Document Details",
    "Overall Similarity",
    "Match Groups",
    "Top Sources",
    "Integrity Flags",
    "detected as AI",
]


@pytest.fixture()
def fake_ai(monkeypatch):  # type: ignore[no-untyped-def]
    from api.config import get_settings

    monkeypatch.setenv("ENABLE_AI", "true")
    monkeypatch.setenv("AI_MIN_WORDS", "50")
    get_settings.cache_clear()
    monkeypatch.setattr("engine.ai.model.get_scorer", lambda *a, **k: FakeScorer())


def _ai_text() -> str:
    return mixed_text() + "\n\n" + " ".join([AI] * 6)


def test_highlights_align_with_text_offsets(client: TestClient, fake_ai) -> None:  # type: ignore[no-untyped-def]
    """Removing the tags from the rendered document gives back the clean text exactly."""
    from api.db import get_sessionmaker
    from api.models import DocumentText, Submission
    from engine.report import render_report
    from worker.report import build_context

    _seed_corpus()
    sid = _paste(client, _ai_text())["id"]
    with get_sessionmaker()() as db:
        sub = db.get(Submission, sid)
        assert sub.ai_percent and sub.ai_percent > 0
        clean = db.get(DocumentText, sid).clean_text
        page = render_report(build_context(db, sub))
    docs = re.findall(r'<div class="doc" dir="auto"[^>]*>(.*?)</div>\n</section>', page, re.S)
    assert len(docs) == 2, "similarity and AI documents expected"
    for body in docs:
        assert "<mark" in body
        body = re.sub(r'<span class="badge">.*?</span></span>', "", body, flags=re.S)
        assert html.unescape(re.sub(r"<[^>]+>", "", body)) == clean


def test_pdf_pages_header_and_verification(client: TestClient, fake_ai) -> None:  # type: ignore[no-untyped-def]
    import pdfplumber

    from worker.report import display_id

    _seed_corpus()
    sid = _paste(client, _ai_text())["id"]

    r = client.get(f"/api/submissions/{sid}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    pdf_bytes = r.content
    assert pdf_bytes.startswith(b"%PDF-")

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        texts = [p.extract_text() or "" for p in pdf.pages]
        cover_links = [h.get("uri") for h in pdf.pages[0].hyperlinks]
    n = len(texts)
    assert n >= 6
    joined = "\n".join(texts)
    for title in SECTIONS:
        assert title in joined, f"missing section {title}"
    for i, t in enumerate(texts, start=1):
        assert t.count(f"Page {i} of {n}") >= 2, f"header/footer page number missing on page {i}"
        assert t.count("Reports") >= 2
        assert display_id(sid) in t, f"submission id missing on page {i}"
    assert cover_links == []
    assert "Internet" in joined and "en.wikipedia.org" in joined

    # Public verification.
    info = client.get(f"/api/verify/{sid}").json()
    assert info["sha256"] == hashlib.sha256(pdf_bytes).hexdigest()
    assert info["pages"] == n and info["ai_percent"] is not None
    ok = client.post(f"/api/verify/{sid}", files={"file": ("r.pdf", pdf_bytes, "application/pdf")}).json()
    assert ok["authentic"] is True
    tampered = pdf_bytes[:-10] + b"0" * 10
    bad = client.post(f"/api/verify/{sid}", files={"file": ("r.pdf", tampered, "application/pdf")}).json()
    assert bad["authentic"] is False
    assert client.get("/api/verify/00000000-0000-0000-0000-000000000000").status_code == 404


def test_ai_endpoint(client: TestClient, fake_ai) -> None:  # type: ignore[no-untyped-def]
    sid = _paste(client, _ai_text())["id"]
    ai = client.get(f"/api/submissions/{sid}/ai").json()
    assert ai["available"] and ai["percent"] > 0 and ai["model"] == "fake"
    seg = next(s for s in ai["segments"] if s["level"] == "ai")
    text = client.get(f"/api/submissions/{sid}/text").json()["clean_text"]
    assert "Moreover" in text[seg["start"] : seg["end"]]


def test_ai_off_says_why(client: TestClient) -> None:
    from tests.engine.test_similarity import ORIGINAL_ESSAY

    sid = _paste(client, ORIGINAL_ESSAY)["id"]
    ai = client.get(f"/api/submissions/{sid}/ai").json()
    assert ai["available"] is False and "switched off" in ai["message"]


def test_download_variants_refresh_legacy_layout(client: TestClient) -> None:
    import fitz

    from tests.engine.test_similarity import ORIGINAL_ESSAY
    from worker.report import part_report_path, pdf_artifact_is_current, pdf_artifact_marker_path

    sid = _paste(client, ORIGINAL_ESSAY)["id"]
    route = f"/api/submissions/{sid}/report.pdf"
    for part in ("similarity", "ai"):
        old = part_report_path(sid, part)
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_bytes(b"legacy report")
        pdf = client.get(route, params={"part": part})
        assert pdf.status_code == 200
        assert f"turnitin-reports-{part}.pdf" in pdf.headers["content-disposition"]
        assert pdf_artifact_is_current(old)
        assert old.read_bytes() == pdf.content
        with fitz.open(stream=pdf.content, filetype="pdf") as doc:
            assert len(doc) >= 2
            assert doc.metadata["author"] == "Turnitin Reports"
            assert all(p.rect == fitz.Rect(0, 0, 612, 792) for p in doc)
            if part == "ai":
                assert "AI Writing score unavailable" in doc[1].get_text()
                assert "0% detected as AI" not in doc[1].get_text()
            else:
                assert "Overall Similarity" in doc[1].get_text()
        assert client.get(route, params={"part": part}).content == pdf.content

    full = client.get(route)
    assert full.status_code == 200
    path = part_report_path(sid, "ai").with_name(f"{sid}.pdf")
    pdf_artifact_marker_path(path).unlink()
    assert client.get(route).status_code == 200
    assert pdf_artifact_is_current(path)


def test_qr_encodes_verify_url() -> None:
    from engine.report import qr_data_uri
    from worker.report import pct_label, verify_url

    url = verify_url("abc")
    assert url.endswith("/verify/abc")
    assert qr_data_uri(url).startswith("data:image/png;base64,")
    assert qr_data_uri(url) == qr_data_uri(url)
    assert [pct_label(x) for x in (0, 0.4, 1.0, 6.5, 99.6)] == ["0%", "<1%", "1%", "7%", "100%"]
