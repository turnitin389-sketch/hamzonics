"""Source index interface + an in-memory implementation (tests, small local runs).
The PostgreSQL/pgvector implementation lives in worker/sql_index.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Protocol

import numpy as np

from engine.similarity.fingerprint import Fingerprint, fingerprints
from engine.similarity.sentences import split_sentences
from engine.similarity.tokens import Token, tokenize

MIN_SENTENCE_WORDS = 6


@dataclass
class SourceDoc:
    key: str
    type: str  # submission | corpus | web
    title: str
    text: str
    url: str | None = None
    owner: str | None = None  # user id for repository submissions
    text_sha256: str | None = None

    @cached_property
    def tokens(self) -> list[Token]:
        return tokenize(self.text)


@dataclass(frozen=True)
class SentenceHit:
    source_key: str
    start: int
    end: int
    cosine: float


class SourceIndex(Protocol):
    def candidate_sources(self, hashes: list[int], exclude: set[str], limit: int) -> list[str]: ...
    def get_source(self, key: str) -> SourceDoc: ...
    def nearest_sentences(
        self, vectors: np.ndarray, k: int, min_cos: float, exclude: set[str]
    ) -> list[list[SentenceHit]]: ...


class Encoder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray: ...


@dataclass
class IndexEntry:
    """Everything stored for one source document."""

    fingerprints: list[Fingerprint]
    sentence_spans: list[tuple[int, int]]
    vectors: np.ndarray | None  # (n_sentences, dim) float32, L2-normalised


def build_entry(text: str, encoder: Encoder | None) -> IndexEntry:
    tokens = tokenize(text)
    spans = [
        (s, e)
        for s, e in split_sentences(text)
        if sum(1 for t in tokens if t.start >= s and t.end <= e) >= MIN_SENTENCE_WORDS
    ]
    vectors = encoder.encode([text[s:e] for s, e in spans]) if encoder is not None and spans else None
    return IndexEntry(fingerprints(tokens), spans, vectors)


@dataclass
class MemoryIndex:
    docs: dict[str, SourceDoc] = field(default_factory=dict)
    postings: dict[int, set[str]] = field(default_factory=dict)
    sent_keys: list[tuple[str, int, int]] = field(default_factory=list)
    sent_vecs: list[np.ndarray] = field(default_factory=list)

    def add(self, doc: SourceDoc, entry: IndexEntry) -> None:
        self.docs[doc.key] = doc
        for fp in entry.fingerprints:
            self.postings.setdefault(fp.hash, set()).add(doc.key)
        if entry.vectors is not None:
            for (s, e), v in zip(entry.sentence_spans, entry.vectors, strict=True):
                self.sent_keys.append((doc.key, s, e))
                self.sent_vecs.append(v)

    def candidate_sources(self, hashes: list[int], exclude: set[str], limit: int) -> list[str]:
        counts: dict[str, int] = {}
        for h in set(hashes):
            for key in self.postings.get(h, ()):
                if key not in exclude:
                    counts[key] = counts.get(key, 0) + 1
        return [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]

    def get_source(self, key: str) -> SourceDoc:
        return self.docs[key]

    def nearest_sentences(
        self, vectors: np.ndarray, k: int, min_cos: float, exclude: set[str]
    ) -> list[list[SentenceHit]]:
        if not self.sent_vecs or len(vectors) == 0:
            return [[] for _ in range(len(vectors))]
        matrix = np.vstack(self.sent_vecs)
        sims = vectors @ matrix.T
        out: list[list[SentenceHit]] = []
        for row in sims:
            hits = [
                SentenceHit(self.sent_keys[j][0], self.sent_keys[j][1], self.sent_keys[j][2], float(row[j]))
                for j in np.nonzero(row >= min_cos)[0]
                if self.sent_keys[j][0] not in exclude
            ]
            hits.sort(key=lambda h: (-round(h.cosine, 6), h.source_key, h.start))
            out.append(hits[:k])
        return out
