"""Character-level cleaning: invisible characters and lookalike letters.

Care is taken not to damage real Urdu/Arabic/Russian/Greek text:
- ZWNJ/ZWJ and LRM/RLM are normal in Urdu; they are only removed when they
  are not next to a right-to-left letter.
- Cyrillic/Greek letters are only replaced inside a word that also has Latin
  letters, or in a whole-lookalike word inside mostly-Latin text. Words that
  contain letters with no Latin twin (e.g. "привет") are real and kept.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from engine.flags.types import Finding

# --------------------------------------------------------------------- invisible

_ALWAYS_INVISIBLE = {
    0x200B,  # zero width space
    0x2060, 0x2061, 0x2062, 0x2063, 0x2064,  # word joiner, invisible operators
    0xFEFF,  # zero width no-break space / BOM
    0x00AD,  # soft hyphen
    0x180E,  # Mongolian vowel separator
    0x034F,  # combining grapheme joiner
    0x115F, 0x1160, 0x3164, 0xFFA0,  # Hangul fillers
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,  # bidi embeddings/overrides
    0x2066, 0x2067, 0x2068, 0x2069,  # bidi isolates
}
# Legitimate in right-to-left scripts (Urdu, Arabic, Persian ...).
_CONTEXT_INVISIBLE = {0x200C, 0x200D, 0x200E, 0x200F, 0x061C}


def _is_tag_or_selector(cp: int) -> bool:
    return 0xE0000 <= cp <= 0xE007F or 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF


def _is_rtl(ch: str) -> bool:
    return unicodedata.bidirectional(ch) in ("R", "AL", "NSM", "AN")


def _is_invisible(text: str, i: int) -> bool:
    cp = ord(text[i])
    if cp in _ALWAYS_INVISIBLE:
        return True
    if 0xFE00 <= cp <= 0xFE0F:
        # Variation selectors are normal after emoji/symbols; suspicious after letters.
        return i > 0 and text[i - 1].isalnum()
    if _is_tag_or_selector(cp):
        return True
    if cp in _CONTEXT_INVISIBLE:
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        return not ((prev and _is_rtl(prev)) or (nxt and _is_rtl(nxt)))
    return False


# --------------------------------------------------------------------- lookalikes

# Cyrillic and Greek letters that look the same as a Latin letter in common fonts.
CONFUSABLES: dict[str, str] = {
    # Cyrillic lower case
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
    "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w", "һ": "h", "ӏ": "l", "ѵ": "v",
    # Cyrillic upper case
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S", "Ԛ": "Q", "Ԝ": "W", "Ӏ": "I",
    # Greek
    "ο": "o", "ν": "v", "ι": "i", "κ": "k", "ρ": "p", "τ": "t", "υ": "u",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M",
    "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
}

_LETTERS_RE = re.compile(r"[^\W\d_]+|[\U0001D400-\U0001D7FF０-９Ａ-Ｚａ-ｚ]+")


def _script(ch: str) -> str:
    name = unicodedata.name(ch, "")
    return name.split(" ", 1)[0] if name else ""


def _compat_letter(ch: str) -> str | None:
    """Fullwidth / mathematical alphanumerics -> plain ASCII (via NFKC)."""
    cp = ord(ch)
    if 0xFF10 <= cp <= 0xFF5A or 0x1D400 <= cp <= 0x1D7FF:
        folded = unicodedata.normalize("NFKC", ch)
        if len(folded) == 1 and folded.isascii() and folded.isalnum():
            return folded
    return None


def _latin_dominant(text: str) -> bool:
    latin = other = 0
    for ch in text:
        if not ch.isalpha():
            continue
        s = _script(ch)
        if s == "LATIN":
            latin += 1
        elif s in ("CYRILLIC", "GREEK") and ch not in CONFUSABLES:
            other += 1
    return latin > 0 and other <= 0.2 * (latin + other)


# --------------------------------------------------------------------- cleaning


@dataclass
class CharCleanResult:
    text: str
    findings: list[Finding]


def clean_characters(text: str, page: int = 1) -> CharCleanResult:
    text, invisible = _remove_invisible(text, page)
    text, lookalike = _replace_lookalikes(text, page)
    for f in invisible:
        assert f.start is not None
        f.text = text[max(0, f.start - 20) : f.start + 20]
    return CharCleanResult(text, invisible + lookalike)


def _remove_invisible(text: str, page: int) -> tuple[str, list[Finding]]:
    out: list[str] = []
    findings: list[Finding] = []
    i = 0
    n = len(text)
    while i < n:
        if _is_invisible(text, i):
            pos = len(out)
            if findings and findings[-1].start == pos:
                findings[-1].count += 1
            else:
                findings.append(Finding("invisible_characters", 1, page, start=pos, end=pos))
            names = findings[-1].detail
            code = f"U+{ord(text[i]):04X}"
            findings[-1].detail = code if not names else (names if code in names else f"{names} {code}")
            i += 1
            # "word ​ word" would leave two spaces; drop the extra one.
            if out and out[-1] == " " and i < n and text[i] == " ":
                i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out), findings


def _replace_lookalikes(text: str, page: int) -> tuple[str, list[Finding]]:
    latin_doc = _latin_dominant(text)
    chars = list(text)
    findings: list[Finding] = []
    for m in _LETTERS_RE.finditer(text):
        word = m.group(0)
        has_latin = any(_script(c) == "LATIN" for c in word)
        real_other = any(_script(c) in ("CYRILLIC", "GREEK") and c not in CONFUSABLES for c in word)
        replace_script = not real_other and (has_latin or (latin_doc and len(word) >= 2))
        replaced = 0
        for k, c in enumerate(word):
            new = _compat_letter(c)
            if new is None and replace_script:
                new = CONFUSABLES.get(c)
            if new is not None:
                chars[m.start() + k] = new
                replaced += 1
        if replaced:
            findings.append(
                Finding(
                    "lookalike_characters",
                    replaced,
                    page,
                    text=word,
                    start=m.start(),
                    end=m.end(),
                    detail="".join(chars[m.start() : m.end()]),
                )
            )
    return "".join(chars), findings
