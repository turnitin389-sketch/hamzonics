"""PDF hidden-text detection on pdfplumber pages.

A character is hidden when it is (checked in this order):
1. entirely outside the page box                -> text_outside_page
2. too close in colour to the background under it -> hidden_text_color
   (background = last filled shape containing the glyph centre, else white;
   glyphs over images are skipped because their background is unknown)
3. smaller than 4 pt                             -> hidden_text_tiny
Hidden characters are removed from the extracted text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.flags.colors import RGB, WHITE, is_invisible_on, pdf_color_to_rgb
from engine.flags.types import Finding

TINY_PT = 4.0


@dataclass
class PdfPageResult:
    text: str
    findings: list[Finding]


def _inside(x: float, y: float, obj: dict[str, Any]) -> bool:
    return obj["x0"] <= x <= obj["x1"] and obj["top"] <= y <= obj["bottom"]


class _PageClassifier:
    def __init__(self, page: Any) -> None:
        self.x0, self.top, self.x1, self.bottom = page.bbox
        fills = [o for o in page.rects + page.curves if o.get("fill")]
        self.fills = [(o, pdf_color_to_rgb(o.get("non_stroking_color"))) for o in fills]
        self.images = page.images

    def background(self, x: float, y: float) -> RGB | None:
        for obj, rgb in reversed(self.fills):
            if _inside(x, y, obj):
                return rgb  # None if the fill colour is a pattern/unknown
        if any(_inside(x, y, img) for img in self.images):
            return None
        return WHITE

    def reason(self, ch: dict[str, Any]) -> str | None:
        if ch["text"].isspace():
            return None
        if ch["x1"] <= self.x0 or ch["x0"] >= self.x1 or ch["bottom"] <= self.top or ch["top"] >= self.bottom:
            return "text_outside_page"
        fg = pdf_color_to_rgb(ch.get("non_stroking_color"))
        if fg is not None:
            bg = self.background((ch["x0"] + ch["x1"]) / 2, (ch["top"] + ch["bottom"]) / 2)
            if bg is not None and is_invisible_on(fg, bg):
                return "hidden_text_color"
        if float(ch.get("size", 99)) < TINY_PT:
            return "hidden_text_tiny"
        return None


def extract_pdf_page(page: Any, page_number: int, x_tolerance: float = 1.5, y_tolerance: float = 3) -> PdfPageResult:
    clf = _PageClassifier(page)
    hidden_ids: set[int] = set()
    findings: list[Finding] = []
    current: Finding | None = None
    last_char: dict[str, Any] | None = None

    for ch in page.chars:
        reason = clf.reason(ch)
        if reason is None:
            if not ch["text"].isspace():
                current = None
            continue
        hidden_ids.add(id(ch))
        if current is not None and current.type == reason:
            current.count += 1
            # A gap wider than ~a space between glyphs means a new word.
            if last_char is not None and ch["x0"] - last_char["x1"] > 0.25 * float(ch.get("size", 10)):
                current.text += " "
            current.text += ch["text"]
        else:
            current = Finding(reason, 1, page_number, text=ch["text"])
            findings.append(current)
        last_char = ch

    if hidden_ids:
        visible = page.filter(lambda o: o.get("object_type") != "char" or id(o) not in hidden_ids)
    else:
        visible = page
    text = visible.extract_text(x_tolerance=x_tolerance, y_tolerance=y_tolerance) or ""
    return PdfPageResult(text, findings)
