"""Render the report HTML and print it to PDF.

Chromium runs with JavaScript disabled and every network request blocked, so the
user's text inside the HTML can never make the renderer fetch anything.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))


def render_report(context: dict[str, Any]) -> str:
    return _env.get_template("report.html").render(**context)


def render_footer(context: dict[str, Any]) -> str:
    return _env.get_template("footer.html").render(**context)


def qr_data_uri(url: str) -> str:
    import qrcode

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def html_to_pdf(html: str, footer_html: str) -> bytes:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(java_script_enabled=False, offline=True)
            page = context.new_page()
            page.route("**/*", lambda route: route.abort() if not route.request.url.startswith("data:") else route.continue_())
            page.set_content(html, wait_until="load")
            # Page size, margins and the header/footer bar (brand, "Page X of Y - <section>",
            # submission ID) come from the template's CSS @page rules.
            return page.pdf(print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def pdf_page_count(pdf: bytes) -> int:
    import pypdfium2

    from engine.pdfium_lock import PDFIUM_LOCK

    with PDFIUM_LOCK:
        doc = pypdfium2.PdfDocument(pdf)
        try:
            return len(doc)
        finally:
            doc.close()
