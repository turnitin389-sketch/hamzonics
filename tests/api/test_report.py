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


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


needs_chromium = pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium is not installed")

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


@needs_chromium
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


def test_qr_encodes_verify_url() -> None:
    from engine.report import qr_data_uri
    from worker.report import pct_label, verify_url

    url = verify_url("abc")
    assert url.endswith("/verify/abc")
    assert qr_data_uri(url).startswith("data:image/png;base64,")
    assert qr_data_uri(url) == qr_data_uri(url)
    assert [pct_label(x) for x in (0, 0.4, 1.0, 6.5, 99.6)] == ["0%", "<1%", "1%", "7%", "100%"]
