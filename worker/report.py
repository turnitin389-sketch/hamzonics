"""Build the PDF report for a finished check and store its SHA-256.

Sections (same numbers as the online report, from api.services):
  1. Cover: document details
  2. Similarity overview: overall %, filters, match groups, source types, integrity flags
  3. Top sources: numbered, coloured, typed
  4. Document with similarity highlights (colour = match group, badge = source number)
  5. AI-writing overview
  6. Document with AI highlights
  7. How to read this report
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models import DocumentText, ReportRow, Submission, as_utc, utcnow
from api.services import ai_view, similarity_view
from engine.report import build_pdf_report, html_to_pdf, pdf_page_count, qr_data_uri, render_footer, render_report

# Source badge and pill colours, used consistently in the list and margins.
SOURCE_PALETTE = [
    ("#cb1476", "#fedce7"),  # Magenta / Light Pink
    ("#225ec6", "#d6e5fb"),  # Blue / Light Blue
    ("#007546", "#c1ecdf"),  # Green / Light Mint
    ("#7533e7", "#ecdffe"),  # Purple / Light Lavender
]
SOURCE_COLORS = [c[0] for c in SOURCE_PALETTE]
TYPE_LABEL = {"corpus": "Publication", "web": "Internet", "submission": "Submitted works"}
TYPE_PILL = {"corpus": "#ecdffe", "web": "#fedce7", "submission": "#c1ecdf"}
# key, label, highlight colour, icon background colour, description
GROUPS = [
    ("not_cited_or_quoted", "Not Cited or Quoted", "#f59a9a", "#f86371",
     "Matches with neither in-text citation nor quotation marks"),
    ("missing_quotations", "Missing Quotations", "#fbbd7c", "#f68e4a",
     "Matches that are still very similar to source material"),
    ("missing_citation", "Missing Citation", "#f7e08a", "#f4e4aa",
     "Matches that have quotation marks, but no in-text citation"),
    ("cited_and_quoted", "Cited and Quoted", "#a9e2cf", "#c1ecdf",
     "Matches with in-text citation present, but no quotation marks"),
]
GROUP_BY_KEY = {g[0]: g for g in GROUPS}
BIB_COLOR = ("#d9dee6", "#8a94a6")
AI_COLORS = {"ai": ("#cceef5", "#00849b"), "possible": ("#e8dff8", "#7b52c7")}
FLAG_TEXT = {
    "lookalike_characters": ("Look-alike characters", "characters",
                             "Letters from other alphabets that look like English letters; replaced before checking."),
    "invisible_characters": ("Invisible characters", "characters", "Zero-width and similar characters; removed before checking."),
    "hidden_text_vanish": ("Hidden text", "characters", "Text marked hidden in Word; left out of the check."),
    "hidden_text_color": ("Text the same colour as the background", "characters",
                          "For example white text on a white page; left out of the check."),
    "hidden_text_tiny": ("Tiny text (under 4 pt)", "characters", "Text too small to read; left out of the check."),
    "text_outside_page": ("Text outside the page", "characters", "Text placed where it cannot be seen; left out of the check."),
    "image_only_pages": ("Image-only pages", "pages", "Pages without a text layer; read with OCR."),
}
MAX_FLAG_EXAMPLES = 8
_REPORT_PACKAGE = Path(__file__).resolve().parent.parent / "engine" / "report"
_REPORT_LAYOUT_REVISION = "hamzonics-v2"
_WORDMARK = (
    b"<svg xmlns='http://www.w3.org/2000/svg' width='150' height='32' viewBox='0 0 150 32'>"
    b"<rect x='1' y='4' width='24' height='24' rx='6' fill='#1e556e'/>"
    b"<path d='M8 10v12m10-12v12M8 16h10' fill='none' stroke='white' stroke-width='2'/>"
    b"<text x='34' y='22' font-family='Arial,Helvetica,sans-serif' font-size='18' "
    b"font-weight='bold' fill='#17394b'>Hamzonics</text></svg>"
)
LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode(_WORDMARK).decode("ascii")


def get_logo_uri() -> str:
    return LOGO_URI


def _fmt(dt: datetime | None, tz: ZoneInfo) -> str:
    if dt is None:
        return "–"
    return as_utc(dt).astimezone(tz).strftime("%b %d, %Y, %I:%M %p %Z").replace(" 0", " ")


def pct_label(p: float) -> str:
    """Whole percent like other checkers; '<1%' for small non-zero values."""
    if p <= 0:
        return "0%"
    if p < 1:
        return "<1%"
    return f"{int(p + 0.5)}%"


def size_label(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def verify_url(submission_id: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/verify/{submission_id}"


def display_id(submission_id: str) -> str:
    return submission_id


def sources_searched_text() -> str:
    s = get_settings()
    names = {n.strip() for n in s.free_sources.split(",") if n.strip()}
    labels = {
        "wikipedia": f"Wikipedia ({s.wikipedia_langs})", "arxiv": "arXiv", "europepmc": "Europe PMC (open-access full text)",
        "openalex": "OpenAlex (250M+ scholarly works)", "crossref": "Crossref", "semanticscholar": "Semantic Scholar",
        "core": "CORE (open-access full text)",
    }
    parts = [labels[n] for n in labels if n in names and (n != "core" or s.core_api_key)]
    if s.serper_api_key or s.searxng_url or s.brave_api_key or (s.google_cse_key and s.google_cse_cx):
        parts.append("the public web (search engine results)")
    parts.append("earlier submissions to this service")
    return "; ".join(parts)


def source_display(src_type: str, title: str, url: str | None) -> str:
    if src_type == "web" and url:
        return urlparse(url).netloc or title
    return title


def _source_link(url: str | None) -> str | None:
    if not url or any(ord(char) < 32 or ord(char) == 127 for char in url):
        return None
    url = url.strip()
    try:
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not any(
            char.isspace() for char in parsed.netloc
        ):
            return url
    except ValueError:
        return None
    return None


def _highlight_segments(text: str, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split the original text in order, with earlier spans owning any shared characters."""
    out: list[dict[str, Any]] = []
    pos = 0
    for sp in sorted(spans, key=lambda s: s["start"]):
        start = max(pos, sp["start"])
        end = min(len(text), sp["end"])
        if start >= end:
            continue
        if start > pos:
            out.append({"text": text[pos:start]})
        out.append({**sp, "start": start, "end": end, "text": text[start:end]})
        pos = end
    if pos < len(text):
        out.append({"text": text[pos:]})
    return out


