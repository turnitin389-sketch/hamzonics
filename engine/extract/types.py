from __future__ import annotations

from dataclasses import dataclass, field

from engine.flags.types import Flag


@dataclass(frozen=True)
class PageText:
    """Clean text of one page (or of the whole file for formats without pages)."""

    number: int  # 1-based
    text: str
    ocr: bool = False


@dataclass(frozen=True)
class ExtractedDocument:
    kind: str
    text: str  # clean text: cleaned pages joined with "\n\n"
    pages: list[PageText]
    # Offsets map: one {"page", "start", "end", "ocr"} entry per page, char offsets into `text`.
    page_offsets: list[dict[str, int | bool]] = field(default_factory=list)
    # Integrity flags found (and already cleaned out of `text`).
    flags: list[Flag] = field(default_factory=list)

    @property
    def ocr_page_count(self) -> int:
        return sum(1 for p in self.pages if p.ocr)

    def flag_count(self, flag_type: str) -> int:
        return next((f.count for f in self.flags if f.type == flag_type), 0)
