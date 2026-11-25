"""Two AI detectors judged together.

The primary model (Fakespot RoBERTa, numpy) decides the windows (token counting); each
window is scored by both models and the scores are combined:
  "max"  - a window counts as AI if EITHER model is sure (catches more edited/paraphrased AI)
  "mean" - both models must lean AI (fewer false alarms)
Measured on the labelled test set before choosing (see scripts/eval_ai.py).
"""

from __future__ import annotations


class CombinedScorer:
    def __init__(self, primary, secondary, rule: str = "max") -> None:  # type: ignore[no-untyped-def]
        self.primary, self.secondary, self.rule = primary, secondary, rule
        self.name = f"{primary.name} + {secondary.name} ({rule})"

    def count_tokens(self, text: str) -> int:
        return self.primary.count_tokens(text)

    def score(self, text: str) -> float:
        a = self.primary.score(text)
        b = self.secondary.score(text)
        if self.rule == "mean":
            return (a + b) / 2
        if self.rule == "min":
            return min(a, b)
        return max(a, b)


class GateScorer:
    """A window counts as AI only when a second model CONFIRMS the primary model's verdict.

    The primary score is kept unless it reaches `threshold`; then the confirming model must
    score at least `confirm_threshold`, otherwise the window is capped just below `threshold`
    (shown as "possibly AI", never counted). The confirming model runs only on those windows,
    so human text costs no extra time.
    """

    def __init__(self, primary, confirm, threshold: float, confirm_threshold: float) -> None:  # type: ignore[no-untyped-def]
        self.primary, self.confirm = primary, confirm
        self.threshold, self.confirm_threshold = threshold, confirm_threshold
        self.name = f"{primary.name} confirmed by {confirm.name}"

    def count_tokens(self, text: str) -> int:
        return self.primary.count_tokens(text)

    def score(self, text: str) -> float:
        a = self.primary.score(text)
        if a < self.threshold:
            return a
        if self.confirm.score(text) >= self.confirm_threshold:
            return a
        return min(a, self.threshold - 1e-3)
