"""Shared read models used by the API and the PDF report, so both always show the
same numbers."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models import DocumentText, SimilarityMatchRow, Submission
from api.schemas import AIOut, AISegmentOut, SimilarityOut, SimilarityRunOut, SimilaritySourceOut
from engine.ai import segments_to_chars
from engine.similarity.merge import Filters, RawMatch, score
from engine.similarity.tokens import tokenize

SOURCE_TYPES = ("web", "corpus", "submission")  # Internet, Publications, Submitted works


def _source_title(row: SimilarityMatchRow) -> str:
    if row.source_type == "submission":
        return re.sub(
            r"^Submitted to .+ on (\d{4}-\d{2}-\d{2})$",
            rf"Submitted to {get_settings().app_name} on \1",
            row.source_title,
        )
    return row.source_title


def default_filters() -> Filters:
    s = get_settings()
    return Filters(s.default_exclude_quotes, s.default_exclude_bibliography, s.default_min_words)


def similarity_view(db: Session, sub: Submission, filters: Filters | None = None) -> SimilarityOut:
    filters = filters or default_filters()
    doc = db.get(DocumentText, sub.id)
    assert doc is not None and sub.word_count is not None
    rows = db.scalars(
        select(SimilarityMatchRow)
        .where(SimilarityMatchRow.submission_id == sub.id)
        .order_by(SimilarityMatchRow.word_start, SimilarityMatchRow.word_end, SimilarityMatchRow.source_key,
                  SimilarityMatchRow.match_type)
    ).all()
    raw = [
        RawMatch(r.word_start, r.word_end, r.start, r.end, r.source_key, r.source_start, r.source_end,
                 r.match_type, r.match_group, r.score)
        for r in rows
    ]
    result = score(raw, sub.word_count, filters)
    tokens = tokenize(doc.clean_text)
    meta = {r.source_key: r for r in rows}
    groups: dict[str, int] = {}
    runs: list[SimilarityRunOut] = []
    for run in result.runs:
        row = rows[run.match_index]
        n = run.word_end - run.word_start
        groups[row.match_group] = groups.get(row.match_group, 0) + n
        runs.append(
            SimilarityRunOut(
                start=tokens[run.word_start].start, end=tokens[run.word_end - 1].end, words=n,
                source_key=row.source_key, match_type=row.match_type, group=row.match_group,
                score=row.score, source_excerpt=row.source_excerpt,
            )
        )
    by_type: dict[str, float] = {}
    for t in SOURCE_TYPES:
        subset = [m for m, r in zip(raw, rows, strict=True) if r.source_type == t]
        by_type[t] = score(subset, sub.word_count, filters).percent if subset else 0.0
    web = (sub.settings or {}).get("_web_search") or {}
    web_state = web.get("web_search", "off")
    web_message = {
        "unavailable": ("Internet search was not available during this check (search engines refused or rate-limited "
                        "our requests), so web pages were NOT searched and the similarity score may be too low. "
                        "Please check this document again later."),
        "partial": ("Internet search was only partly available during this check (many searches were refused), "
                    "so some web sources may be missing and the similarity score may be too low."),
    }.get(web_state, "")
    return SimilarityOut(
        web_search=web_state,
        web_search_message=web_message,
        percent=result.percent,
        matched_words=result.matched_words,
        total_words=result.total_words,
        sources=[
            SimilaritySourceOut(source_key=s.source_key, type=meta[s.source_key].source_type,
                                title=_source_title(meta[s.source_key]), url=meta[s.source_key].source_url,
                                words=s.words, percent=s.percent)
            for s in result.sources
        ],
        runs=runs,
        groups=groups,
        by_type=by_type,
        exclude_bibliography=filters.exclude_bibliography,
        exclude_quotes=filters.exclude_quotes,
        min_words=filters.min_words,
    )


def ai_view(db: Session, sub: Submission) -> AIOut:
    data = sub.ai_result or {"available": False, "message": "AI-writing detection was not run for this check."}
    segments: list[AISegmentOut] = []
    if data.get("segments"):
        doc = db.get(DocumentText, sub.id)
        assert doc is not None
        segments = [
            AISegmentOut(start=s["start"], end=s["end"], word_start=s["word_start"], word_end=s["word_end"],
                         level=s["level"], score=s["score"])
            for s in segments_to_chars(doc.clean_text, data["segments"])
        ]
    return AIOut(
        available=bool(data.get("available")), percent=data.get("percent"),
        qualifying_words=int(data.get("qualifying_words") or 0), ai_words=int(data.get("ai_words") or 0),
        model=str(data.get("model") or ""), message=str(data.get("message") or ""), segments=segments,
    )
