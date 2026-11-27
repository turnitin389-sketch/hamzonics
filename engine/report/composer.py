"""Compose Turnitin Report Similarity and AI Writing PDFs on US Letter pages."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Any

import fitz

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"

PAGE_W = 612.0
PAGE_H = 792.0
KAPPA = 0.5522847498

# ---------------------------------------------------------------------------
# Report colors (normalized RGB floats)
# ---------------------------------------------------------------------------
C_BRAND  = (23/255, 57/255, 75/255)
C_TEXT   = (25/255, 25/255, 25/255)
C_MUTED  = (99/255, 99/255, 99/255)
C_WHITE  = (1.0, 1.0, 1.0)               # badge number text
C_RULE   = (0.800781, 0.800781, 0.800781) # #CCCCCC — divider lines
C_STATS_BG  = (0.972656, 0.972656, 0.972656)  # #F8F8F8
C_CAUTION_BG  = (0.816406, 0.910156, 0.976562)  # #D0E8F9
C_CAUTION_TXT = (45/255, 45/255, 45/255)   # #2D2D2D
C_AI_HL  = (0.320312, 0.777344, 0.855469)  # #52C6DA AI highlight

# Match group fill colors
GROUP_FILLS = {
    "not_cited_or_quoted": (0.972656, 0.386719, 0.441406),  # #F86371
    "missing_quotations":  (0.964844, 0.558594, 0.289062),  # #F68E4A
    "missing_citation":    (0.957031, 0.894531, 0.667969),  # #F4E4AA
    "cited_and_quoted":    (0.757812, 0.925781, 0.875),     # #C1ECDF
}

GROUP_ICONS = {
    "not_cited_or_quoted": ("grp_not_cited.png",        5.5, 6.0),
    "missing_quotations":  ("grp_missing_quotes.png",   5.5, 3.5),
    "missing_citation":    ("grp_missing_citation.png", 6.0, 4.0),
    "cited_and_quoted":    ("grp_cited_quoted.png",     5.5, 6.0),
}

# Source color cycle (dark badge / light pill)
SOURCE_CYCLE = [
    ((0.796875, 0.078125, 0.460938), (0.996094, 0.863281, 0.90625)),   # #CB1476 / #FEDCE7
    ((0.132812, 0.367188, 0.777344), (0.839844, 0.898438, 0.984375)),  # #225EC6 / #D6E5FB
    ((0.0,      0.457031, 0.273438), (0.757812, 0.925781, 0.875)),     # #007546 / #C1ECDF
    ((0.457031, 0.199219, 0.90625),  (0.925781, 0.875,    0.996094)),  # #7533E7 / #ECDFFE
]

# ---------------------------------------------------------------------------
# Source list exact geometry (from Sim_SRC page reference measurements)
# ---------------------------------------------------------------------------
# Summary columns top: y=64 (heading "Match Groups" / "Top Sources")
# Source list section: "Top Sources" heading y=216.5, desc y=231.5
# First source row top y_top = 245.5; badge center-text y = 255.5 (y_top+10)
# Title y = 273.5 (y_top + 28), percent y = 273.5
# Row spacing = 48pt (source 1 y=255.5 → source 2 y=303.5 → delta=48)
# Badge: Rect(36, y_top, 60.5, y_top+15) → badge num text at y=y_top+10 centered x
#   Exact ref: x=46.25 for single digit, x=44.25 for "10" → compute as center
# Type pill: Rect(66, y_top, 136, y_top+15) → text at x=86.77 (Internet) / 81.75 (Publication)
# Rule at y = y_top + row_h - 10 = y_top + 38 for single-title rows

SRC_Y_HEADING   = 216.5   # "Top Sources" section heading
SRC_Y_DESC      = 231.5   # description line
SRC_Y_FIRST     = 245.5   # first row y_top
SRC_ROW_H       = 48.0    # spacing between rows (badge baseline delta = 48)
SRC_BADGE_X0    = 36.0
SRC_BADGE_X1    = 60.5
SRC_PILL_X0     = 66.0
SRC_PILL_X1     = 136.0
SRC_BADGE_H     = 15.0
SRC_BADGE_TY    = 10.0    # text y offset within badge (above row y_top)
SRC_TITLE_DY    = 28.0    # title below y_top
SRC_PCT_X       = 386.0
SRC_RULE_DY     = 38.0    # rule below y_top (for single-line title)

# Summary columns geometry (on source-list page and overview pages)
SUM_MATCH_X     = 36.0
SUM_SRC_X       = 298.5
SUM_ROW_STEP    = 25.0    # match groups row step

# Top-sources summary sub-section (right column of summary)
TOP_SRC_ROW_STEP = 14.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def _draw_rounded_rect(
    shape: fitz.Shape,
    rect: fitz.Rect,
    r: float,
    fill: tuple[float, float, float],
    color: tuple | None = None,
    width: float = 0.0,
) -> None:
    x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
    r = min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0)
    k = r * KAPPA
    p1 = fitz.Point(x0 + r, y0)
    p2 = fitz.Point(x1 - r, y0)
    p3 = fitz.Point(x1,     y0 + r)
    p4 = fitz.Point(x1,     y1 - r)
    p5 = fitz.Point(x1 - r, y1)
    p6 = fitz.Point(x0 + r, y1)
    p7 = fitz.Point(x0,     y1 - r)
    p8 = fitz.Point(x0,     y0 + r)
    shape.draw_line(p1, p2)
    shape.draw_bezier(p2, fitz.Point(x1 - r + k, y0),     fitz.Point(x1,     y0 + r - k), p3)
    shape.draw_line(p3, p4)
    shape.draw_bezier(p4, fitz.Point(x1,     y1 - r + k), fitz.Point(x1 - r + k, y1),     p5)
    shape.draw_line(p5, p6)
    shape.draw_bezier(p6, fitz.Point(x0 + r - k, y1),     fitz.Point(x0,     y1 - r + k), p7)
    shape.draw_line(p7, p8)
    shape.draw_bezier(p8, fitz.Point(x0,     y0 + r - k), fitz.Point(x0 + r - k, y0),     p1)
    shape.finish(fill=fill, color=color, width=width, fill_opacity=1.0, closePath=True)


def _draw_rule(page: fitz.Page, x0: float, x1: float, y: float) -> None:
    sh = page.new_shape()
    sh.draw_line(fitz.Point(x0, y), fitz.Point(x1, y))
    sh.finish(color=C_RULE, width=0.5)
    sh.commit()


def _commit_highlights(page: fitz.Page, shape: fitz.Shape) -> None:
    if not shape.totalcont:
        return
    shape.commit()
    doc = page.parent
    # Use a dedicated blend state so translucent highlights leave dark glyphs legible.
    state = doc.get_new_xref()
    doc.update_object(state, "<< /Type /ExtGState /BM /Multiply >>")
    _, reference = doc.xref_get_key(page.xref, "Resources")
    resources = int(reference.split()[0])
    doc.xref_set_key(resources, "ExtGState/ReportMultiply", f"{state} 0 R")
    stream = page.get_contents()[-1]
    doc.update_stream(stream, b"q\n/ReportMultiply gs\n" + doc.xref_stream(stream) + b"\nQ\n")


def _wrap_text(text: str, font: fitz.Font, fontsize: float, max_width: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = ""
    for word in words:
        candidate = f"{cur} {word}" if cur else word
        if font.text_length(candidate, fontsize=fontsize) <= max_width:
            cur = candidate
            continue
        if cur:
            lines.append(cur)
        start = 0
        width = 0.0
        for index, advance in enumerate(font.char_lengths(word, fontsize=fontsize)):
            if width + advance > max_width and index > start:
                lines.append(word[start:index])
                start = index
                width = 0.0
            width += advance
        cur = word[start:]
    if cur:
        lines.append(cur)
    return lines


class _Composer:
    def __init__(self) -> None:
        self.fonts = {
            "lexend_sb": fitz.Font(fontfile=str(FONTS_DIR / "LexendDeca-SemiBold.ttf")),
            "lexend_md": fitz.Font(fontfile=str(FONTS_DIR / "LexendDeca-Medium.ttf")),
            "noto_reg":  fitz.Font(fontfile=str(FONTS_DIR / "NotoSans-Regular.ttf")),
            "noto_sb":   fitz.Font(fontfile=str(FONTS_DIR / "NotoSans-SemiBold.ttf")),
            "serif":     fitz.Font("tiro"),
        }
        self._font_bufs = {
            "lexend_sb": (FONTS_DIR / "LexendDeca-SemiBold.ttf").read_bytes(),
            "lexend_md": (FONTS_DIR / "LexendDeca-Medium.ttf").read_bytes(),
            "noto_reg":  (FONTS_DIR / "NotoSans-Regular.ttf").read_bytes(),
            "noto_sb":   (FONTS_DIR / "NotoSans-SemiBold.ttf").read_bytes(),
        }
        self._img_cache: dict[str, bytes] = {}

    def _img(self, name: str) -> bytes:
        if name not in self._img_cache:
            self._img_cache[name] = (ASSETS_DIR / name).read_bytes()
        return self._img_cache[name]

    def _new_page(self, doc: fitz.Document, role: str) -> fitz.Page:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for name, buf in self._font_bufs.items():
            page.insert_font(fontname=name, fontbuffer=buf)
        # Store role in instance list indexed by page number
        self._page_roles.append(role)
        return page

    def _t(self, page: fitz.Page, x: float, y: float, text: str, fk: str, sz: float, col: tuple) -> None:
        """Insert text at (x, y) with given font key, size, color."""
        page.insert_text(fitz.Point(x, y), text, fontname=fk, fontsize=sz, color=col)

    # -----------------------------------------------------------------------
    # Chrome (header + footer) — painted last so page count is known
    # -----------------------------------------------------------------------
    def _paint_chrome(
        self,
        page: fitz.Page,
        page_num: int,
        total_pages: int,
        label: str,
        display_id: str,
    ) -> None:
        left_str = f"Page {page_num} of {total_pages} - {label}"
        f_reg = self.fonts["noto_reg"]

        # Submission ID label and value — exact x positions from reference:
        # "Submission ID" at x=467.53, trn:oid at x=512.99
        # We compute dynamically but anchor to match reference spacing
        id_w   = f_reg.text_length(display_id,     fontsize=6.0)
        lbl_w  = f_reg.text_length("Submission ID", fontsize=6.0)
        # In reference: trn:oid x=512.99, "Submission ID" x=467.53
        # Gap between them = 512.99 - 467.53 - lbl_w = ~5pt
        # Right edge of trn:oid = 512.99 + id_w ≈ 576pt
        id_x  = 576.0 - id_w
        lbl_x = id_x - 5.0 - lbl_w

        logo_path = Path(__file__).resolve().parents[2] / "frontend" / "public" / "logo.png"
        logo_bytes = logo_path.read_bytes()
        for y in (34.0, 758.0):
            # Use the website's Turnitin wordmark in both the page header and footer.
            page.insert_image(
                fitz.Rect(36.0, y - 11.0, 78.0, y + 2.0),
                stream=logo_bytes,
                keep_proportion=True,
            )
            self._t(page, 82.0, y, "Report", "lexend_sb", 8.0, C_BRAND)
            self._t(page, 107.0, y, left_str,       "noto_reg", 6.0, C_TEXT)
            self._t(page, lbl_x,  y, "Submission ID", "noto_reg", 6.0, C_TEXT)
            self._t(page, id_x,   y, display_id,      "noto_reg", 6.0, C_TEXT)
        page.draw_line(fitz.Point(36, 44), fitz.Point(576, 44), color=C_BRAND, width=0.8)

    # -----------------------------------------------------------------------
    # Cover page — exact geometry from reference AI Page 1 / Sim Page 1
    # -----------------------------------------------------------------------
    def _build_cover(self, doc: fitz.Document, ctx: dict[str, Any]) -> None:
        p = self._new_page(doc, "Cover Page")

        author = ctx.get("author")
        filename = str(ctx["filename"])
        title = _wrap_text(author or filename, self.fonts["lexend_sb"], 20.0, 540.0)
        subtitle = _wrap_text(filename, self.fonts["lexend_md"], 17.0, 540.0) if author else []
        extra_title = (len(title) - 1) * 24.0 + max(0, len(subtitle) - 1) * 20.0

        details = [
            ("Submission ID", ctx["display_id"]),
            ("Submission Date", ctx["submitted"]),
            ("Download Date", ctx["generated"]),
            ("File Name", filename),
            ("File Size", ctx["file_size"]),
        ]
        detail_rows = [
            (label, _wrap_text(str(value), self.fonts["noto_sb"], 7.0, 345.0))
            for label, value in details
        ]
        extra_details = sum((len(lines) - 1) * 10.0 for _, lines in detail_rows)
        lift = max(0.0, 638.0 + extra_title + extra_details - 718.0)
        dy = extra_title - lift
        for index, line in enumerate(title):
            self._t(p, 36.0, 324.0 - lift + index * 24.0, line, "lexend_sb", 20.0, C_BRAND)
        for index, line in enumerate(subtitle):
            baseline = 354.0 - lift + (len(title) - 1) * 24.0 + index * 20.0
            self._t(p, 36.0, baseline, line, "lexend_md", 17.0, C_TEXT)

        _draw_rule(p, 36.0, 576.0, 425.0 + dy)
        self._t(p, 36.0, 454.0 + dy, "Document Details", "noto_sb", 10.0, C_TEXT)
        label_y = 480.0 + dy
        for label, lines in detail_rows:
            self._t(p, 36.0, label_y, label, "noto_sb", 7.0, C_MUTED)
            for index, line in enumerate(lines):
                self._t(p, 36.0, label_y + 14.0 + index * 10.0, line, "noto_sb", 7.0, C_TEXT)
            label_y += 36.0 + (len(lines) - 1) * 10.0

        # Stats box: Rect(403, 470+dy, 492, 548+dy)
        sh = p.new_shape()
        sh.draw_rect(fitz.Rect(403.0, 470.0 + dy, 492.0, 548.0 + dy))
        sh.finish(fill=C_STATS_BG, color=None)
        sh.commit()

        # Stats text: y=492, 514, 536 at x=415
        pc = ctx["page_count"]
        self._t(p, 415.0, 492.0 + dy, f"{pc} Page{'s' if pc != 1 else ''}",    "noto_sb", 7.0, C_TEXT)
        self._t(p, 415.0, 514.0 + dy, f"{ctx['word_count']} Words",             "noto_sb", 7.0, C_TEXT)
        self._t(p, 415.0, 536.0 + dy, f"{ctx['char_count']} Characters",        "noto_sb", 7.0, C_TEXT)

    # -----------------------------------------------------------------------
    # AI Writing Overview — exact from AI_OVR Page 2
    # -----------------------------------------------------------------------
    def _build_ai_overview(self, doc: fitz.Document, ctx: dict[str, Any]) -> None:
        p = self._new_page(doc, "AI Writing Overview")
        ai = ctx["ai"]
        available = ai.get("available", False)
        _draw_rule(p, 36.0, 576.0, 60.0)

        if available:
            pct = f"{ai['percent_label']}{'*' if ai.get('low') else ''}"
            self._t(p, 36.0, 98.0, f"{pct} detected as AI", "lexend_md", 17.0, C_TEXT)
            summary = (
                "The score estimates the share of eligible text that the analyzer classified "
                "as likely written or revised by AI."
            )
        else:
            self._t(p, 36.0, 98.0, "AI Writing score unavailable", "lexend_md", 15.0, C_TEXT)
            summary = ai.get("message") or "No AI Writing score is available for this submission."
        for index, line in enumerate(_wrap_text(summary, self.fonts["noto_reg"], 7.0, 252.0)):
            self._t(p, 36.0, 108.0 + index * 10.0, line, "noto_reg", 7.0, C_TEXT)

        # Caution box: Rect(306, 76, 579, 132) — from reference AI_OVR page
        sh = p.new_shape()
        _draw_rounded_rect(sh, fitz.Rect(306.0, 76.0, 579.0, 132.0), 8.0, C_CAUTION_BG)
        sh.commit()

        # Caution text — exact positions from reference
        self._t(p, 318.0,  92.0, "Caution: Review required.",           "noto_sb",  6.0, C_CAUTION_TXT)
        self._t(p, 318.0, 108.0,
                "It is essential to understand the limitations of AI detection before making decisions",
                "noto_reg", 6.0, C_CAUTION_TXT)
        self._t(p, 318.0, 116.0,
                "about a student\u2019s work. Review the limitations of this analyzer before using its",
                "noto_reg", 6.0, C_CAUTION_TXT)
        self._t(p, 318.0, 124.0,
                "results.",
                "noto_reg", 6.0, C_CAUTION_TXT)

        # Rule at y=148
        _draw_rule(p, 36.0, 576.0, 148.0)

        if available:
            # AI robot icon: Rect(36,168,48,180) — 12x12pt
            p.insert_image(fitz.Rect(36.0, 168.0, 48.0, 180.0), stream=self._img("ai_robot.png"))

            # Segment count + label: y=174, x=52
            cnt_str = str(ai.get("ai_segments_count", 0))
            self._t(p, 52.0, 174.0, cnt_str, "noto_sb", 7.0, C_TEXT)
            cnt_w = self.fonts["noto_sb"].text_length(cnt_str, fontsize=7.0)
            ai_pct_lbl = ai["percent_label"]
            self._t(p, 52.0 + cnt_w + 2.0, 174.0,
                    f"AI-generated  {ai_pct_lbl}", "noto_reg", 7.0, C_TEXT)

            # Subtitle: y=184, x=52
            self._t(p, 52.0, 184.0,
                    "Likely generated or likely generated and revised by AI.",
                    "noto_reg", 7.0, C_MUTED)

        # Rule at y=200
        _draw_rule(p, 36.0, 576.0, 200.0)

        # Disclaimer
        self._t(p, 36.0, 224.0, "Disclaimer", "noto_sb", 6.0, C_MUTED)
        disc_lines = [
            "Our AI writing assessment is designed to help educators identify text that might be prepared by a generative AI tool. Our AI writing assessment may not always be accurate (it may misidentify",
            "writing that is likely human generated as AI generated and likely AI generated as human generated) so it should not be used as the sole basis for adverse actions against a student. It takes",
            "further scrutiny and human judgment in conjunction with an organization\u2019s application of its specific academic policies to determine whether any academic misconduct has occurred.",
        ]
        for idx, line in enumerate(disc_lines):
            self._t(p, 36.0, 232.0 + idx * 8.0, line, "noto_reg", 6.0, C_MUTED)

        _draw_rule(p, 36.0, 576.0, 264.0)

    # -----------------------------------------------------------------------
    # Summary columns (Match Groups + Top Sources mini-table)
    # Used on: Sim_OVR page (y=172.5) and Sim_SRC page (y=64)
    # -----------------------------------------------------------------------
    def _draw_summary_columns(
        self, p: fitz.Page, ctx: dict[str, Any], heading_y: float
    ) -> None:
        # Headings
        self._t(p, SUM_MATCH_X, heading_y, "Match Groups", "noto_sb", 10.0, C_TEXT)
        self._t(p, SUM_SRC_X,   heading_y, "Top Sources",  "noto_sb", 10.0, C_TEXT)

        # Match Groups rows
        # Reference: first row y=192.5 when heading_y=172.5 → offset +20
        # Icon circle: Rect(36, cy, 48.5, cy+12), cy = row_y - 8  (so top = row_y-8, bottom = row_y+4)
        row_y = heading_y + 20.0
        for g in ctx["groups"]:
            key  = g["key"]
            fill = GROUP_FILLS.get(key, C_RULE)
            cy   = row_y - 8.0

            sh = p.new_shape()
            _draw_rounded_rect(sh, fitz.Rect(36.0, cy, 48.5, cy + 12.0), 6.0, fill)
            sh.commit()

            icon_name, iw, ih = GROUP_ICONS[key]
            ix = 36.0 + (12.5 - iw) / 2.0
            iy = cy  + (12.0 - ih) / 2.0
            p.insert_image(fitz.Rect(ix, iy, ix + iw, iy + ih), stream=self._img(icon_name))

            cnt = str(g["count"])
            cw  = self.fonts["noto_sb"].text_length(cnt, fontsize=7.0)
            self._t(p, 53.0, row_y, cnt, "noto_sb", 7.0, C_TEXT)
            self._t(p, 53.0 + cw, row_y,
                    f"  {g['label']}  {g['percent_label']}", "noto_reg", 7.0, C_TEXT)
            self._t(p, 53.0, row_y + 10.0, g["help"], "noto_reg", 7.0, C_MUTED)
            row_y += SUM_ROW_STEP

        # Top Sources summary (right column)
        # Reference: row_y starts at heading_y+20 same as match groups
        type_icons = [
            ("web",        "src_web.png",        322.0, 8.5, 8.5),
            ("corpus",     "src_corpus.png",     322.0, 9.0, 6.5),
            ("submission", "src_submission.png", 323.0, 6.5, 6.5),
        ]
        type_labels = {
            "web":        "Internet sources",
            "corpus":     "Publications",
            "submission": "Submitted works (Student Papers)",
        }
        by_type_map = {t["key"]: t for t in ctx["by_type"]}
        ty = heading_y + 20.0
        for key, icon_name, ix, iw, ih in type_icons:
            t = by_type_map.get(key, {"percent_label": "0%", "label": type_labels[key]})
            iy = ty - 6.5 + (8.5 - ih) / 2.0
            p.insert_image(fitz.Rect(ix, iy, ix + iw, iy + ih), stream=self._img(icon_name))
            self._t(p, SUM_SRC_X, ty, t["percent_label"], "noto_reg", 7.0, C_TEXT)
            self._t(p, 336.0,     ty, type_labels[key],    "noto_reg", 7.0, C_TEXT)
            ty += TOP_SRC_ROW_STEP

    # -----------------------------------------------------------------------
    # Similarity Overview (page 2 of Sim report) — exact from Sim_OVR
    # -----------------------------------------------------------------------
    def _build_sim_overview(self, doc: fitz.Document, ctx: dict[str, Any]) -> None:
        p = self._new_page(doc, "Integrity Overview")

        # "X% Overall Similarity": y=72, x=36, sz=17
        self._t(p, 36.0, 72.0,
                f"{ctx['similarity_label']} Overall Similarity", "lexend_md", 17.0, C_TEXT)
        # Subtitle: y=87.5, x=36, sz=7, muted
        self._t(p, 36.0, 87.5,
                "The combined total of all matches, including overlapping sources, for each database.",
                "noto_reg", 7.0, C_MUTED)

        # "Filtered from the Report": y=111.5
        self._t(p, 36.0, 111.5, "Filtered from the Report", "noto_sb", 10.0, C_TEXT)

        filtered = ctx.get("filtered") or ["Nothing was filtered."]
        # First filter item: y=129.5, x=48
        fy = 129.5
        for f_item in filtered:
            # filter arrow icon: small, before text
            p.insert_image(fitz.Rect(39.0, fy - 4.0, 41.0, fy - 1.0),
                           stream=self._img("filter_arrow.png"))
            self._t(p, 48.0, fy, f_item, "noto_reg", 7.0, C_TEXT)
            fy += 14.0

        # dy = extra height from additional filter items (reference has 1 item = 0 dy)
        dy = max(0.0, (len(filtered) - 1) * 14.0)

        # Rule: y=148.5 (when 1 filter item) → reference shows 148+dy
        _draw_rule(p, 36.0, 576.0, 148.5 + dy)

        # Summary columns: heading_y=172.5 (from reference exact measurement)
        self._draw_summary_columns(p, ctx, 172.5 + dy)

        # Rule after summary (4 group rows × 25pt + heading_y+20 → 172.5+20+4×25=292.5)
        _draw_rule(p, 36.0, 576.0, 291.0 + dy)

        # "Integrity Flags": y=312.5
        self._t(p, 36.0, 312.5 + dy, "Integrity Flags", "noto_sb", 10.0, C_TEXT)

        flags = ctx.get("flags") or []
        # "0 Integrity Flags for Review": y=326.5
        self._t(p, 36.0, 326.5 + dy,
                f"{len(flags)} Integrity Flag{'s' if len(flags) != 1 else ''} for Review",
                "noto_sb", 7.0, C_TEXT)
        if not flags:
            # "No suspicious text manipulations found.": y=341.5
            self._t(p, 36.0, 341.5 + dy,
                    "No suspicious text manipulations found.", "noto_reg", 7.0, C_MUTED)
        else:
            iy = 341.5 + dy
            for fl in flags:
                self._t(p, 36.0, iy,
                        f"{fl['title']} \u2014 {fl['count']} {fl['unit']}", "noto_reg", 7.0, C_TEXT)
                iy += 12.0

        # Caution box: Rect(301, 318.5+dy, 567, 382.5+dy) — from reference Sim_OVR
        sh = p.new_shape()
        _draw_rounded_rect(sh, fitz.Rect(301.0, 318.5 + dy, 567.0, 382.5 + dy), 8.0, C_CAUTION_BG)
        sh.commit()

        # Caution box text — exact y positions from reference
        caution_lines = [
            ("Our system\u2019s algorithms look deeply at a document for any inconsistencies that",   332.5 + dy),
            ("would set it apart from a normal submission. If we notice something strange, we flag",   340.5 + dy),
            ("it for you to review.",                                                                  348.5 + dy),
            ("A Flag is not necessarily an indicator of a problem. However, we\u2019d recommend you", 364.5 + dy),
            ("focus your attention there for further review.",                                         372.5 + dy),
        ]
        for txt, cy in caution_lines:
            self._t(p, 313.0, cy, txt, "noto_reg", 6.0, C_CAUTION_TXT)

    # -----------------------------------------------------------------------
    # Source list page — exact from Sim_SRC Page 3
    # -----------------------------------------------------------------------
    def _build_source_list(self, doc: fitz.Document, ctx: dict[str, Any]) -> None:
        p = self._new_page(doc, "Integrity Overview")

        # Summary columns: heading_y=64 (from reference Sim_SRC)
        self._draw_summary_columns(p, ctx, 64.0)

        # Rule: y=187.5 (from reference — after 4 groups × 25 + offset)
        _draw_rule(p, 36.0, 576.0, 187.5)

        # "Top Sources" section heading: y=216.5
        self._t(p, 36.0, SRC_Y_HEADING, "Top Sources", "noto_sb", 10.0, C_TEXT)
        # Description: y=231.5
        self._t(p, 36.0, SRC_Y_DESC,
                "The sources with the highest number of matches within the submission. Overlapping sources will not be displayed.",
                "noto_reg", 7.0, C_MUTED)

        sources = ctx.get("sources") or []
        if not sources:
            self._t(p, 36.0, 255.0, "No matching sources were found.", "noto_reg", 8.0, C_MUTED)
            return

        y_top = SRC_Y_FIRST  # = 245.5
        for idx, s in enumerate(sources):
            title_lines = _wrap_text(s["title"], self.fonts["noto_sb"], 8.0, 340.0)
            # Row height: single-title = 48pt, multi-title adds 18pt per extra line
            extra_lines = max(0, len(title_lines) - 1)
            row_h = SRC_ROW_H + extra_lines * 18.0

            # Page break
            if y_top + row_h - 10.0 > 738.0:
                p = self._new_page(doc, "Integrity Overview")
                y_top = 75.0

            dark_col, light_col = SOURCE_CYCLE[idx % len(SOURCE_CYCLE)]
            sh = p.new_shape()
            # Badge: Rect(36, y_top, 60.5, y_top+15) r=7
            _draw_rounded_rect(sh,
                fitz.Rect(SRC_BADGE_X0, y_top, SRC_BADGE_X1, y_top + SRC_BADGE_H),
                7.0, dark_col)
            # Pill: Rect(66, y_top, 136, y_top+15) r=7.5
            _draw_rounded_rect(sh,
                fitz.Rect(SRC_PILL_X0, y_top, SRC_PILL_X1, y_top + SRC_BADGE_H),
                7.5, light_col)
            sh.commit()

            # Badge number text — horizontally centered in badge (w=24.5pt)
            # Reference exact: x=46.25 for "1", x=44.25 for "10"
            num_str = str(s["number"])
            nw = self.fonts["noto_sb"].text_length(num_str, fontsize=7.0)
            bx = SRC_BADGE_X0 + (SRC_BADGE_X1 - SRC_BADGE_X0 - nw) / 2.0
            # y baseline = y_top + 10 (text baseline within 15pt badge)
            self._t(p, bx, y_top + SRC_BADGE_TY, num_str, "noto_sb", 7.0, C_WHITE)

            # Type label text — centered in pill (w=70pt)
            # Reference: "Internet" x=86.77, "Publication" x=81.75 → computed by centering
            lbl_str = s["type_label"]
            lw = self.fonts["noto_sb"].text_length(lbl_str, fontsize=7.0)
            px = SRC_PILL_X0 + (SRC_PILL_X1 - SRC_PILL_X0 - lw) / 2.0
            self._t(p, px, y_top + SRC_BADGE_TY, lbl_str, "noto_sb", 7.0, C_TEXT)

            # Title lines: start at y_top + 28
            ty = y_top + SRC_TITLE_DY
            for tline in title_lines:
                self._t(p, 36.0, ty, tline, "noto_sb", 8.0, C_TEXT)
                ty += 18.0

            # Percent: at same y as first title line, x=386
            self._t(p, SRC_PCT_X, y_top + SRC_TITLE_DY, s["percent_label"], "noto_sb", 8.0, C_TEXT)

            # Hyperlink annotation
            if s.get("link_url"):
                link_rect = fitz.Rect(
                    36.0, y_top + 16.0, 376.0,
                    y_top + SRC_TITLE_DY + extra_lines * 18.0 + 10.0
                )
                p.insert_link({"kind": fitz.LINK_URI, "from": link_rect, "uri": s["link_url"]})

            # Rule: y = y_top + row_h - 10 (38pt below y_top for single-line)
            if idx < len(sources) - 1:
                _draw_rule(p, 36.0, 400.0, y_top + row_h - 10.0)
            y_top += row_h

    # -----------------------------------------------------------------------
    # Margin marker (left side, overlapping circles)
    # -----------------------------------------------------------------------
    def _draw_margin_marker(
        self,
        page: fitz.Page,
        y_top: float,
        group_key: str,
        source_num: int,
        source_idx: int,
    ) -> None:
        g_col    = GROUP_FILLS.get(group_key, GROUP_FILLS["not_cited_or_quoted"])
        dark_col = SOURCE_CYCLE[source_idx % len(SOURCE_CYCLE)][0]

        sh = page.new_shape()
        _draw_rounded_rect(sh, fitz.Rect(7.48,  y_top, 22.99, y_top + 15.51), 7.75, g_col)
        _draw_rounded_rect(sh, fitz.Rect(24.10, y_top, 41.82, y_top + 15.51), 7.75, dark_col)
        sh.commit()

        icon_name, iw, ih = GROUP_ICONS.get(group_key, GROUP_ICONS["not_cited_or_quoted"])
        ix = 7.48  + (15.51 - iw) / 2.0
        iy = y_top + (15.51 - ih) / 2.0
        page.insert_image(fitz.Rect(ix, iy, ix + iw, iy + ih), stream=self._img(icon_name))

        num_str = str(source_num)
        nw = self.fonts["noto_sb"].text_length(num_str, fontsize=7.75)
        self._t(page,
                24.10 + (17.72 - nw) / 2.0,
                y_top + 10.6,
                num_str, "noto_sb", 7.75, C_WHITE)

    # -----------------------------------------------------------------------
    # Text-fallback body pages (when no source PDF is available)
    # -----------------------------------------------------------------------
    def _build_text_fallback_pages(
        self,
        doc: fitz.Document,
        role: str,
        text: str,
        segments: list[dict[str, Any]],
        is_ai: bool,
        source_index_map: dict[int, int],
    ) -> None:
        f_serif  = self.fonts["serif"]
        fontsize = 11.98
        max_w    = 468.0  # x=72 to x=540

        # Build flat list of (line_str, char_start, char_end)
        lines_meta: list[tuple[str, int, int]] = []
        pos = 0
        for para in text.split("\n"):
            if not para:
                lines_meta.append(("", pos, pos))
                pos += 1
                continue
            cur_start = pos
            cur_line  = ""
            for m in re.finditer(r"\S+\s*", para):
                tok       = m.group(0)
                tok_start = pos + m.start()
                cand      = cur_line + tok
                if cur_line and f_serif.text_length(cand.rstrip(), fontsize=fontsize) > max_w:
                    lines_meta.append((cur_line, cur_start, tok_start))
                    cur_line  = tok
                    cur_start = tok_start
                else:
                    cur_line = cand
            if cur_line:
                lines_meta.append((cur_line, cur_start, pos + len(para)))
            pos += len(para) + 1

        # Compute highlight character ranges
        hl_ranges: list[tuple[int, int, dict[str, Any]]] = []
        cpos = 0
        for seg in segments:
            seg_len = len(seg["text"])
            if "bg" in seg:
                hl_ranges.append((cpos, cpos + seg_len, seg))
            cpos += seg_len

        # Paginate: y_start=83.2, step=27.6, max_y=710
        y_start   = 83.2
        line_step = 27.6
        max_y     = 710.0

        pages_lines: list[list[tuple[str, int, int, float]]] = []
        cur_page: list[tuple[str, int, int, float]] = []
        y = y_start
        for l_str, l_s, l_e in lines_meta:
            if y > max_y and cur_page:
                pages_lines.append(cur_page)
                cur_page = []
                y = y_start
            cur_page.append((l_str, l_s, l_e, y))
            y += line_step
        if cur_page or not pages_lines:
            pages_lines.append(cur_page)

        seen_badges: set[int] = set()
        for p_lines in pages_lines:
            pg = self._new_page(doc, role)
            # Draw text
            for l_str, _, _, ly in p_lines:
                if l_str:
                    pg.insert_text(
                        fitz.Point(72.0, ly), l_str,
                        fontname="tiro", fontsize=fontsize, color=C_TEXT
                    )
            # Draw highlights and collect margin markers
            sh = pg.new_shape()
            markers: list[tuple[float, str, int, int]] = []
            for l_str, l_s, l_e, ly in p_lines:
                if not l_str:
                    continue
                for r_idx, (rs, re_pos, seg) in enumerate(hl_ranges):
                    ov_s = max(l_s, rs)
                    ov_e = min(l_e, re_pos)
                    if ov_s < ov_e:
                        pre     = l_str[: ov_s - l_s]
                        sub_txt = l_str[ov_s - l_s : ov_e - l_s].rstrip()
                        if not sub_txt:
                            continue
                        hx0 = 72.0 + f_serif.text_length(pre, fontsize=fontsize)
                        hx1 = hx0  + f_serif.text_length(sub_txt, fontsize=fontsize)
                        hy0 = ly - 9.0
                        hy1 = ly + 2.5
                        col = C_AI_HL if is_ai else GROUP_FILLS.get(
                            seg.get("group"), _hex_to_rgb(seg["bg"])
                        )
                        op = 0.40 if is_ai else 0.80
                        sh.draw_rect(fitz.Rect(hx0, hy0, hx1, hy1))
                        sh.finish(fill=col, color=None, fill_opacity=op)
                        if not is_ai and seg.get("badge") and r_idx not in seen_badges:
                            seen_badges.add(r_idx)
                            b    = seg["badge"]
                            snum = b["number"]
                            markers.append((hy0, b["icon"], snum, source_index_map.get(snum, snum - 1)))
            _commit_highlights(pg, sh)
            for my, gkey, snum, sidx in markers:
                self._draw_margin_marker(pg, my, gkey, snum, sidx)

    # -----------------------------------------------------------------------
    # PDF-based body pages (when source PDF is available)
    # -----------------------------------------------------------------------
    def _build_submission_from_pdf(
        self,
        doc: fitz.Document,
        role: str,
        src_path: Path,
        clean_text: str,
        page_offsets: list[dict[str, Any]],
        segments: list[dict[str, Any]],
        is_ai: bool,
        source_index_map: dict[int, int],
    ) -> None:
        ranges: list[tuple[int, int, dict[str, Any]]] = []
        cursor = 0
        for segment in segments:
            end = cursor + len(segment["text"])
            if "bg" in segment and end > cursor:
                ranges.append((cursor, end, segment))
            cursor = end
        range_ends = [end for _, end, _ in ranges]
        offsets_by_page = {offset["page"]: offset for offset in page_offsets}
        seen_badges: set[int] = set()

        with fitz.open(src_path) as source:
            if len(source) == 1 and not page_offsets:
                offsets_by_page = {1: {"start": 0, "end": len(clean_text), "ocr": False}}
            for index, src_page in enumerate(source):
                # PyMuPDF's extraction coordinates are unrotated. Flatten the
                # original rotation in memory before placing or mapping the page.
                if src_page.rotation:
                    src_page.remove_rotation()
                page = self._new_page(doc, role)
                target = self._source_area(src_page)
                if src_page.get_contents():
                    page.show_pdf_page(target, source, index, keep_proportion=True)

                offset = offsets_by_page.get(index + 1)
                if not offset:
                    if ranges:
                        self._unmapped_highlights(page)
                    continue
                first = bisect_right(range_ends, offset["start"])
                if first == len(ranges) or ranges[first][0] >= offset["end"]:
                    continue
                page_text = clean_text[offset["start"]:offset["end"]]
                words = self._matching_source_words(src_page, page_text) if not offset.get("ocr") else []
                if not words:
                    self._unmapped_highlights(page)
                    continue

                scale = min(target.width / src_page.rect.width, target.height / src_page.rect.height)
                transform = fitz.Matrix(
                    scale, 0, 0, scale,
                    target.x0 + (target.width - src_page.rect.width * scale) / 2.0,
                    target.y0 + (target.height - src_page.rect.height * scale) / 2.0,
                )
                word_starts = [start for start, _, _, _ in words]
                word_ends = [end for _, end, _, _ in words]
                shape = page.new_shape()
                markers = []
                for range_index in range(first, len(ranges)):
                    start, end, segment = ranges[range_index]
                    if start >= offset["end"]:
                        break
                    word_first = bisect_right(word_ends, start - offset["start"])
                    word_last = bisect_left(word_starts, end - offset["start"])
                    lines: dict[tuple[int, int], fitz.Rect] = {}
                    for _, _, line, rect in words[word_first:word_last]:
                        if line in lines:
                            lines[line].include_rect(rect)
                        else:
                            lines[line] = fitz.Rect(rect)
                    if not lines:
                        continue
                    color = C_AI_HL if is_ai else GROUP_FILLS.get(
                        segment.get("group"), _hex_to_rgb(segment["bg"])
                    )
                    for rect in lines.values():
                        shape.draw_rect(rect * transform)
                        shape.finish(fill=color, color=None, fill_opacity=0.40 if is_ai else 0.80)
                    badge = segment.get("badge")
                    if not is_ai and badge and range_index not in seen_badges:
                        seen_badges.add(range_index)
                        y = (next(iter(lines.values())) * transform).y0
                        number = badge["number"]
                        markers.append((y, badge["icon"], number, source_index_map.get(number, number - 1)))
                _commit_highlights(page, shape)
                for marker in markers:
                    self._draw_margin_marker(page, *marker)

    @staticmethod
    def _source_area(src_page: fitz.Page) -> fitz.Rect:
        """Fit to Letter and reserve clear bands for the report chrome."""
        full = fitz.Rect(0, 0, PAGE_W, PAGE_H)
        scale = min(PAGE_W / src_page.rect.width, PAGE_H / src_page.rect.height)
        top = (PAGE_H - src_page.rect.height * scale) / 2.0
        for operation, box in src_page.get_bboxlog():
            if operation == "ignore-text":
                continue
            visible = fitz.Rect(box) & src_page.rect
            if not visible.is_empty and (top + visible.y0 * scale < 48.0 or top + visible.y1 * scale > 738.0):
                return fitz.Rect(36.0, 52.0, 576.0, 738.0)
        return full

    @staticmethod
    def _matching_source_words(
        page: fitz.Page, clean_text: str
    ) -> list[tuple[int, int, tuple[int, int], fitz.Rect]]:
        """Require a positional word match before putting analysis paint on the source."""
        analyzed = list(re.finditer(r"\S+", clean_text))
        expected = [unicodedata.normalize("NFKC", word.group()) for word in analyzed]
        for sort in (False, True):
            physical = page.get_text("words", sort=sort)
            if [unicodedata.normalize("NFKC", word[4]) for word in physical] == expected:
                return [
                    (word.start(), word.end(), (raw[5], raw[6]), fitz.Rect(raw[:4]))
                    for word, raw in zip(analyzed, physical)
                ]
        return []

    def _unmapped_highlights(self, page: fitz.Page) -> None:
        self._t(page, 36.0, 746.0, "Highlight positions unavailable for this source page.",
                "noto_reg", 6.0, C_MUTED)

    # -----------------------------------------------------------------------
    # Main build entry point
    # -----------------------------------------------------------------------
    def build(self, ctx: dict[str, Any]) -> bytes:
        doc   = fitz.open()
        part  = ctx.get("part", "all")
        source_index_map = {s["number"]: i for i, s in enumerate(ctx.get("sources") or [])}
        src_file = ctx.get("source_pdf_path")
        src_path = Path(src_file) if src_file and Path(src_file).is_file() else None
        raw_text = ctx.get("clean_text", "")
        # Track page roles in a list (page proxy objects don't retain Python attrs)
        self._page_roles: list[str] = []

        # 1. Cover
        self._build_cover(doc, ctx)

        # 2-4. Similarity sections
        if part != "ai":
            self._build_sim_overview(doc, ctx)
            self._build_source_list(doc, ctx)
            if src_path is not None:
                self._build_submission_from_pdf(
                    doc, "Integrity Submission", src_path, raw_text, ctx.get("source_page_offsets", []),
                    ctx.get("sim_segments", []), False, source_index_map
                )
            else:
                self._build_text_fallback_pages(
                    doc, "Integrity Submission", raw_text,
                    ctx.get("sim_segments", []), False, source_index_map
                )

        # 5-6. AI sections
        if part != "similarity":
            self._build_ai_overview(doc, ctx)
            ai_info = ctx.get("ai", {})
            if ai_info.get("available"):
                if src_path is not None:
                    self._build_submission_from_pdf(
                        doc, "AI Writing Submission", src_path, raw_text, ctx.get("source_page_offsets", []),
                        ctx.get("ai_segments", []), True, source_index_map
                    )
                else:
                    self._build_text_fallback_pages(
                        doc, "AI Writing Submission", raw_text,
                        ctx.get("ai_segments", []), True, source_index_map
                    )

        # Paint chrome last (page count is now final)
        total_pages = len(doc)
        for i, page in enumerate(doc):
            role = self._page_roles[i] if i < len(self._page_roles) else "Cover Page"
            self._paint_chrome(page, i + 1, total_pages, role, ctx["display_id"])

        doc.set_metadata({"title": "Turnitin Report Analysis Report", "author": "Turnitin Report"})
        out = doc.tobytes(garbage=3, deflate=True)
        doc.close()
        return out


def build_pdf_report(ctx: dict[str, Any]) -> bytes:
    """Compose a PDF from the analysis results and source document."""
    return _Composer().build(ctx)
