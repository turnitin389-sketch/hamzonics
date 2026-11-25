"""Integrity flags: tricks that hide text from a checker or break matching.

Every flag is detected AND cleaned before any other check runs:
- lookalike_characters   Cyrillic/Greek/fullwidth/math letters posing as Latin
- invisible_characters   zero-width, bidi-control, tag and similar characters
- hidden_text_vanish     DOCX text with the "hidden" attribute
- hidden_text_color      text the same colour as its background (e.g. white on white)
- hidden_text_tiny       font size below 4 pt
- text_outside_page      PDF text placed outside the visible page
- image_only_pages       pages with no text layer (read with OCR)

All `count` values are characters (whitespace excluded), except image_only_pages (pages).
"""

from engine.flags.chars import CharCleanResult, clean_characters
from engine.flags.types import FLAG_ORDER, Finding, Flag, aggregate

__all__ = ["FLAG_ORDER", "CharCleanResult", "Finding", "Flag", "aggregate", "clean_characters"]
