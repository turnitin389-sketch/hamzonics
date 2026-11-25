"""Run the full similarity check of one clean text against a source index."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from engine.similarity.align import align
from engine.similarity.citations import build_context, group_for
from engine.similarity.fingerprint import fingerprints
from engine.similarity.index import MIN_SENTENCE_WORDS, Encoder, SourceDoc, SourceIndex
from engine.similarity.merge import Filters, RawMatch, Score, score
from engine.similarity.semantic import DEFAULT_THRESHOLD
from engine.similarity.sentences import split_sentences
from engine.similarity.tokens import tokenize, word_index_at


@dataclass(frozen=True)
class SimilarityOptions:
    semantic_threshold: float = DEFAULT_THRESHOLD
    max_candidates: int = 50
    # Sentences already this much covered by exact/near matches skip the paraphrase search.
    paraphrase_skip_covered: float = 0.5
    neighbours: int = 3


@dataclass
class SimilarityResult:
    matches: list[RawMatch]
    sources: dict[str, SourceDoc]
    total_words: int
    score: Score
    sentences: list[tuple[int, int]] = field(default_factory=list)


def check_similarity(
    text: str,
    index: SourceIndex,
    encoder: Encoder | None = None,
    options: SimilarityOptions | None = None,
    exclude: set[str] | None = None,
) -> SimilarityResult:
    options = options or SimilarityOptions()
    exclude = exclude or set()
    tokens = tokenize(text)
    sentences = split_sentences(text)
    ctx = build_context(text, sentences)
    raw: list[RawMatch] = []
    sources: dict[str, SourceDoc] = {}
    covered = bytearray(len(tokens))

    # 1. Exact and near copies via fingerprints.
    hashes = [fp.hash for fp in fingerprints(tokens)]
    for key in index.candidate_sources(hashes, exclude, options.max_candidates):
        src = index.get_source(key)
        stoks = src.tokens
        for r in align(tokens, stoks):
            start, end = tokens[r.q_start].start, tokens[r.q_end - 1].end
            raw.append(
                RawMatch(r.q_start, r.q_end, start, end, key, stoks[r.s_start].start, stoks[r.s_end - 1].end,
                         r.kind, group_for(ctx, start, end), 1.0)
            )
            sources[key] = src
            for i in range(r.q_start, r.q_end):
                covered[i] = 1

    # 2. Paraphrase / cross-language via sentence embeddings.
    if encoder is not None:
        todo: list[tuple[int, int, int, int]] = []  # (char_start, char_end, word_start, word_end)
        for s, e in sentences:
            ws, we = word_index_at(tokens, s), word_index_at(tokens, e)
            n = we - ws
            if n >= MIN_SENTENCE_WORDS and sum(covered[ws:we]) < options.paraphrase_skip_covered * n:
                todo.append((s, e, ws, we))
        if todo:
            vectors = encoder.encode([text[s:e] for s, e, _, _ in todo])
            all_hits = index.nearest_sentences(vectors, options.neighbours, options.semantic_threshold, exclude)
            for (s, e, ws, we), hits in zip(todo, all_hits, strict=True):
                if not hits:
                    continue
                best = hits[0]
                src = sources.get(best.source_key) or index.get_source(best.source_key)
                sources[best.source_key] = src
                kind = "crosslang" if _script(text[s:e]) != _script(src.text[best.start : best.end]) else "paraphrase"
                cs, ce = tokens[ws].start, tokens[we - 1].end
                raw.append(
                    RawMatch(ws, we, cs, ce, best.source_key, best.start, best.end, kind,
                             group_for(ctx, cs, ce), round(best.cosine, 4))
                )

    raw.sort(key=lambda m: (m.word_start, m.word_end, m.source_key, m.match_type))
    return SimilarityResult(raw, sources, len(tokens), score(raw, len(tokens), Filters()), sentences)


def _script(text: str) -> str:
    counts: dict[str, int] = {}
    for ch in text:
        if ch.isalpha():
            name = unicodedata.name(ch, "")
            script = "ARABIC" if name.startswith("ARABIC") else name.split(" ", 1)[0]
            counts[script] = counts.get(script, 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0] if counts else ""
