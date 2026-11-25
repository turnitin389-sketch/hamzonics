"""Public checker schema: submissions, text, flags, sources/fingerprints/embeddings,
similarity matches, AI results, reports, frozen results. No accounts.

Revision ID: 0001_public
Revises:
Create Date: 2026-11-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_public"
down_revision = None
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
EMBEDDING_DIM = 384


def _big_id() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    pg = op.get_bind().dialect.name == "postgresql"
    if pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("delete_token_hash", sa.String(64), nullable=False),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(8), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=True),
        sa.Column("result_key", sa.String(64), nullable=True),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("ocr_pages", sa.Integer(), nullable=True),
        sa.Column("settings", JSONType, nullable=False),
        sa.Column("repository_opt_in", sa.Boolean(), nullable=False),
        sa.Column("similarity_percent", sa.Float(), nullable=True),
        sa.Column("ai_percent", sa.Float(), nullable=True),
        sa.Column("ai_result", JSONType, nullable=True),
        _ts("created_at"),
        _ts("started_at", True),
        _ts("finished_at", True),
    )
    for col in ("ip_hash", "status", "file_sha256", "text_sha256", "result_key", "created_at"):
        op.create_index(f"ix_submissions_{col}", "submissions", [col])

    op.create_table(
        "documents_text",
        sa.Column("submission_id", sa.String(36), sa.ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("clean_text", sa.Text(), nullable=False),
        sa.Column("offsets", JSONType, nullable=False),
        _ts("created_at"),
    )

    op.create_table(
        "flags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("submission_id", sa.String(36), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("locations", JSONType, nullable=False),
        sa.UniqueConstraint("submission_id", "type", name="uq_flag_submission_type"),
    )
    op.create_index("ix_flags_submission_id", "flags", ["submission_id"])

    op.create_table(
        "reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("submission_id", sa.String(36), sa.ForeignKey("submissions.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("pdf_path", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_reports_sha256", "reports", ["sha256"])

    op.create_table(
        "sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("corpus", sa.String(40), nullable=True),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.String(36), sa.ForeignKey("submissions.id", ondelete="CASCADE"),
                  nullable=True, unique=True),
        _ts("cached_at"),
        _ts("created_at"),
    )
    for col in ("type", "url", "text_sha256"):
        op.create_index(f"ix_sources_{col}", "sources", [col])

    op.create_table(
        "fingerprints",
        sa.Column("id", _big_id(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hash", sa.BigInteger(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
    )
    op.create_index("ix_fingerprints_hash", "fingerprints", ["hash"])
    op.create_index("ix_fingerprints_source_id", "fingerprints", ["source_id"])

    if pg:
        from pgvector.sqlalchemy import Vector

        emb_type: sa.types.TypeEngine = Vector(EMBEDDING_DIM)
    else:
        emb_type = sa.LargeBinary()
    op.create_table(
        "sentence_embeddings",
        sa.Column("id", _big_id(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("embedding", emb_type, nullable=False),
    )
    op.create_index("ix_sentence_embeddings_source_id", "sentence_embeddings", ["source_id"])
    if pg:
        op.execute(
            "CREATE INDEX ix_sentence_embeddings_hnsw ON sentence_embeddings "
            "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )

    op.create_table(
        "similarity_matches",
        sa.Column("id", _big_id(), primary_key=True, autoincrement=True),
        sa.Column("submission_id", sa.String(36), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_key", sa.String(36), nullable=False),
        sa.Column("word_start", sa.Integer(), nullable=False),
        sa.Column("word_end", sa.Integer(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("source_start", sa.Integer(), nullable=False),
        sa.Column("source_end", sa.Integer(), nullable=False),
        sa.Column("match_type", sa.String(12), nullable=False),
        sa.Column("match_group", sa.String(24), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_title", sa.String(500), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=False),
    )
    op.create_index("ix_similarity_matches_submission_id", "similarity_matches", ["submission_id"])

    op.create_table(
        "frozen_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("result_key", sa.String(64), nullable=False, unique=True),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("result", JSONType, nullable=False),
        _ts("created_at"),
    )


def downgrade() -> None:
    for table in ("frozen_results", "similarity_matches", "sentence_embeddings", "fingerprints", "sources",
                  "reports", "flags", "documents_text", "submissions"):
        op.drop_table(table)