REPORT_PARTS = ("all", "similarity", "ai")


def build_context(db: Session, sub: Submission, part: str = "all") -> dict[str, Any]:
    settings = get_settings()
    tz = ZoneInfo(settings.report_timezone)
    doc = db.get(DocumentText, sub.id)
    assert doc is not None
    sim = similarity_view(db, sub)
    ai = ai_view(db, sub)
    text = doc.clean_text

    color_of: dict[str, str] = {}
    number_of: dict[str, int] = {}
    sources = []
    for i, s in enumerate(sim.sources):
        badge_col, pill_col = SOURCE_PALETTE[i % len(SOURCE_PALETTE)]
        color_of[s.source_key] = badge_col
        number_of[s.source_key] = i + 1
        link_url = _source_link(s.url)
        sources.append({"number": i + 1, "color": badge_col, "title": source_display(s.type, s.title, link_url),
                        "full_title": s.title, "url": s.url, "link_url": link_url,
                        "type": s.type, "type_label": TYPE_LABEL.get(s.type, s.type),
                        "pill": pill_col, "words": s.words, "percent": s.percent,
                        "percent_label": pct_label(s.percent)})

    # Similarity highlights: colour by match group, badge = source number. A badge is
    # only shown where a new source starts, like a margin note.
    spans = []
    last_key = None
    for run in sorted(sim.runs, key=lambda r: r.start):
        g = GROUP_BY_KEY.get(run.group)
        bg, line = (g[2], g[3]) if g else BIB_COLOR
        badge = None if run.source_key == last_key else {"number": number_of[run.source_key],
                                                          "color": color_of[run.source_key], "icon": run.group}
        spans.append({"start": run.start, "end": run.end, "bg": bg, "line": line,
                      "group": run.group, "badge": badge})
        last_key = run.source_key
    sim_segments = _highlight_segments(text, spans)

    total = max(sim.total_words, 1)
    match_counts: dict[str, int] = {}
    prev = None
    for run in sorted(sim.runs, key=lambda r: r.start):
        key = (run.source_key, run.group)
        if key != prev:
            match_counts[run.group] = match_counts.get(run.group, 0) + 1
        prev = key
    groups = [
        {"key": key, "label": label, "bg": bg, "color": color, "help": help_text,
         "count": match_counts.get(key, 0), "words": sim.groups.get(key, 0),
         "percent_label": pct_label(100 * sim.groups.get(key, 0) / total) if sim.groups.get(key) else "0%"}
        for key, label, bg, color, help_text in GROUPS
    ]
    filtered = []
    if sim.exclude_bibliography:
        filtered.append("Bibliography")
    if sim.exclude_quotes:
        filtered.append("Quoted text")
    if sim.min_words:
        filtered.append(f"Matches under {sim.min_words} words")
    by_type = [
        {"key": "web", "label": "Internet sources", "percent_label": pct_label(sim.by_type.get("web", 0)).replace("<1%", "<1%")},
        {"key": "corpus", "label": "Publications", "percent_label": pct_label(sim.by_type.get("corpus", 0))},
        {"key": "submission", "label": "Submitted works (Student Papers)", "percent_label": pct_label(sim.by_type.get("submission", 0))},
    ]

    ai_spans = [{"start": s.start, "end": s.end, "bg": AI_COLORS[s.level][0], "line": AI_COLORS[s.level][1],
                 "badge": None, "level": s.level} for s in ai.segments if s.level in AI_COLORS]
    ai_segments = _highlight_segments(text, ai_spans)
    ai_ctx = {
        "available": ai.available,
        "message": ai.message,
        "percent": ai.percent,
        "percent_label": (pct_label(ai.percent) if ai.percent is not None else "–"),
        "low": ai.percent is not None and 0 < ai.percent < 20,
        "qualifying_words": f"{ai.qualifying_words:,}",
        "ai_words": f"{ai.ai_words:,}",
        "ai_segments_count": sum(1 for s in ai.segments if s.level == "ai"),
        "possible_segments_count": sum(1 for s in ai.segments if s.level == "possible"),
        "possible_words": f"{sum(s.word_end - s.word_start for s in ai.segments if s.level == 'possible'):,}",
        "model": ai.model,
        "threshold": f"{settings.ai_threshold * 100:g}",
    }

    flags = []
    for f in sub.flags:
        title, unit, help_text = FLAG_TEXT.get(f.type, (f.type, "items", ""))
        flags.append({"title": title, "unit": unit, "help": help_text, "count": f.count,
                      "examples": [{"page": loc.get("page"), "text": (loc.get("text") or "")[:120],
                                    "detail": loc.get("detail")} for loc in f.locations[:MAX_FLAG_EXAMPLES]],
                      "more": max(0, len(f.locations) - MAX_FLAG_EXAMPLES)})

    url = verify_url(sub.id)
    return {
        "part": part if part in REPORT_PARTS else "all",
        "app_name": "Hamzonics",
        "submission_id": sub.id,
        "display_id": display_id(sub.id),
        "author": "",
        "doc_num": "",
        "class_name": "",
        "institution": "",
        "filename": sub.original_filename,
        "file_size": size_label(sub.file_size),
        "submitted": _fmt(sub.created_at, tz),
        "generated": _fmt(utcnow(), tz),
        "word_count": f"{sub.word_count:,}",
        "char_count": f"{len(text):,}",
        "page_count": sub.page_count,
        "ocr_pages": sub.ocr_pages,
        "file_type": sub.file_type,
        "engine_version": sub.engine_version,
        "similarity": sim,
        "similarity_label": pct_label(sim.percent),
        "web_warning": sim.web_search_message,
        "logo_uri": get_logo_uri(),
        "sources": sources,
        "groups": groups,
        "filtered": filtered,
        "by_type": by_type,
        "sim_segments": sim_segments,
        "flags": flags,
        "ai": ai_ctx,
        "ai_segments": ai_segments,
        "clean_text": text,
        "source_pdf_path": sub.file_path if sub.file_type == "pdf" else None,
        "source_page_offsets": (doc.offsets or {}).get("pages", []),
        "verify_url": url,
        "verify_base": settings.public_base_url.rstrip("/"),
        "qr_data_uri": qr_data_uri(url),
        "sources_searched": sources_searched_text(),
    }


