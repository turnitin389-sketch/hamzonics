"""Word tokens with character offsets. Uses the same word rule as the word count,
so "matched words / total words" is consistent with the reported word count."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from engine.extract.normalize import WORD_RE


@dataclass(frozen=True, slots=True)
class Token:
    norm: str  # folded form used for matching
    start: int  # char offsets in the clean text
    end: int


def fold(word: str) -> str:
    """Case-fold and drop combining marks (accents, Urdu harakat), unify apostrophes."""
    w = unicodedata.normalize("NFKD", word.casefold().replace("’", "'"))
    return "".join(c for c in w if not unicodedata.combining(c))


def tokenize(text: str) -> list[Token]:
    return [Token(fold(m.group(0)), m.start(), m.end()) for m in WORD_RE.finditer(text)]


def canonical_sha256(text: str) -> str:
    """Identity of a document's WORDS, independent of layout: the same essay saved as
    DOCX or as PDF (different line breaks, ligatures, spacing) gets the same hash."""
    import hashlib

    return hashlib.sha256(" ".join(t.norm for t in tokenize(text)).encode("utf-8")).hexdigest()


def word_index_at(tokens: list[Token], char_pos: int) -> int:
    """Index of the first token that ends after `char_pos` (binary search)."""
    lo, hi = 0, len(tokens)
    while lo < hi:
        mid = (lo + hi) // 2
        if tokens[mid].end <= char_pos:
            lo = mid + 1
        else:
            hi = mid
    return lo
