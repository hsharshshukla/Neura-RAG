"""add storage+vector+links

Revision ID: 172de1004b16
Revises: f4053c07231e
Create Date: 2025-08-18 15:32:27.735635

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
# add below: from alembic import op / import sqlalchemy as sa
try:
    from pgvector.sqlalchemy import Vector   # pip install pgvector
except Exception:
    Vector = None



# revision identifiers, used by Alembic.
revision = '172de1004b16'
down_revision = 'f4053c07231e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Extensions (safe if already present) ---
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm";')
    if Vector:
        op.execute('CREATE EXTENSION IF NOT EXISTS "vector";')

    # --- 1) upload_link (recommended) ---
    op.create_table(
        "upload_link",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.ForeignKeyConstraint(["upload_id"], ["upload.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_upload_link_user_email", "upload_link", ["user_email"])

    # --- 2) blob (ONLY if you truly need to store bytes in Postgres) ---
    op.create_table(
        "blob",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=True),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),  # BYTEA in Postgres
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.ForeignKeyConstraint(["upload_id"], ["upload.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_blob_user_email", "blob", ["user_email"])
    op.create_index("ix_blob_sha256", "blob", ["sha256"])

    # --- 3) embedding_index (pgvector) ---
    if Vector:
        op.create_table(
            "embedding_index",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("user_email", sa.String(), nullable=False),
            sa.Column("session_id", sa.String(), nullable=True),
            sa.Column("upload_id", sa.Integer(), nullable=True),
            sa.Column("chunk_id", sa.String(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding", Vector(dim=1536), nullable=False),  # adjust dim if needed
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("timezone('utc', now())"),
            ),
            sa.ForeignKeyConstraint(["upload_id"], ["upload.id"], ondelete="SET NULL"),
        )
        op.create_index(
            "ix_embedding_index_user_session",
            "embedding_index",
            ["user_email", "session_id"],
        )
        # ANN index for fast vector search (L2 distance; use vector_cosine_ops for cosine)
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_embedding_index_embedding "
            "ON embedding_index USING ivfflat (embedding vector_l2_ops) WITH (lists = 100);"
        )


def downgrade() -> None:
    # drop vector index & table if it was created
    if Vector:
        op.execute("DROP INDEX IF EXISTS idx_embedding_index_embedding;")
        op.drop_index("ix_embedding_index_user_session", table_name="embedding_index")
        op.drop_table("embedding_index")

    op.drop_index("ix_blob_sha256", table_name="blob")
    op.drop_index("ix_blob_user_email", table_name="blob")
    op.drop_table("blob")

    op.drop_index("ix_upload_link_user_email", table_name="upload_link")
    op.drop_table("upload_link")
