"""Phase 1 acceptance: PDF, DOCX and scanned PDF produce clean text with the right word count."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.extract import (
    ExtractionError,
    FileKind,
    UnsupportedFileType,
    count_words,
    detect_file_type,
    extract_document,
    normalize_text,
)
from engine.extract.normalize import words
from engine.extract.ocr import TesseractOCR
from tests import fixtures as fx

ESSAY = fx.essay(3)
ESSAY_WORDS = count_words(ESSAY)

needs_tesseract = pytest.mark.skipif(not TesseractOCR().available(), reason="Tesseract OCR is not installed")


# ---------------------------------------------------------------- word counting


def test_count_words_known_value() -> None:
    assert ESSAY_WORDS == 3 * sum(len(s.split()) for s in fx.SENTENCES)
    # It's | a | well-known | fact | isn't | it
    assert count_words("It's a well-known fact, isn't it?") == 6
    assert count_words("") == 0


def test_count_words_urdu_with_diacritics() -> None:
    # "Pakistan is a beautiful country" with a zabar on the first letter of khoobsurat
    assert count_words("پاکستان ایک خَوبصورت ملک ہے") == 5


def test_normalize_text() -> None:
    raw = "Hello   world\r\nthis is an exam-\nple text.\n\n\n\nNew  para"
    assert normalize_text(raw) == "Hello world\nthis is an example text.\n\nNew para"


# ---------------------------------------------------------------- type detection


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"%PDF-1.7\n...", FileKind.PDF),
        (b"{\\rtf1\\ansi hello}", FileKind.RTF),
        ("plain text, اردو".encode(), FileKind.TXT),
    ],
)
def test_detect_by_magic_bytes(data: bytes, kind: FileKind) -> None:
    assert detect_file_type(data) is kind


def test_detect_rejects_binary_and_renamed_files(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedFileType):
        detect_file_type(b"\x89PNG\r\n\x1a\n\x00\x00\x00")  # an image renamed to .pdf
    with pytest.raises(UnsupportedFileType):
        detect_file_type(b"MZ\x90\x00\x03\x00\x00\x00")  # a Windows .exe
    with pytest.raises(UnsupportedFileType):
        detect_file_type(b"")


def test_detect_office_formats(tmp_path: Path) -> None:
    docx = fx.make_docx(tmp_path / "a.docx", ["Hello"])
    odt = fx.make_odt(tmp_path / "a.odt", ["Hello"])
    assert detect_file_type(docx.read_bytes()) is FileKind.DOCX
    assert detect_file_type(odt.read_bytes()) is FileKind.ODT


# ---------------------------------------------------------------- extraction


def test_extract_pdf_word_count(tmp_path: Path) -> None:
    pages = [fx.essay(2), fx.essay(1)]
    pdf = fx.make_pdf(tmp_path / "essay.pdf", pages)
    doc = extract_document(pdf, FileKind.PDF)
    assert len(doc.pages) == 2
    assert doc.ocr_page_count == 0
    assert count_words(doc.text) == sum(count_words(p) for p in pages)
    assert words(doc.text) == words(" ".join(pages))  # same words, same order
    # Offsets map points at each page's text.
    for off, page in zip(doc.page_offsets, doc.pages, strict=True):
        assert doc.text[int(off["start"]) : int(off["end"])] == page.text


def test_extract_docx_word_count_with_table(tmp_path: Path) -> None:
    paragraphs = ESSAY.split("\n\n")
    table = [["District", "Yield"], ["Multan", "Low"]]
    path = fx.make_docx(tmp_path / "essay.docx", paragraphs, table)
    doc = extract_document(path, FileKind.DOCX)
    heading_words = count_words("Climate and Farming")
    table_words = 4
    assert count_words(doc.text) == ESSAY_WORDS + heading_words + table_words
    # Table rows stay on their own line; cell separators are normalised to a space.
    assert "\nMultan Low" in doc.text


def test_extract_odt_rtf_txt(tmp_path: Path) -> None:
    paragraphs = ESSAY.split("\n\n")
    odt = extract_document(fx.make_odt(tmp_path / "e.odt", paragraphs), FileKind.ODT)
    rtf = extract_document(fx.make_rtf(tmp_path / "e.rtf", ESSAY), FileKind.RTF)
    txt_path = tmp_path / "e.txt"
    txt_path.write_text(ESSAY, encoding="utf-8")
    txt = extract_document(txt_path, FileKind.TXT)
    for doc in (odt, rtf, txt):
        assert count_words(doc.text) == ESSAY_WORDS


def test_damaged_pdf_gives_clear_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4\nthis is not really a pdf")
    with pytest.raises(ExtractionError):
        extract_document(bad, FileKind.PDF)


class _NoOCR:
    def available(self) -> bool:
        return False

    def image_to_text(self, image):  # type: ignore[no-untyped-def]
        raise AssertionError("should not be called")


def test_scanned_pdf_without_ocr_engine_fails_clearly(tmp_path: Path) -> None:
    pdf = fx.make_scanned_pdf(tmp_path / "scan.pdf", [fx.essay(1)])
    with pytest.raises(ExtractionError, match="OCR"):
        extract_document(pdf, FileKind.PDF, ocr=_NoOCR())


@needs_tesseract
def test_extract_scanned_pdf_with_ocr(tmp_path: Path) -> None:
    pages = [fx.essay(1), fx.essay(1)]
    pdf = fx.make_scanned_pdf(tmp_path / "scan.pdf", pages)
    doc = extract_document(pdf, FileKind.PDF)
    assert doc.ocr_page_count == 2
    expected = [w.lower() for w in words(" ".join(pages))]
    got = [w.lower() for w in words(doc.text)]
    # OCR is not perfect: require the word count within 2 % and 95 % of words recognised.
    assert abs(len(got) - len(expected)) <= max(2, len(expected) // 50)
    recognised = sum(1 for w in set(expected) if w in set(got))
    assert recognised / len(set(expected)) >= 0.95
