"""Raw text extractors per file format. PDF and DOCX extractors leave out hidden
text and return findings for it; ODT/RTF/TXT have no hidden-text detection yet."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from engine.flags.docx_hidden import extract_docx
from engine.flags.pdf_hidden import extract_pdf_page
from engine.flags.types import Finding

# ---------------------------------------------------------------- PDF

PageImage = Callable[[], Image.Image]


RawPage = tuple[str, list[Finding], PageImage]


def pdf_pages_pdfplumber(path: Path, dpi: int) -> list[RawPage]:
    """Return (visible_text, hidden_text_findings, render_page) for each page.
    pdfplumber is MIT licensed; it exposes glyph colours, sizes and positions."""
    import pdfplumber

    out: list[RawPage] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            res = extract_pdf_page(page, page.page_number)
            out.append((res.text, res.findings, _pdfplumber_renderer(path, page.page_number - 1, dpi)))
    return out


def _pdfplumber_renderer(path: Path, index: int, dpi: int) -> PageImage:
    def render() -> Image.Image:
        import pdfplumber

        from engine.pdfium_lock import PDFIUM_LOCK

        # to_image() renders with PDFium, which is not thread-safe.
        with PDFIUM_LOCK, pdfplumber.open(path) as pdf:
            return pdf.pages[index].to_image(resolution=dpi).original.copy()

    return render


def pdf_pages_pymupdf(path: Path, dpi: int) -> list[RawPage]:
    """Optional backend (PyMuPDF is AGPL-3.0; enabled only with ENABLE_PYMUPDF=true).
    It does not detect hidden PDF text; use the default pdfplumber backend for that."""
    import fitz  # PyMuPDF

    out: list[RawPage] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            out.append((page.get_text("text"), [], _pymupdf_renderer(path, i, dpi)))
    return out


def _pymupdf_renderer(path: Path, index: int, dpi: int) -> PageImage:
    def render() -> Image.Image:
        import fitz

        with fitz.open(path) as doc:
            pix = doc[index].get_pixmap(dpi=dpi)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    return render


# ---------------------------------------------------------------- DOCX


def docx_text(path: Path) -> tuple[str, list[Finding]]:
    """Body paragraphs and tables in document order, without hidden runs.
    See engine/flags/docx_hidden.py for what counts as hidden."""
    res = extract_docx(path)
    return res.text, res.findings


# ---------------------------------------------------------------- ODT

_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"


def odt_text(path: Path) -> str:
    """Parse content.xml with the standard library (no extra dependency)."""
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("content.xml"))
    blocks: list[str] = []
    for el in root.iter():
        if el.tag in (f"{{{_TEXT_NS}}}p", f"{{{_TEXT_NS}}}h"):
            blocks.append(_odt_inline(el))
    return "\n".join(blocks)


def _odt_inline(el: ET.Element) -> str:
    parts: list[str] = [el.text or ""]
    for child in el:
        name = child.tag.rsplit("}", 1)[-1]
        if name == "s":
            parts.append(" " * int(child.get(f"{{{_TEXT_NS}}}c", "1")))
        elif name == "tab":
            parts.append("\t")
        elif name == "line-break":
            parts.append("\n")
        elif name in ("note", "annotation"):
            pass  # footnote/comment bodies are not part of the running text
        else:
            parts.append(_odt_inline(child))
        parts.append(child.tail or "")
    return "".join(parts)


# ---------------------------------------------------------------- RTF / TXT


def rtf_text(data: bytes) -> str:
    from striprtf.striprtf import rtf_to_text

    return rtf_to_text(data.decode("latin-1"), errors="ignore")


def plain_text(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def image_from_bytes(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))
