"""Word 5-gram fingerprints with winnowing (Schleimer, Wilkerson & Aiken, 2003).

Every shared run of at least K + WINDOW - 1 = 8 words is guaranteed to share at
least one stored fingerprint, which is enough to find a candidate source; the
exact matched regions are then computed by `align.py` on the full texts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from engine.similarity.tokens import Token

K = 5
WINDOW = 4


@dataclass(frozen=True, slots=True)
class Fingerprint:
    hash: int  # signed 64-bit (fits PostgreSQL BIGINT)
    pos: int  # index of the first word of the 5-gram
    char_start: int
    char_end: int


def hash_gram(words: list[str] | tuple[str, ...]) -> int:
    digest = hashlib.blake2b("\x1f".join(words).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def gram_hashes(tokens: list[Token], k: int = K) -> list[int]:
    norms = [t.norm for t in tokens]
    return [hash_gram(norms[i : i + k]) for i in range(len(norms) - k + 1)]


def winnow(hashes: list[int], window: int = WINDOW) -> list[int]:
    """Positions selected by robust winnowing (rightmost minimum per window)."""
    if not hashes:
        return []
    if len(hashes) <= window:
        m = min(hashes)
        return [max(i for i, h in enumerate(hashes) if h == m)]
    selected: list[int] = []
    last = -1
    for start in range(len(hashes) - window + 1):
        best = start
        for i in range(start, start + window):
            if hashes[i] <= hashes[best]:
                best = i
        if best != last:
            selected.append(best)
            last = best
    return selected


def fingerprints(tokens: list[Token], k: int = K, window: int = WINDOW) -> list[Fingerprint]:
    hashes = gram_hashes(tokens, k)
    return [
        Fingerprint(hashes[p], p, tokens[p].start, tokens[p + k - 1].end) for p in winnow(hashes, window)
    ]
