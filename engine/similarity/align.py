"""Exact and near-copy alignment between a submission and one candidate source.

1. Every 5-gram of the submission that also occurs in the source gives a hit
   (query position i, source position p). Hits on the same diagonal (p - i)
   at consecutive positions form an exact run.
2. Runs are chosen longest-first without overlapping in the submission.
3. Neighbouring runs separated by a small gap (a few changed/inserted words)
   whose source positions continue in the same order are merged into one
   near-copy region.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.similarity.fingerprint import K, gram_hashes
from engine.similarity.tokens import Token

MAX_QUERY_GAP = 3  # words that may differ between two exact runs
MAX_SOURCE_GAP = 6
MAX_POSITIONS_PER_GRAM = 50  # very repetitive phrases


@dataclass
class Region:
    q_start: int  # word indices in the submission, end exclusive
    q_end: int
    s_start: int  # word indices in the source, end exclusive
    s_end: int
    kind: str  # exact | near

    @property
    def words(self) -> int:
        return self.q_end - self.q_start


def align(query: list[Token], source: list[Token], k: int = K) -> list[Region]:
    q_hashes = gram_hashes(query, k)
    s_index: dict[int, list[int]] = {}
    for p, h in enumerate(gram_hashes(source, k)):
        positions = s_index.setdefault(h, [])
        if len(positions) < MAX_POSITIONS_PER_GRAM:
            positions.append(p)

    # Diagonal runs of consecutive gram hits: diag -> [q_first, q_last]
    open_runs: dict[int, list[int]] = {}
    runs: list[tuple[int, int, int]] = []  # (q_first_gram, q_last_gram, diag)
    for i, h in enumerate(q_hashes):
        hits = s_index.get(h)
        still_open: dict[int, list[int]] = {}
        if hits:
            for p in hits:
                d = p - i
                run = open_runs.get(d)
                if run is not None and run[1] == i - 1:
                    run[1] = i
                    still_open[d] = run
                else:
                    still_open[d] = [i, i]
        for d, run in open_runs.items():
            if d not in still_open:
                runs.append((run[0], run[1], d))
        open_runs = still_open
    runs.extend((r[0], r[1], d) for d, r in open_runs.items())

    # Longest first; ties broken by position for determinism.
    candidates = sorted(
        (Region(a, b + k, a + d, b + k + d, "exact") for a, b, d in runs),
        key=lambda r: (-r.words, r.q_start, r.s_start),
    )
    taken: list[Region] = []
    covered = bytearray(len(query))
    for r in candidates:
        if any(covered[r.q_start : r.q_end]):
            # Keep the non-overlapping tail/head if it is still a full gram long.
            free = [i for i in range(r.q_start, r.q_end) if not covered[i]]
            if len(free) < k or free[-1] - free[0] + 1 != len(free):
                continue
            shift = free[0] - r.q_start
            r = Region(free[0], free[-1] + 1, r.s_start + shift, r.s_start + shift + len(free), "exact")
        for i in range(r.q_start, r.q_end):
            covered[i] = 1
        taken.append(r)
    taken.sort(key=lambda r: r.q_start)
    return _merge_near(taken)


def _merge_near(regions: list[Region]) -> list[Region]:
    merged: list[Region] = []
    for r in regions:
        if merged:
            last = merged[-1]
            q_gap = r.q_start - last.q_end
            s_gap = r.s_start - last.s_end
            if 0 <= q_gap <= MAX_QUERY_GAP and 0 <= s_gap <= MAX_SOURCE_GAP:
                merged[-1] = Region(last.q_start, r.q_end, last.s_start, max(last.s_end, r.s_end), "near")
                continue
        merged.append(r)
    return merged
