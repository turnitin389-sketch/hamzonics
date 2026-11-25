"""Frozen results: the same document always gets exactly the same result.

result_key = sha256(text_sha256 + check settings + ENGINE_VERSION)

The first computation for a key is stored unchanged; every later check with the same
key copies it (similarity scores, highlights, sources, excerpts AND the AI result).
Matches are stored by WORD index, and character offsets are recomputed for each new
upload, so a DOCX and the same text saved as PDF show identical highlights.

Two identical documents arriving together: one computes while the other waits on a
lock keyed by result_key (PostgreSQL advisory lock; an in-process lock for SQLite).
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models import FrozenResult, SimilarityMatchRow, SourceRow, Submission
from engine.similarity.tokens import tokenize
from engine.version import CODE_FINGERPRINT, ENGINE_VERSION

_local_locks: dict[str, threading.Lock] = {}
_local_guard = threading.Lock()


def compute_result_key(text_sha256: str, settings: dict[str, Any]) -> str:
    """Only the check settings count; internal bookkeeping keys start with "_"."""
    check_settings = {k: v for k, v in settings.items() if not k.startswith("_")}
    payload = json.dumps(check_settings, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{text_sha256}|{payload}|{ENGINE_VERSION}|{CODE_FINGERPRINT}".encode()).hexdigest()


@contextmanager
def result_lock(db: Session, result_key: str) -> Iterator[None]:
    """Only one worker computes a given result_key at a time."""
    if db.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(bytes.fromhex(result_key[:16]), "big", signed=True)
        conn = db.get_bind().connect()  # dedicated connection: the session commits in between
        try:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            conn.close()
        return
    with _local_guard:
        lock = _local_locks.setdefault(result_key, threading.Lock())
    with lock:
        yield


def load(db: Session, result_key: str) -> dict[str, Any] | None:
    row = db.scalar(select(FrozenResult).where(FrozenResult.result_key == result_key))
    return None if row is None else row.result


def snapshot(rows: list[SimilarityMatchRow], similarity_percent: float) -> dict[str, Any]:
    return {
        "similarity_percent": similarity_percent,
        "matches": [
            {
                "word_start": r.word_start, "word_end": r.word_end, "source_key": r.source_key,
                "source_start": r.source_start, "source_end": r.source_end, "match_type": r.match_type,
                "match_group": r.match_group, "score": r.score, "source_type": r.source_type,
                "source_title": r.source_title, "source_url": r.source_url, "source_excerpt": r.source_excerpt,
            }
            for r in sorted(rows, key=lambda r: (r.word_start, r.word_end, r.source_key, r.match_type))
        ],
    }


def store(db: Session, result_key: str, result: dict[str, Any]) -> dict[str, Any]:
    """Insert the frozen result; if another worker won the race, return theirs."""
    db.add(FrozenResult(result_key=result_key, engine_version=ENGINE_VERSION, result=result))
    try:
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        existing = load(db, result_key)
        assert existing is not None
        return existing


def apply(db: Session, sub: Submission, clean_text: str, result: dict[str, Any]) -> None:
    """Write the frozen matches for this submission (char offsets from ITS OWN text),
    replacing rows from an earlier interrupted run. Caller commits."""
    db.execute(delete(SimilarityMatchRow).where(SimilarityMatchRow.submission_id == sub.id))
    tokens = tokenize(clean_text)
    existing_sources = set(
        db.scalars(select(SourceRow.id).where(SourceRow.id.in_({m["source_key"] for m in result["matches"]}))).all()
    ) if result["matches"] else set()
    for m in result["matches"]:
        db.add(SimilarityMatchRow(
            submission_id=sub.id,
            source_id=m["source_key"] if m["source_key"] in existing_sources else None,
            source_key=m["source_key"], word_start=m["word_start"], word_end=m["word_end"],
            start=tokens[m["word_start"]].start, end=tokens[m["word_end"] - 1].end,
            source_start=m["source_start"], source_end=m["source_end"], match_type=m["match_type"],
            match_group=m["match_group"], score=m["score"], source_type=m["source_type"],
            source_title=m["source_title"], source_url=m["source_url"], source_excerpt=m["source_excerpt"],
        ))
    sub.similarity_percent = result["similarity_percent"]
    ai = result.get("ai")
    sub.ai_result = ai
    sub.ai_percent = ai.get("percent") if ai and ai.get("available") else None