def pdf_artifact_marker_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".layout")


def _layout_marker(mtime_ns: int, size: int) -> bytes:
    return f"{_REPORT_LAYOUT_REVISION}\n{mtime_ns}\n{size}\n".encode("ascii")


def pdf_artifact_is_current(path: Path) -> bool:
    """Check the layout revision, artifact identity and installed asset timestamps."""
    try:
        pdf_info = path.stat()
        marker = pdf_artifact_marker_path(path).read_bytes()
    except FileNotFoundError:
        return False
    if marker != _layout_marker(pdf_info.st_mtime_ns, pdf_info.st_size):
        return False

    layout_files = [
        Path(__file__),
        *_REPORT_PACKAGE.glob("*.py"),
        *_REPORT_PACKAGE.rglob("*.html"),
        *_REPORT_PACKAGE.rglob("*.ttf"),
        *_REPORT_PACKAGE.rglob("*.otf"),
        *_REPORT_PACKAGE.rglob("*.woff*"),
    ]
    for source in layout_files:
        try:
            if source.stat().st_mtime_ns > pdf_info.st_mtime_ns:
                return False
        except FileNotFoundError:
            continue
    return True


def _write_report(path: Path, pdf: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent, prefix=f".{path.name}.") as folder:
        tmp = Path(folder) / path.name
        marker_path = pdf_artifact_marker_path(path)
        tmp_marker = Path(folder) / marker_path.name
        tmp.write_bytes(pdf)
        info = tmp.stat()
        tmp_marker.write_bytes(_layout_marker(info.st_mtime_ns, info.st_size))
        tmp.replace(path)
        tmp_marker.replace(marker_path)


def generate_report(db: Session, sub: Submission) -> ReportRow:
    ctx = build_context(db, sub)
    pdf = build_pdf_report(ctx)
    folder = Path(get_settings().report_dir)
    path = folder / f"{sub.id}.pdf"
    _write_report(path, pdf)
    row = db.scalar(select(ReportRow).where(ReportRow.submission_id == sub.id))
    if row is None:
        row = ReportRow(submission_id=sub.id, pdf_path=str(path), sha256="", pages=0)
        db.add(row)
    row.pdf_path, row.sha256, row.pages, row.created_at = (
        str(path), hashlib.sha256(pdf).hexdigest(), pdf_page_count(pdf), utcnow())
    db.commit()
    return row


def part_report_path(submission_id: str, part: str) -> Path:
    return Path(get_settings().report_dir) / f"{submission_id}-{part}.pdf"


def generate_part_report(db: Session, sub: Submission, part: str) -> Path:
    """Similarity-only or AI-only PDF, built on first download and kept next to the full report."""
    path = part_report_path(sub.id, part)
    if not pdf_artifact_is_current(path):
        ctx = build_context(db, sub, part=part)
        pdf = build_pdf_report(ctx)
        _write_report(path, pdf)
    return path
