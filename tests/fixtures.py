"""Build test documents in code so the expected text and word count are known exactly."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

SENTENCES = [
    "Climate change is one of the most serious problems facing farmers in Pakistan today.",
    "Rising temperatures reduce wheat yields across Punjab and Sindh every year.",
    "Many villages now depend on groundwater because canal water arrives late.",
    "Researchers recommend drought tolerant seeds and better irrigation scheduling.",
    "Government support for small farmers remains limited and uneven between districts.",
    "Students who study agriculture should learn both field methods and data analysis.",
]


def essay(paragraphs: int = 3) -> str:
    return "\n\n".join(" ".join(SENTENCES) for _ in range(paragraphs))


def make_pdf(path: Path, pages: list[str]) -> Path:
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        rect = fitz.Rect(56, 56, 539, 786)
        overflow = page.insert_textbox(rect, text, fontsize=11, fontname="helv")
        assert overflow >= 0, "test text does not fit on the page"
    doc.save(path)
    doc.close()
    return path


def make_scanned_pdf(path: Path, pages: list[str], dpi: int = 200) -> Path:
    """Render text pages to images and build a PDF that has NO text layer."""
    import fitz

    src = fitz.open()
    for text in pages:
        page = src.new_page(width=595, height=842)
        page.insert_textbox(fitz.Rect(56, 56, 539, 786), text, fontsize=14, fontname="helv")
    out = fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        img_page = out.new_page(width=page.rect.width, height=page.rect.height)
        img_page.insert_image(img_page.rect, stream=pix.tobytes("png"))
    out.save(path)
    src.close()
    out.close()
    return path


def make_docx(path: Path, paragraphs: list[str], table: list[list[str]] | None = None) -> Path:
    import docx

    d = docx.Document()
    d.add_heading("Climate and Farming", level=1)
    for p in paragraphs:
        d.add_paragraph(p)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, val in enumerate(row):
                t.cell(r, c).text = val
    d.save(str(path))
    return path


def make_odt(path: Path, paragraphs: list[str]) -> Path:
    body = "".join(f"<text:p>{p}</text:p>" for p in paragraphs)
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">'
        f"<office:body><office:text>{body}</office:text></office:body></office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        zf.writestr("content.xml", content)
    path.write_bytes(buf.getvalue())
    return path


def make_rtf(path: Path, text: str) -> Path:
    body = text.replace("\n\n", "\\par\\par ").replace("\n", "\\par ")
    path.write_bytes(("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Arial;}}\\f0\\fs22 " + body + "}").encode("latin-1"))
    return path
