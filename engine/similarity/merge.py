"""Word-level scoring.

Raw matches may overlap (several sources, exact + paraphrase). Each submission word
is given to exactly one match:
  1. stronger match type first: exact > near > paraphrase/crosslang
  2. then the source with more matched words overall
  3. then source key (deterministic tie-break)
Similarity % = assigned words / total words. Filters (exclude quotes, bibliography,
small matches, chosen sources) are applied to the raw matches and the assignment
is recomputed, so excluding a source can hand its words to the next-best source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

PRIORITY = {"exact": 0, "near": 1, "paraphrase": 2, "crosslang": 2}
QUOTED_GROUPS = frozenset({"missing_citation", "cited_and_quoted"})


def round2(value: float) -> float:
    """The single rounding function used for every stored/displayed score."""
    return float(Decimal(repr(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class RawMatch:
    word_start: int  # word indices in the submission, end exclusive
    word_end: int
    start: int  # char offsets in the submission clean text
    end: int
    source_key: str
    source_start: int  # char offsets in the source text
    source_end: int
    match_type: str  # exact | near | paraphrase | crosslang
    group: str  # see citations.GROUPS
    score: float  # 1.0 for exact/near, cosine for paraphrase

    @property
    def words(self) -> int:
        return self.word_end - self.word_start


@dataclass(frozen=True)
class Filters:
    exclude_quotes: bool = False
    exclude_bibliography: bool = False
    min_words: int = 0
    exclude_sources: frozenset[str] = frozenset()

    def keeps(self, m: RawMatch) -> bool:
        if self.exclude_quotes and m.group in QUOTED_GROUPS:
            return False
        if self.exclude_bibliography and m.group == "bibliography":
            return False
        if m.words < self.min_words:
            return False
        return m.source_key not in self.exclude_sources


@dataclass(frozen=True)
class SourceScore:
    source_key: str
    words: int
    percent: float


@dataclass(frozen=True)
class AssignedRun:
    """A contiguous run of submission words given to one raw match."""

    word_start: int
    word_end: int
    match_index: int  # index into the raw match list passed to score()


@dataclass
class Score:
    percent: float
    matched_words: int
    total_words: int
    sources: list[SourceScore] = field(default_factory=list)
    runs: list[AssignedRun] = field(default_factory=list)


def score(matches: list[RawMatch], total_words: int, filters: Filters | None = None) -> Score:
    filters = filters or Filters()
    kept = [(i, m) for i, m in enumerate(matches) if filters.keeps(m)]

    totals: dict[str, int] = {}
    for _, m in kept:
        totals[m.source_key] = totals.get(m.source_key, 0) + m.words

    owner: list[tuple[int, int, str, int] | None] = [None] * total_words
    for i, m in kept:
        key = (PRIORITY.get(m.match_type, 9), -totals[m.source_key], m.source_key, i)
        for w in range(max(m.word_start, 0), min(m.word_end, total_words)):
            cur = owner[w]
            if cur is None or key < cur:
                owner[w] = key

    per_source: dict[str, int] = {}
    runs: list[AssignedRun] = []
    matched = 0
    w = 0
    while w < total_words:
        cur = owner[w]
        if cur is None:
            w += 1
            continue
        start = w
        while w < total_words and owner[w] == cur:
            w += 1
        runs.append(AssignedRun(start, w, cur[3]))
        per_source[cur[2]] = per_source.get(cur[2], 0) + (w - start)
        matched += w - start

    def pct(n: int) -> float:
        return round2(100.0 * n / total_words) if total_words else 0.0

    sources = sorted(
        (SourceScore(k, n, pct(n)) for k, n in per_source.items()), key=lambda s: (-s.words, s.source_key)
    )
    return Score(pct(matched), matched, total_words, sources, runs)
