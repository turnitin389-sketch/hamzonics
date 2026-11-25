"""Deterministic sentence splitting: spaCy's rule-based sentencizer on a blank
multi-language pipeline (no downloaded model, so results never change between
machines). Line breaks always end a sentence (headings, list items, table rows).
Urdu full stop (۔) and question mark (؟) are sentence ends too."""

from __future__ import annotations

from functools import lru_cache

PUNCT = [".", "!", "?", "۔", "؟", "…", "。"]


def _guard_broken_torch() -> None:
    """spaCy's backend (thinc) imports torch if installed and only expects ImportError.
    When torch is installed but its native libraries cannot load (e.g. an outdated
    Visual C++ runtime on Windows) the first import raises OSError and spaCy crashes.
    A failed first attempt makes any later `import torch` raise ImportError, which
    thinc handles, so sentence splitting keeps working without torch."""
    try:
        import torch  # noqa: F401
    except Exception:
        pass


@lru_cache(maxsize=1)
def _nlp():  # type: ignore[no-untyped-def]
    _guard_broken_torch()
    import spacy

    nlp = spacy.blank("xx")
    nlp.add_pipe("sentencizer", config={"punct_chars": PUNCT})
    nlp.max_length = 2_000_000
    return nlp


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) char spans of sentences, whitespace trimmed."""
    spans: list[tuple[int, int]] = []
    pos = 0
    nlp = _nlp()
    for line in text.split("\n"):
        if line.strip():
            for sent in nlp(line).sents:
                s = pos + sent.start_char
                e = pos + sent.end_char
                while s < e and text[s].isspace():
                    s += 1
                while e > s and text[e - 1].isspace():
                    e -= 1
                if e > s:
                    spans.append((s, e))
        pos += len(line) + 1
    return spans
