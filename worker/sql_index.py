"""Source index backed by the database.

PostgreSQL: fingerprint lookup via the btree index on `hash`; nearest sentences via
pgvector cosine distance with the HNSW index. SQLite (local dev): same fingerprint
query, nearest sentences by brute force in numpy.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.models import FingerprintRow, SentenceEmbeddingRow, SourceRow, utcnow
from engine.extract.normalize import count_words
from engine.similarity.tokens import canonical_sha256 as text_sha256
from engine.similarity.index import IndexEntry, SentenceHit, SourceDoc

_CHUNK = 500  # SQLite allows at most 999 bound parameters


class SqlSourceIndex:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.pg = db.get_bind().dialect.name == "postgresql"
        self._docs: dict[str, SourceDoc] = {}
        self._matrix: tuple[np.ndarray, list[tuple[str, int, int]]] | None = None

    # ------------------------------------------------------------ lookups

    def candidate_sources(self, hashes: list[int], exclude: set[str], limit: int) -> list[str]:
        counts: dict[str, int] = {}
        unique = sorted(set(hashes))
        for i in range(0, len(unique), _CHUNK):
            rows = self.db.execute(
                select(FingerprintRow.source_id, FingerprintRow.hash)
                .where(FingerprintRow.hash.in_(unique[i : i + _CHUNK]))
                .distinct()
            ).all()
            for source_id, _ in rows:
                if source_id not in exclude:
                    counts[source_id] = counts.get(source_id, 0) + 1
        return [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]

    def get_source(self, key: str) -> SourceDoc:
        doc = self._docs.get(key)
        if doc is None:
            row = self.db.get(SourceRow, key)
            if row is None:
                raise KeyError(key)
            doc = SourceDoc(row.id, row.type, row.title, row.text, row.url, None, row.text_sha256)
            self._docs[key] = doc
        return doc

    def nearest_sentences(
        self, vectors: np.ndarray, k: int, min_cos: float, exclude: set[str]
    ) -> list[list[SentenceHit]]:
        if len(vectors) == 0:
            return []
        return self._nearest_pg(vectors, k, min_cos, exclude) if self.pg else self._nearest_np(vectors, k, min_cos, exclude)

    def _nearest_pg(self, vectors: np.ndarray, k: int, min_cos: float, exclude: set[str]) -> list[list[SentenceHit]]:
        out: list[list[SentenceHit]] = []
        for v in vectors:
            # Excluded sources are filtered INSIDE the query: when a text has many identical
            # copies (e.g. earlier uploads of it), the nearest rows would otherwise all be those
            # copies and the real source behind them would never be reached.
            rows = self.db.execute(nearest_query(v, k + 10, exclude)).all()
            hits = [
                SentenceHit(sid, s, e, float(1 - dd)) for sid, s, e, dd in rows if sid not in exclude and 1 - dd >= min_cos
            ]
            hits.sort(key=lambda h: (-round(h.cosine, 6), h.source_key, h.start))
            out.append(hits[:k])
        return out

    def _nearest_np(self, vectors: np.ndarray, k: int, min_cos: float, exclude: set[str]) -> list[list[SentenceHit]]:
        if self._matrix is None:
            rows = self.db.execute(
                select(
                    SentenceEmbeddingRow.source_id,
                    SentenceEmbeddingRow.char_start,
                    SentenceEmbeddingRow.char_end,
                    SentenceEmbeddingRow.embedding,
                ).order_by(SentenceEmbeddingRow.id)
            ).all()
            if not rows:
                return [[] for _ in range(len(vectors))]
            self._matrix = (np.vstack([r[3] for r in rows]), [(r[0], r[1], r[2]) for r in rows])
        matrix, keys = self._matrix
        out: list[list[SentenceHit]] = []
        for row in vectors @ matrix.T:
            hits = [
                SentenceHit(keys[j][0], keys[j][1], keys[j][2], float(row[j]))
                for j in np.nonzero(row >= min_cos)[0]
                if keys[j][0] not in exclude
            ]
            hits.sort(key=lambda h: (-round(h.cosine, 6), h.source_key, h.start))
            out.append(hits[:k])
        return out


def nearest_query(vector: np.ndarray, limit: int, exclude: set[str] | None = None):  # type: ignore[no-untyped-def]
    """PostgreSQL: the `limit` stored sentences closest to `vector` (pgvector `<=>` = cosine
    distance, served by the HNSW index). The column uses our own TypeDecorator, which does
    not expose pgvector's comparator, so the operator is written out explicitly."""
    from pgvector.sqlalchemy import Vector
    from sqlalchemy import Float, literal

    from api.models import EMBEDDING_DIM

    query_vec = literal([float(x) for x in vector], type_=Vector(EMBEDDING_DIM))
    d = SentenceEmbeddingRow.embedding.op("<=>", return_type=Float)(query_vec)
    q = select(SentenceEmbeddingRow.source_id, SentenceEmbeddingRow.char_start, SentenceEmbeddingRow.char_end, d)
    if exclude:
        q = q.where(SentenceEmbeddingRow.source_id.not_in(sorted(exclude)))
    return q.order_by(d, SentenceEmbeddingRow.id).limit(limit)


# ---------------------------------------------------------------- writing


def store_entry(db: Session, source: SourceRow, entry: IndexEntry) -> None:
    """(Re)write the fingerprints and sentence embeddings of one source."""
    db.execute(delete(FingerprintRow).where(FingerprintRow.source_id == source.id))
    db.execute(delete(SentenceEmbeddingRow).where(SentenceEmbeddingRow.source_id == source.id))
    db.add_all(
        FingerprintRow(source_id=source.id, hash=fp.hash, char_start=fp.char_start, char_end=fp.char_end)
        for fp in entry.fingerprints
    )
    if entry.vectors is not None:
        db.add_all(
            SentenceEmbeddingRow(source_id=source.id, char_start=s, char_end=e, embedding=v)
            for (s, e), v in zip(entry.sentence_spans, entry.vectors, strict=True)
        )


def upsert_source(
    db: Session,
    *,
    type: str,
    title: str,
    text: str,
    url: str | None = None,
    corpus: str | None = None,
    submission_id: str | None = None,
) -> tuple[SourceRow, bool]:
    """Find the source by submission id or (type, url); create or refresh it.
    Returns (row, changed) where changed means the text must be (re)indexed."""
    row = None
    if submission_id is not None:
        row = db.scalar(select(SourceRow).where(SourceRow.submission_id == submission_id))
    elif url is not None:
        row = db.scalar(select(SourceRow).where(SourceRow.type == type, SourceRow.url == url))
    digest = text_sha256(text)
    if row is None:
        row = SourceRow(type=type, corpus=corpus, url=url, title=title[:500], text=text, text_sha256=digest,
                        word_count=count_words(text), submission_id=submission_id)
        db.add(row)
        db.flush()
        return row, True
    row.cached_at = utcnow()
    if row.text_sha256 == digest:
        return row, False
    row.title, row.text, row.text_sha256, row.word_count = title[:500], text, digest, count_words(text)
    return row, True
