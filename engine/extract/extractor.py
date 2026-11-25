"""Top-level extraction: file -> ExtractedDocument (clean text + page offsets + integrity flags).

Per page:
1. format extractor returns the visible text and findings for hidden text it left out;
2. pages whose text layer has fewer than `ocr_min_chars` characters are scanned/image-only
   and go to OCR (flagged as image_only_pages);
3. layout normalisation, then character cleaning (invisible + lookalike characters).
The resulting clean text is what every later check runs on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from engine.extract import formats
from engine.extract.detect import FileKind
from engine.extract.normalize import normalize_text
from engine.extract.ocr import OCREngine, TesseractOCR
from engine.extract.types import ExtractedDocument, PageText
from engine.flags import Finding, aggregate, clean_characters

ProgressFn = Callable[[int, int], None]


class ExtractionError(RuntimeError):
    """A problem with the document itself; the message is shown to the user."""


class _CallbackError(Exception):
    """An error raised by the caller's progress callback (e.g. a database problem).
    It is NOT a problem with the document and must not be reported as one."""


def _wrap_progress(progress: ProgressFn | None) -> ProgressFn | None:
    if progress is None:
        return None

    def call(done: int, total: int) -> None:
        try:
            progress(done, total)
        except Exception as exc:
            raise _CallbackError() from exc

    return call


@dataclass(frozen=True)
class ExtractOptions:
    pdf_backend: str = "pdfplumber"
    ocr_languages: str = "eng+urd"
    ocr_min_chars: int = 25
    ocr_dpi: int = 300


@dataclass
class _Page:
    number: int
    text: str  # normalised, before character cleaning
    ocr: bool
    findings: list[Finding]


def extract_document(
    path: Path,
    kind: FileKind | str,
    options: ExtractOptions | None = None,
    ocr: OCREngine | None = None,
    progress: ProgressFn | None = None,
) -> ExtractedDocument:
    options = options or ExtractOptions()
    kind = FileKind(kind)
    ocr = ocr or TesseractOCR(options.ocr_languages)
    progress = _wrap_progress(progress)

    try:
        if kind is FileKind.PDF:
            pages = _extract_pdf(path, options, ocr, progress)
        else:
            raw, findings = _extract_flat(path, kind)
            pages = [_Page(1, normalize_text(raw), False, findings)]
            if progress:
                progress(1, 1)
    except ExtractionError:
        raise
    except _CallbackError as exc:  # the caller's problem: re-raise the original error unchanged
        assert exc.__cause__ is not None
        raise exc.__cause__ from None
    except Exception as exc:  # parser errors on damaged files
        raise ExtractionError(f"Could not read this {kind.value.upper()} file. It may be damaged or password-protected.") from exc

    return _assemble(kind.value, pages)


def _extract_flat(path: Path, kind: FileKind) -> tuple[str, list[Finding]]:
    if kind is FileKind.DOCX:
        return formats.docx_text(path)
    if kind is FileKind.ODT:
        return formats.odt_text(path), []
    data = path.read_bytes()
    if kind is FileKind.RTF:
        return formats.rtf_text(data), []
    return formats.plain_text(data), []


def _extract_pdf(path: Path, options: ExtractOptions, ocr: OCREngine, progress: ProgressFn | None) -> list[_Page]:
    _check_pdf_not_encrypted(path)
    if options.pdf_backend == "pymupdf":
        raw_pages = formats.pdf_pages_pymupdf(path, options.ocr_dpi)
    else:
        raw_pages = formats.pdf_pages_pdfplumber(path, options.ocr_dpi)
    if not raw_pages:
        raise ExtractionError("The PDF has no pages")

    total = len(raw_pages)
    pages: list[_Page] = []
    for i, (text, findings, render) in enumerate(raw_pages, start=1):
        clean = normalize_text(text)
        used_ocr = False
        if len(clean.replace("\n", "").replace(" ", "")) < options.ocr_min_chars:
            if not ocr.available():
                raise ExtractionError(
                    "This PDF contains scanned pages, but OCR (Tesseract) is not installed on the server."
                )
            ocr_text = normalize_text(ocr.image_to_text(render()))
            if len(ocr_text) > len(clean):
                clean, used_ocr = ocr_text, True
                findings = findings + [Finding("image_only_pages", 1, i, detail="read with OCR")]
        pages.append(_Page(i, clean, used_ocr, findings))
        if progress:
            progress(i, total)
    return pages


def _check_pdf_not_encrypted(path: Path) -> None:
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfminer.pdfparser import PDFSyntaxError

    import pdfplumber

    try:
        with pdfplumber.open(path):
            pass
    except PDFPasswordIncorrect as exc:
        raise ExtractionError("This PDF is password-protected. Remove the password and upload again.") from exc
    except PDFSyntaxError as exc:
        raise ExtractionError("This PDF is damaged and cannot be read.") from exc


def _assemble(kind: str, pages: list[_Page]) -> ExtractedDocument:
    """Clean each page's characters, join pages with a blank line, record each page's
    char range, and shift character-level finding offsets into document coordinates."""
    parts: list[str] = []
    offsets: list[dict[str, int | bool]] = []
    out_pages: list[PageText] = []
    findings: list[Finding] = []
    pos = 0
    for page in pages:
        cleaned = clean_characters(page.text, page.number)
        if parts:
            parts.append("\n\n")
            pos += 2
        start = pos
        parts.append(cleaned.text)
        pos += len(cleaned.text)
        offsets.append({"page": page.number, "start": start, "end": pos, "ocr": page.ocr})
        out_pages.append(PageText(page.number, cleaned.text, page.ocr))
        findings.extend(page.findings)
        for f in cleaned.findings:
            assert f.start is not None and f.end is not None
            findings.append(replace(f, start=f.start + start, end=f.end + start))
    return ExtractedDocument(
        kind=kind, text="".join(parts), pages=out_pages, page_offsets=offsets, flags=aggregate(findings)
    )
