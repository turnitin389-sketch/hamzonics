"""SQLAlchemy ORM models. Public site: no users, clients or credits."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

JSONType = JSON().with_variant(JSONB(), "postgresql")
# Auto-increment ids: BIGINT on PostgreSQL, INTEGER (rowid) on SQLite.
BigId = BigInteger().with_variant(Integer(), "sqlite")
EMBEDDING_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2


class EmbeddingType(TypeDecorator):  # type: ignore[type-arg]
    """pgvector `vector(dim)` on PostgreSQL; raw float32 bytes elsewhere (local SQLite)."""

    impl = LargeBinary
    cache_ok = True

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        arr = np.asarray(value, dtype=np.float32)
        return arr if dialect.name == "postgresql" else arr.tobytes()

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if dialect.name == "postgresql":
            return np.asarray(value, dtype=np.float32)
        return np.frombuffer(value, dtype=np.float32)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Status:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Submission(Base):
    """One check. The site is public: there are no accounts. Whoever has the (random,
    unguessable) id can open the report; deleting needs the delete token that was
    returned once, when the check was created."""

    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    delete_token_hash: Mapped[str] = mapped_column(String(64))
    # SHA-256 of the uploader's IP address + server secret (rate limiting only; the IP itself is not stored).
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)

    status: Mapped[str] = mapped_column(String(16), default=Status.QUEUED, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    original_filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(8))  # pdf | docx | odt | rtf | txt
    file_size: Mapped[int] = mapped_column(BigInteger)
    file_path: Mapped[str] = mapped_column(String(512))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    engine_version: Mapped[str] = mapped_column(String(32))

    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    repository_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    similarity_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    # engine.ai.AIResult.to_json(): word-indexed AI segments, or why AI was not checked.
    ai_result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["DocumentText | None"] = relationship(
        back_populates="submission", cascade="all, delete-orphan", uselist=False
    )
    flags: Mapped[list["FlagRow"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="FlagRow.position"
    )


class DocumentText(Base):
    """Clean extracted text plus an offsets map (page -> char range in clean_text)."""

    __tablename__ = "documents_text"

    submission_id: Mapped[str] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True
    )
    clean_text: Mapped[str] = mapped_column(Text)
    offsets: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    submission: Mapped[Submission] = relationship(back_populates="document")


class FlagRow(Base):
    """One integrity flag type found in a submission (see engine/flags)."""

    __tablename__ = "flags"
    __table_args__ = (UniqueConstraint("submission_id", "type", name="uq_flag_submission_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer, default=0)  # display order
    count: Mapped[int] = mapped_column(Integer)
    locations: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)

    submission: Mapped[Submission] = relationship(back_populates="flags")


class ReportRow(Base):
    """A generated PDF report. Its SHA-256 lets anyone confirm a PDF is genuine."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), unique=True)
    pdf_path: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    pages: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceType:
    SUBMISSION = "submission"  # own repository (past submissions that opted in)
    CORPUS = "corpus"  # Wikipedia, arXiv ... loaded by scripts
    WEB = "web"  # pages found by web search, cached


class SourceRow(Base):
    """A document submissions are compared against."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(16), index=True)
    corpus: Mapped[str | None] = mapped_column(String(40), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64), index=True)
    word_count: Mapped[int] = mapped_column(Integer)
    # Repository copies keep this link while the check exists; it is set to NULL before an
    # old check is deleted (retention), so the repository keeps the text.
    submission_id: Mapped[str | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FingerprintRow(Base):
    __tablename__ = "fingerprints"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    hash: Mapped[int] = mapped_column(BigInteger, index=True)  # btree
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)


class SentenceEmbeddingRow(Base):
    __tablename__ = "sentence_embeddings"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(EmbeddingType(EMBEDDING_DIM))  # HNSW index on PostgreSQL


class SimilarityMatchRow(Base):
    """A raw similarity region (before word assignment). Scores and filters are
    recomputed from these rows, so changing a filter never needs a re-check.
    Source title/url/excerpt are copied so a later change to the source cannot
    change this report."""

    __tablename__ = "similarity_matches"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"), nullable=True)
    source_key: Mapped[str] = mapped_column(String(36))  # stable even if the source row is deleted
    word_start: Mapped[int] = mapped_column(Integer)
    word_end: Mapped[int] = mapped_column(Integer)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    source_start: Mapped[int] = mapped_column(Integer)
    source_end: Mapped[int] = mapped_column(Integer)
    match_type: Mapped[str] = mapped_column(String(12))  # exact | near | paraphrase | crosslang
    match_group: Mapped[str] = mapped_column(String(24))
    score: Mapped[float] = mapped_column(Float)
    source_type: Mapped[str] = mapped_column(String(16))
    source_title: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_excerpt: Mapped[str] = mapped_column(Text)


class ApiKey(Base):
    """A search API key added in the admin portal. Keys are used in `position` order; when
    one runs out of credits (or is rejected) it is marked exhausted and the next one is used.
    The key itself is stored encrypted with SECRET_KEY (api/secrets.py)."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(20), default="serper", index=True)
    label: Mapped[str] = mapped_column(String(100), default="")
    key_encrypted: Mapped[str] = mapped_column(Text)
    key_last4: Mapped[str] = mapped_column(String(4))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    exhausted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    searches_used: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchCache(Base):
    """Result URLs of one exact-phrase web search, kept SEARCH_CACHE_DAYS: the same phrase
    (e.g. the same copied paragraph in many students' work) never costs a credit twice."""

    __tablename__ = "search_cache"
    __table_args__ = (UniqueConstraint("provider", "query_hash", name="uq_search_cache_query"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(20))
    query_hash: Mapped[str] = mapped_column(String(64))
    urls: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class FrozenResult(Base):
    """The first result computed for a result_key, reused unchanged for every later check
    with the same key. Never updated."""

    __tablename__ = "frozen_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    result_key: Mapped[str] = mapped_column(String(64), unique=True)
    engine_version: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
