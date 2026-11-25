from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

FLAG_ORDER = [
    "lookalike_characters",
    "invisible_characters",
    "hidden_text_vanish",
    "hidden_text_color",
    "hidden_text_tiny",
    "text_outside_page",
    "image_only_pages",
]

SNIPPET_MAX = 200


@dataclass
class Finding:
    """One place where a trick was found."""

    type: str
    count: int
    page: int
    text: str = ""  # what was found (original characters / hidden words), shortened
    start: int | None = None  # char offsets in the final clean text (character-level flags)
    end: int | None = None
    detail: str | None = None  # e.g. the cleaned word, or why text counts as hidden

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("type")
        d["text"] = d["text"][:SNIPPET_MAX]
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class Flag:
    type: str
    count: int
    locations: list[dict[str, Any]] = field(default_factory=list)


def aggregate(findings: list[Finding]) -> list[Flag]:
    """Group findings by type, in a fixed order, with locations sorted by page then offset."""
    by_type: dict[str, list[Finding]] = {}
    for f in findings:
        by_type.setdefault(f.type, []).append(f)
    flags: list[Flag] = []
    for t in FLAG_ORDER + sorted(set(by_type) - set(FLAG_ORDER)):
        items = by_type.get(t)
        if not items:
            continue
        items.sort(key=lambda f: (f.page, f.start if f.start is not None else -1, f.text))
        flags.append(Flag(t, sum(f.count for f in items), [f.to_dict() for f in items]))
    return flags
