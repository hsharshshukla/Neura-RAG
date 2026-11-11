"""Remove the superseded in-database blob/vector storage tables.

Revision ID: 67eec25b6a9f
Revises: 7f0f2a1f2b3c
Create Date: 2025-08-19 01:10:55.145858

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "67eec25b6a9f"
down_revision = "7f0f2a1f2b3c"
branch_labels = None
depends_on = None


class Vector1536(sa.types.UserDefinedType):
    """Compile the historical pgvector column without a Python pgvector dependency."""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        return "VECTOR(1536)"


def _database_has_vector_extension() -> bool:
    """Use durable database capability, not the migrator's installed packages."""
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return False
    return bool(
        connection.execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar_one()
    )


def upgrade() -> None:
    # DROP TABLE defaults to RESTRICT. If an unknown view, foreign key, or other
    # object depends on a legacy table, fail the migration transaction instead of
    # deleting that unrelated object through CASCADE.
    inspector = sa.inspect(op.get_bind())
    for table_name in ("embedding_index", "upload_link", "blob"):
        if inspector.has_table(table_name):
            op.drop_table(table_name)


def downgrade() -> None:
    if _database_has_vector_extension():
        op.create_table(
            "embedding_index",
            sa.Column("id", sa.VARCHAR(), nullable=False),
            sa.Column("user_email", sa.VARCHAR(), nullable=False),
            sa.Column("session_id", sa.VARCHAR(), nullable=True),
            sa.Column("upload_id", sa.INTEGER(), nullable=True),
            sa.Column("chunk_id", sa.VARCHAR(), nullable=True),
            sa.Column("content", sa.TEXT(), nullable=False),
            sa.Column("embedding", Vector1536(), nullable=False),
            sa.Column(
                "created_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("timezone('utc'::text, now())"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["upload_id"], ["upload.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_embedding_index_user_session",
            "embedding_index",
            ["user_email", "session_id"],
        )
        op.execute(
            "CREATE INDEX idx_embedding_index_embedding ON embedding_index "
            "USING ivfflat (embedding vector_l2_ops) WITH (lists = 100)"
        )

    op.create_table(
        "upload_link",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("upload_id", sa.INTEGER(), nullable=False),
        sa.Column("user_email", sa.VARCHAR(), nullable=False),
        sa.Column("url", sa.TEXT(), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used", sa.BOOLEAN(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("timezone('utc'::text, now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["upload_id"], ["upload.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_link_user_email", "upload_link", ["user_email"])
    op.create_table(
        "blob",
        sa.Column("id", sa.VARCHAR(), nullable=False),
        sa.Column("upload_id", sa.INTEGER(), nullable=True),
        sa.Column("user_email", sa.VARCHAR(), nullable=False),
        sa.Column("mime_type", sa.VARCHAR(), nullable=True),
        sa.Column("size_bytes", sa.INTEGER(), nullable=True),
        sa.Column("sha256", sa.VARCHAR(length=64), nullable=True),
        sa.Column("data", postgresql.BYTEA(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("timezone('utc'::text, now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["upload_id"], ["upload.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blob_user_email", "blob", ["user_email"])
    op.create_index("ix_blob_sha256", "blob", ["sha256"])
