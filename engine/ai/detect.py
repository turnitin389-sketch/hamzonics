"""AI-writing detection for a whole document.

How a document is scored (modelled on how commercial checkers report AI writing):

1. Qualifying text: prose sentences of at least MIN_SENTENCE_WORDS words, outside the
   reference list. Headings, table cells, list fragments and the bibliography do not count.
2. Windows: consecutive qualifying sentences are packed into windows of up to
   `window_tokens` tokens. With `overlap`, a second set of windows starts half a window
   later, so every sentence is judged in two different contexts.
3. Each window is classified by the model (probability that it is AI-generated). A
   sentence's score is the mean of the windows that contain it.
4. Sentences scoring >= `threshold` are "AI-generated" and are highlighted; sentences
   between `possible_threshold` and `threshold` are shown as "possibly AI" but are not
   counted. AI % = AI-generated words / qualifying words.
5. Under `min_words` qualifying words there is not enough text for a reliable result.

The result is stored by WORD index, so the same text gives the same highlights whatever
file format it came in.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Protocol

from engine.similarity.citations import bibliography_start
from engine.similarity.merge import round2
from engine.similarity.sentences import split_sentences
from engine.similarity.tokens import tokenize, word_index_at

MIN_SENTENCE_WORDS = 5
PARAGRAPH_MIN_TOKENS = 120  # a window may end at a paragraph break once it has this many tokens


class WindowScorer(Protocol):
    """Probability (0..1) that each text is AI-generated."""

    name: str

    def count_tokens(self, text: str) -> int: ...

    def score(self, text: str) -> float: ...


@dataclass(frozen=True)
class AIOptions:
    threshold: float = 0.995
    possible_threshold: float = 0.9
    window_tokens: int = 400
    overlap: bool = True
    min_words: int = 300


@dataclass
class AIResult:
    available: bool
    percent: float | None = None
    qualifying_words: int = 0
    ai_words: int = 0
    model: str = ""
    message: str = ""
    # word_start, word_end (exclusive), score, level ("ai" | "possible")
    segments: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "available": self.available, "percent": self.percent, "qualifying_words": self.qualifying_words,
            "ai_words": self.ai_words, "model": self.model, "message": self.message, "segments": self.segments,
        }


def clean_for_model(text: str) -> str:
    """Same normalisation as the model was trained with (whitespace, markup)."""
    text = re.sub(r"<[^>]{0,200}>", "", text)
    text = unescape(text)
    text = re.sub(r"[\r\n\t]+", " ", text)
    return re.sub(r" +", " ", text.replace(" ,", ",")).strip()


@dataclass(frozen=True)
class _Sentence:
    start: int  # char offsets in the document
    end: int
    word_start: int
    word_end: int

    @property
    def words(self) -> int:
        return self.word_end - self.word_start


# Common Roman-Urdu words (Urdu written in English letters). Words that are also normal
# English words ("main", "is", "to", "me", "us") are left out so English is never mistaken.
_ROMAN_URDU = frozenset(
    "hai hain hae hy ka ki ke ko mein mai aur ye yeh wo woh kya nahi nahin ni se par pe jo bhi tha thi thay "
    "raha rahi rahe kar karna karo karein kiya kiye hum aap ap tum mujhe mujhy humein unhein inhein apna apni "
    "apne agar lekin magar kyun kyunke kyunki jaise jaisa waise sath saath bohat bahut zyada kam abhi phir "
    "chahiye chahein sakte sakta sakti hoga hogi honge diya diye gaya gayi gaye wala wali wale liye hota hoti "
    "maine hamara hamari tumhara inko unko isko usko yahan wahan kahan dobara batao bata dein lein dekh".split()
)


def _is_roman_urdu(chunk: str) -> bool:
    words = [w.strip(".,;:!?\"'()").lower() for w in chunk.split()]
    words = [w for w in words if w]
    return len(words) >= 4 and sum(w in _ROMAN_URDU for w in words) >= 0.2 * len(words)


def _is_english_script(chunk: str) -> bool:
    """The model was trained on English only: Urdu, Arabic, Chinese ... sentences, and Urdu
    written in English letters (Roman Urdu), are not scored."""
    letters = [ch for ch in chunk if ch.isalpha()]
    latin = sum(1 for ch in letters if ch.isascii())
    return bool(letters) and latin >= 0.8 * len(letters) and not _is_roman_urdu(chunk)


def _qualifying(text: str) -> tuple[list[_Sentence], int]:
    """(English prose sentences, words in non-English prose sentences that were skipped)."""
    tokens = tokenize(text)
    bib = bibliography_start(text)
    out: list[_Sentence] = []
    other_language_words = 0
    for s, e in split_sentences(text):
        if bib is not None and s >= bib:
            break
        ws, we = word_index_at(tokens, s), word_index_at(tokens, e)
        if we - ws < MIN_SENTENCE_WORDS:
            continue
        chunk = text[s:e]
        letters = sum(ch.isalpha() for ch in chunk)
        if letters < 0.6 * len(chunk.replace(" ", "")):  # tables of numbers, references, formulas
            continue
        if not _is_english_script(chunk):
            other_language_words += we - ws
            continue
        out.append(_Sentence(s, e, ws, we))
    return out, other_language_words


def _windows(sents: list[_Sentence], text: str, scorer: WindowScorer, limit: int, offset: int) -> list[tuple[int, int]]:
    """Index ranges [i, j) of consecutive sentences, each window <= limit tokens.
    A gap of more than 40 characters between sentences (skipped heading, table,
    page break) does not stop a window: the model sees prose only."""
    windows: list[tuple[int, int]] = []
    i = 0
    if offset:
        windows.append((0, min(offset, len(sents))))
        i = min(offset, len(sents))
    while i < len(sents):
        j, used = i, 0
        while j < len(sents):
            n = scorer.count_tokens(text[sents[j].start : sents[j].end])
            if j > i and used + n > limit:
                break
            used += n
            j += 1
            # Stop at a paragraph break once the window has enough text: otherwise an AI
            # paragraph and the human paragraph next to it are judged together and the
            # human one is flagged too (mixed documents scored 64-100% instead of 54-66%).
            if j < len(sents) and used >= PARAGRAPH_MIN_TOKENS and "\n" in text[sents[j - 1].end : sents[j].start]:
                break
        windows.append((i, j))
        i = j
    return [w for w in windows if w[1] > w[0]]


def detect_ai(
    text: str,
    scorer: WindowScorer,
    options: AIOptions | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> AIResult:
    options = options or AIOptions()
    sents, other_language_words = _qualifying(text)
    qualifying = sum(s.words for s in sents)
    note = (f" {other_language_words:,} words in other languages (e.g. Urdu) were not checked: "
            "AI-writing detection is available for English text only.") if other_language_words else ""
    if qualifying < options.min_words:
        if other_language_words > qualifying:
            message = ("AI-writing detection is available for English text only; this document is mostly in "
                       f"another language ({other_language_words:,} words), so it was not checked for AI writing.")
        else:
            message = (f"Not enough English prose to check for AI writing: {qualifying} qualifying words "
                       f"(at least {options.min_words} are needed).{note}")
        return AIResult(available=False, qualifying_words=qualifying, model=scorer.name, message=message)

    passes = [_windows(sents, text, scorer, options.window_tokens, 0)]
    if options.overlap and len(passes[0]) > 1:
        first = passes[0][0]
        passes.append(_windows(sents, text, scorer, options.window_tokens, max(1, (first[1] - first[0]) // 2)))
    total = sum(len(p) for p in passes)

    sums = [0.0] * len(sents)
    counts = [0] * len(sents)
    done = 0
    for windows in passes:
        for i, j in windows:
            chunk = clean_for_model(" ".join(text[s.start : s.end] for s in sents[i:j]))
            p = scorer.score(chunk)
            for k in range(i, j):
                sums[k] += p
                counts[k] += 1
            done += 1
            if progress:
                progress(done, total)

    segments: list[dict[str, Any]] = []
    ai_words = 0
    for k, s in enumerate(sents):
        p = sums[k] / max(counts[k], 1)
        level = "ai" if p >= options.threshold else "possible" if p >= options.possible_threshold else None
        if level is None:
            continue
        if level == "ai":
            ai_words += s.words
        prev = segments[-1] if segments else None
        if prev and prev["level"] == level and prev["word_end"] == s.word_start:
            prev["word_end"] = s.word_end
            prev["_scores"].append((p, s.words))
        else:
            segments.append({"word_start": s.word_start, "word_end": s.word_end, "level": level,
                             "_scores": [(p, s.words)]})
    for seg in segments:
        scores = seg.pop("_scores")
        seg["score"] = round(sum(p * w for p, w in scores) / max(sum(w for _, w in scores), 1), 4)

    return AIResult(
        available=True, percent=round2(100.0 * ai_words / qualifying), qualifying_words=qualifying,
        ai_words=ai_words, model=scorer.name, segments=segments, message=note.strip(),
    )


def segments_to_chars(text: str, segments: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Word-indexed segments -> char offsets in `text` (for highlighting)."""
    tokens = tokenize(text)
    out = []
    for seg in segments:
        ws, we = seg["word_start"], min(seg["word_end"], len(tokens))
        if ws >= we:
            continue
        out.append({**seg, "start": tokens[ws].start, "end": tokens[we - 1].end})
    return out
