"""Quotes, in-text citations and the bibliography section.

Each similarity region is put in one group:
- cited_and_quoted     inside quotation marks AND a citation is nearby
- missing_citation     inside quotation marks, no citation nearby
- missing_quotations   a citation is nearby, but no quotation marks
- not_cited_or_quoted  neither
- bibliography         the region is inside the reference list

"Nearby" = from the start of the sentence where the region starts to the end of
the sentence after the one where it ends (citations often follow a quote).
GROBID (optional, Phase 4+) can replace the regex bibliography detection.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

GROUPS = ("not_cited_or_quoted", "missing_quotations", "missing_citation", "cited_and_quoted", "bibliography")

_QUOTE_RES = [
    re.compile(r"“[^“”\n]{2,}?”"),  # “ … ”
    re.compile(r'"[^"\n]{2,}?"'),  # " … "
    re.compile(r"«[^«»\n]{2,}?»"),  # « … »
    re.compile(r"„[^„“”\n]{2,}?[“”]"),  # „ … “
    re.compile(r"‘[^‘’\n]{8,}?’(?!\w)"),  # ‘ … ’ (long enough to not be an apostrophe)
]

_NAME = r"[A-Z][A-Za-zÀ-ɏ'\-]+"
_YEAR = r"(?:1[5-9]\d\d|20\d\d)[a-z]?|n\.d\."
_CITATION_RES = [
    # (Smith, 2019) (Smith & Khan, 2019, p. 4) (Smith et al. 2019; Ali 2020)
    re.compile(rf"\((?:[^()]*?{_NAME}[^()]*?,?\s*(?:{_YEAR}))(?:[^()]*)\)"),
    # Smith (2019)  Smith et al. (2019, p. 4)
    re.compile(rf"{_NAME}(?:\s+(?:and|&)\s+{_NAME}|\s+et al\.)?\s+\((?:{_YEAR})(?:[^()]*)\)"),
    # [12] [3, 4] [1-5]
    re.compile(r"\[\d{1,3}(?:\s*[,–\-]\s*\d{1,3})*\]"),
]

_BIB_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\s*)?(references|reference list|bibliography|works cited|literature cited|sources|"
    r"حوالہ جات|کتابیات)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class CitationContext:
    quotes: list[tuple[int, int]]
    citations: list[tuple[int, int]]
    sentences: list[tuple[int, int]]
    bibliography_start: int | None


def quote_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for rx in _QUOTE_RES:
        spans.extend((m.start(), m.end()) for m in rx.finditer(text))
    return _union(spans)


def citation_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for rx in _CITATION_RES:
        spans.extend((m.start(), m.end()) for m in rx.finditer(text))
    return sorted(spans)


def bibliography_start(text: str) -> int | None:
    """Char offset where the reference list starts (last matching heading in the
    second half of the document), or None."""
    half = len(text) // 2
    starts = [m.start() for m in _BIB_HEADING_RE.finditer(text) if m.start() >= half]
    return starts[-1] if starts else None


def build_context(text: str, sentences: list[tuple[int, int]]) -> CitationContext:
    return CitationContext(quote_spans(text), citation_spans(text), sentences, bibliography_start(text))


def group_for(ctx: CitationContext, start: int, end: int) -> str:
    if ctx.bibliography_start is not None and start >= ctx.bibliography_start:
        return "bibliography"
    quoted = _covered(ctx.quotes, start, end) >= 0.8 * max(end - start, 1)
    w_start, w_end = _window(ctx.sentences, start, end)
    cited = any(cs < w_end and ce > w_start for cs, ce in ctx.citations)
    if quoted and cited:
        return "cited_and_quoted"
    if quoted:
        return "missing_citation"
    if cited:
        return "missing_quotations"
    return "not_cited_or_quoted"


def _window(sentences: list[tuple[int, int]], start: int, end: int) -> tuple[int, int]:
    if not sentences:
        return start, end
    starts = [s for s, _ in sentences]
    i = max(bisect_right(starts, start) - 1, 0)
    j = max(bisect_right(starts, max(end - 1, start)) - 1, 0)
    j = min(j + 1, len(sentences) - 1)
    return min(sentences[i][0], start), max(sentences[j][1], end)


def _covered(spans: list[tuple[int, int]], start: int, end: int) -> int:
    return sum(max(0, min(e, end) - max(s, start)) for s, e in spans)


def _union(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out
