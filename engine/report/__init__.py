"""PDF report rendering: Jinja2 HTML templates -> PDF with headless Chromium (Playwright)."""

from engine.report.composer import build_pdf_report
from engine.report.render import html_to_pdf, pdf_page_count, qr_data_uri, render_footer, render_report

__all__ = ["build_pdf_report", "html_to_pdf", "pdf_page_count", "qr_data_uri", "render_footer", "render_report"]
