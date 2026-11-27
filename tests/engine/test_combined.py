"""Combining AI detectors: rule "only" uses the second model's score with the first model's windows."""

from __future__ import annotations

from engine.ai.combined import CombinedScorer, GateScorer, SecondOnlyScorer
from engine.ai.detect import AIOptions, detect_ai


class _Fixed:
    def __init__(self, name: str, value: float) -> None:
        self.name, self.value, self.calls = name, value, 0

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def score(self, text: str) -> float:
        self.calls += 1
        return self.value


class _CounterOnly:
    name = "tok"

    def count_tokens(self, text: str) -> int:
        return len(text.split())


TEXT = " ".join(f"Sentence number {i} has a few plain words in it." for i in range(80))


def test_second_only_uses_second_score_and_first_windows() -> None:
    second = _Fixed("desk", 0.99)
    s = SecondOnlyScorer(_CounterOnly(), second)
    assert s.count_tokens("a b c") == 3
    assert s.score("x") == 0.99
    assert "desk" in s.name


def test_second_only_equals_max_when_first_is_low() -> None:
    """With a first model that never fires, "only" gives the same result as "max"."""
    first, second, confirm = _Fixed("fake", 0.0), _Fixed("desk", 0.99), _Fixed("sa", 0.9)
    opts = AIOptions(threshold=0.9, possible_threshold=0.7, min_words=50)
    a = detect_ai(TEXT, GateScorer(SecondOnlyScorer(_CounterOnly(), second), confirm, 0.9, 0.72), opts)
    b = detect_ai(TEXT, GateScorer(CombinedScorer(first, second, "max"), confirm, 0.9, 0.72), opts)
    assert a.percent == b.percent == 100.0


def test_confirming_model_still_vetoes_in_second_only_mode() -> None:
    second, confirm = _Fixed("desk", 0.99), _Fixed("sa", 0.1)
    opts = AIOptions(threshold=0.9, possible_threshold=0.7, min_words=50)
    r = detect_ai(TEXT, GateScorer(SecondOnlyScorer(_CounterOnly(), second), confirm, 0.9, 0.72), opts)
    assert r.percent == 0.0
