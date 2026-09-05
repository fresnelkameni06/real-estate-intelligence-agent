"""add pgvector-backed RAG document chunks

Revision ID: 0002_rag_embeddings
Revises: 0001_initial
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_rag_embeddings"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "real_estate"


def upgrade() -> None:
    # pgvector is installed once at PostgreSQL server level and enabled once per
    # database. IF NOT EXISTS keeps the migration idempotent when an administrator
    # has already enabled it, as recommended by the setup instructions.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "rag_document_chunks",
        sa.Column("chunk_id", sa.String(length=64), primary_key=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("chunking_version", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("source_page_url", sa.Text(), nullable=False),
        sa.Column("download_url", sa.Text(), nullable=False),
        sa.Column("document_format", sa.String(length=8), nullable=False),
        sa.Column(
            "heading_path",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("page_start", sa.Integer()),
        sa.Column("page_end", sa.Integer()),
        sa.Column(
            "topics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("jurisdiction", sa.String(length=32)),
        sa.Column("authority_level", sa.Text(), nullable=False),
        sa.Column("is_normative", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_until", sa.Date()),
        sa.Column(
            "quality_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding_dimensions", sa.SmallInteger(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("char_length(chunk_id) = 64", name="ck_rag_chunk_id_length"),
        sa.CheckConstraint(
            "char_length(content_sha256) = 64", name="ck_rag_content_sha_length"
        ),
        sa.CheckConstraint("char_length(raw_sha256) = 64", name="ck_rag_raw_sha_length"),
        sa.CheckConstraint("chunk_index >= 0", name="ck_rag_chunk_index_nonnegative"),
        sa.CheckConstraint("character_count > 0", name="ck_rag_character_count_positive"),
        sa.CheckConstraint("word_count > 0", name="ck_rag_word_count_positive"),
        sa.CheckConstraint(
            "document_format IN ('html', 'pdf')", name="ck_rag_document_format"
        ),
        sa.CheckConstraint(
            "embedding_dimensions = 1536", name="ck_rag_embedding_dimensions"
        ),
        sa.UniqueConstraint("source_id", "chunk_index", name="uq_rag_source_chunk_index"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_rag_source_id",
        "rag_document_chunks",
        ["source_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("idx_rag_source_id", table_name="rag_document_chunks", schema=SCHEMA)
    op.drop_table("rag_document_chunks", schema=SCHEMA)
    # The vector extension is shared database infrastructure. Do not remove it
    # during an application migration downgrade.
