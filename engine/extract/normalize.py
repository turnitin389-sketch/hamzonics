"""Text normalisation and word counting.

Phase 1 does layout clean-up only (Unicode NFC, line endings, hyphenation, spaces).
Phase 2 adds integrity cleaning (confusables, invisible characters) before checks.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Letters/digits plus Arabic-script and Latin combining marks, so Urdu words with
# diacritics (zer, zabar, pesh ...) are counted as one word.
_MARKS = "̀-ͯؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۤۧۨ-ۭ"
_WORD_RE = re.compile(rf"(?:[^\W_]|[{_MARKS}])+(?:['’\-](?:[^\W_]|[{_MARKS}])+)*")
# Public: the similarity engine tokenises with exactly the same rule as the word count.
WORD_RE = _WORD_RE

_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(?=[a-z])")
_SPACES_RE = re.compile(r"[ \t  -   　]+")
_MANY_NEWLINES_RE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    text = text.replace(" ", "\n").replace(" ", "\n\n")
    # "exam-\nple" -> "example" (only when the next line starts lower-case)
    text = _HYPHEN_BREAK_RE.sub(r"\1", text)
    lines = [_SPACES_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MANY_NEWLINES_RE.sub("\n\n", text)
    return text.strip()


def count_words(text: str) -> int:
    return sum(1 for _ in _WORD_RE.finditer(text))


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def text_sha256(clean_text: str) -> str:
    return hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
