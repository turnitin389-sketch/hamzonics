"""AI-writing detection (see detect.py for how a document is scored)."""

from engine.ai.detect import AIOptions, AIResult, WindowScorer, detect_ai, segments_to_chars

__all__ = ["AIOptions", "AIResult", "WindowScorer", "detect_ai", "segments_to_chars"]
