"""Colour helpers: parse colours and decide whether text is readable on its background."""

from __future__ import annotations

RGB = tuple[float, float, float]  # 0..1

WHITE: RGB = (1.0, 1.0, 1.0)
BLACK: RGB = (0.0, 0.0, 0.0)

# Below this WCAG contrast ratio text is treated as invisible (white on white = 1.0,
# #EEEEEE on white = 1.16, mid-grey on white = 3.9).
MIN_VISIBLE_CONTRAST = 1.5


def hex_to_rgb(value: str | None) -> RGB | None:
    if not value or value.lower() == "auto" or len(value) != 6:
        return None
    try:
        return (int(value[0:2], 16) / 255, int(value[2:4], 16) / 255, int(value[4:6], 16) / 255)
    except ValueError:
        return None


def pdf_color_to_rgb(color: object) -> RGB | None:
    """pdfplumber gives gray (1), RGB (3) or CMYK (4) tuples in 0..1, or None/pattern names."""
    if isinstance(color, (int, float)):
        color = (color,)
    if not isinstance(color, (tuple, list)) or not all(isinstance(c, (int, float)) for c in color):
        return None
    vals = [min(max(float(c), 0.0), 1.0) for c in color]
    if len(vals) == 1:
        return (vals[0], vals[0], vals[0])
    if len(vals) == 3:
        return (vals[0], vals[1], vals[2])
    if len(vals) == 4:
        c, m, y, k = vals
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _luminance(rgb: RGB) -> float:
    def ch(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_invisible_on(fg: RGB, bg: RGB) -> bool:
    return contrast_ratio(fg, bg) < MIN_VISIBLE_CONTRAST
