"""AI-writing detection: document scoring logic (fake scorer) and the real model (if downloaded)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.ai import AIOptions, detect_ai, segments_to_chars
from engine.ai.detect import clean_for_model

AI_MARK = "Moreover"


class FakeScorer:
    """'AI' = windows containing the word Moreover; token count = word count."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def score(self, text: str) -> float:
        self.calls.append(text)
        return 0.9995 if AI_MARK in text else 0.02


HUMAN = "My grandfather grew wheat near Multan and he told us stories about the canal every single evening."
AI = f"{AI_MARK}, it is crucial to acknowledge that agricultural productivity depends on numerous interrelated factors."


def _doc(parts: list[str]) -> str:
    return "\n\n".join(" ".join(p for _ in range(6)) for p in parts)


class _Fixed:
    def __init__(self, value: float) -> None:
        self.value, self.calls, self.name = value, 0, f"fixed{value}"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def score(self, text: str) -> float:
        self.calls += 1
        return self.value


def test_gate_scorer_needs_confirmation_for_ai() -> None:
    from engine.ai.combined import GateScorer

    # Primary says AI, confirmer agrees -> AI.
    assert GateScorer(_Fixed(0.9999), _Fixed(0.9), 0.995, 0.72).score("x") == 0.9999
    # Primary says AI, confirmer disagrees -> capped below the AI threshold ("possibly AI").
    capped = GateScorer(_Fixed(0.9999), _Fixed(0.5), 0.995, 0.72).score("x")
    assert 0.9 <= capped < 0.995
    # Primary says human -> confirmer is never run (no extra time for human text).
    confirm = _Fixed(0.99)
    assert GateScorer(_Fixed(0.3), confirm, 0.995, 0.72).score("x") == 0.3 and confirm.calls == 0


def test_gate_scorer_in_document() -> None:
    from engine.ai.combined import GateScorer

    text = _doc([HUMAN, AI, HUMAN, AI])
    opts = AIOptions(threshold=0.995, possible_threshold=0.9, window_tokens=60, overlap=False, min_words=20)
    agree = detect_ai(text, GateScorer(FakeScorer(), _Fixed(0.9), 0.995, 0.72), opts)
    disagree = detect_ai(text, GateScorer(FakeScorer(), _Fixed(0.1), 0.995, 0.72), opts)
    assert agree.percent > 0
    assert disagree.percent == 0 and any(s["level"] == "possible" for s in disagree.segments)


def test_ai_paragraph_is_highlighted_and_counted() -> None:
    text = _doc([HUMAN, HUMAN, AI, HUMAN])
    res = detect_ai(text, FakeScorer(), AIOptions(window_tokens=60, min_words=50))
    assert res.available
    ai_segments = [s for s in res.segments if s["level"] == "ai"]
    assert ai_segments, res
    chars = segments_to_chars(text, ai_segments)
    flagged = " ".join(text[s["start"] : s["end"]] for s in chars)
    assert AI_MARK in flagged and "grandfather" not in flagged.split(AI_MARK)[0][-30:]
    assert 10 < res.percent < 50


def test_all_human_is_zero_and_all_ai_is_hundred() -> None:
    assert detect_ai(_doc([HUMAN] * 5), FakeScorer(), AIOptions(min_words=50)).percent == 0.0
    assert detect_ai(_doc([AI] * 5), FakeScorer(), AIOptions(min_words=50)).percent == 100.0


def test_short_text_is_not_checked() -> None:
    res = detect_ai(HUMAN, FakeScorer(), AIOptions(min_words=300))
    assert not res.available and "Not enough" in res.message


def test_bibliography_is_not_checked() -> None:
    text = _doc([HUMAN] * 4) + "\n\nReferences\n\n" + _doc([AI] * 2)
    scorer = FakeScorer()
    res = detect_ai(text, scorer, AIOptions(min_words=50))
    assert res.percent == 0.0 and not any(AI_MARK in c for c in scorer.calls)


def test_windows_respect_token_limit_and_overlap() -> None:
    scorer = FakeScorer()
    detect_ai(_doc([HUMAN] * 10), scorer, AIOptions(window_tokens=80, overlap=True, min_words=50))
    assert all(len(c.split()) <= 80 for c in scorer.calls)
    single = FakeScorer()
    detect_ai(_doc([HUMAN] * 10), single, AIOptions(window_tokens=80, overlap=False, min_words=50))
    assert len(scorer.calls) > len(single.calls)  # second, shifted pass


def test_non_english_text_is_not_scored() -> None:
    urdu = "پاکستان جنوبی ایشیا کا ایک ملک ہے اور اس کی آبادی چوبیس کروڑ سے زیادہ ہے۔ " * 80
    scorer = FakeScorer()
    res = detect_ai(urdu, scorer, AIOptions(min_words=50))
    assert not res.available and "English text only" in res.message and scorer.calls == []

    mixed = _doc([AI] * 5) + "\n\n" + urdu
    res = detect_ai(mixed, FakeScorer(), AIOptions(min_words=50))
    assert res.available and res.percent == 100.0 and "not checked" in res.message


def test_roman_urdu_is_not_scored_but_english_is() -> None:
    from engine.ai.detect import _is_english_script

    assert not _is_english_script('Claims: "Nation\'s leading" jaise daawe maine hata diye hain, kyunke inhein saabit karna mushkil hai.')
    assert not _is_english_script("Agar aap pricing aur implementation ki details bata dein to main woh answers bhi likh dunga.")
    for english in (HUMAN, AI, "Main results of the study show that the pass rate in Lahore is higher than in Karachi.",
                    "The water level is low; to me it is a sign of drought in the region this year."):
        assert _is_english_script(english), english


def test_clean_for_model() -> None:
    assert clean_for_model("a\n\nb\t c ,d <b>x</b> &amp;") == "a b c,d x &"


MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models"


@pytest.mark.skipif(not any(MODEL_DIR.glob("models--fakespot-ai--*/snapshots/*/model.safetensors")),
                    reason="AI model not downloaded (it is fetched on the first real check)")
def test_real_model_separates_ai_from_human() -> None:
    from api.config import get_settings
    from engine.ai.model import get_scorer

    s = get_settings()
    scorer = get_scorer(s.ai_model, s.ai_model_revision, MODEL_DIR)
    ai = ("Artificial intelligence has emerged as a transformative force across numerous sectors, reshaping the way "
          "organizations operate and deliver value. Moreover, it is crucial to acknowledge the ethical considerations "
          "that accompany these advancements, including data privacy and algorithmic bias.")
    human = ("We present a simple trick for training sequence models: we reverse the order of the words in all source "
             "sentences, which introduces many short term dependencies between source and target that make the "
             "optimization problem easier. On the WMT14 English to French task our system obtains a BLEU score of 34.8.")
    assert scorer.score(ai) > 0.9
    assert scorer.score(human) < 0.5


def test_ai_highlights_exclude_skipped_words() -> None:
    skipped = "Short heading"
    text = f"{AI}\n{skipped}\n{AI}"
    result = detect_ai(text, FakeScorer(), AIOptions(min_words=1))
    highlights = segments_to_chars(text, result.segments)

    assert [text[span["start"]:span["end"]] for span in highlights] == [
        AI.rstrip("."), AI.rstrip("."),
    ]
