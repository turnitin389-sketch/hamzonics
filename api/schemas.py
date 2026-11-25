"""Pydantic response schemas."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_validator


class MessageOut(BaseModel):
    message: str


class FlagSummary(BaseModel):
    type: str
    count: int


class FlagOut(FlagSummary):
    locations: list[dict]


class SubmissionOut(BaseModel):
    id: str
    status: str
    progress: int
    stage: str
    error: str | None
    queue_position: int | None
    original_filename: str
    file_type: str
    file_size: int
    word_count: int | None
    page_count: int | None
    ocr_pages: int | None
    repository_opt_in: bool
    engine_version: str
    flags: list[FlagSummary]
    similarity_percent: float | None
    ai_percent: float | None
    ai_available: bool | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # Returned ONCE, when the check is created: needed to delete it later.
    delete_token: str | None = None

    @field_validator("created_at", "started_at", "finished_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        # SQLite returns naive datetimes; they are stored as UTC. Without the
        # offset the browser would read them as local time.
        return v.replace(tzinfo=timezone.utc) if v is not None and v.tzinfo is None else v


class QueueOut(BaseModel):
    running: int
    queued: int
    max_concurrent: int


class SimilaritySourceOut(BaseModel):
    source_key: str
    type: str
    title: str
    url: str | None
    words: int
    percent: float


class SimilarityRunOut(BaseModel):
    """A highlighted span of the submission given to one source."""

    start: int
    end: int
    words: int
    source_key: str
    match_type: str
    group: str
    score: float
    source_excerpt: str


class SimilarityOut(BaseModel):
    percent: float
    matched_words: int
    total_words: int
    sources: list[SimilaritySourceOut]
    runs: list[SimilarityRunOut]
    groups: dict[str, int]
    # Similarity % per source database when it is matched on its own (overlaps counted in each).
    by_type: dict[str, float]
    exclude_bibliography: bool
    exclude_quotes: bool
    min_words: int
    # "off" (no web search configured) | "ok" | "partial" | "unavailable" (search engines blocked us)
    web_search: str = "off"
    web_search_message: str = ""


class AISegmentOut(BaseModel):
    start: int
    end: int
    word_start: int
    word_end: int
    level: str  # ai | possible
    score: float


class AIOut(BaseModel):
    available: bool
    percent: float | None
    qualifying_words: int
    ai_words: int
    model: str
    message: str
    segments: list[AISegmentOut]


class SubmissionTextOut(BaseModel):
    id: str
    word_count: int
    clean_text: str
    pages: list[dict]
