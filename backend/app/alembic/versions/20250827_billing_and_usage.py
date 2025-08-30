"""add billing fields to user and LLMUsageEvent table

Revision ID: 20250827_billing_and_usage
Revises: 9c2f7f3c5b1a
Create Date: 2025-08-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250827_billing_and_usage"
down_revision = "9c2f7f3c5b1a"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c["name"] for c in insp.get_columns(table)]
        return column in cols
    except Exception:
        return False


def _has_index(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        idx = [ix["name"] for ix in insp.get_indexes(table)]
        return index_name in idx
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # --- user table: country, last_payment_at, last_payment_id ---
    if not _has_column("user", "country"):
        op.add_column("user", sa.Column("country", sa.Text(), nullable=True))
    if not _has_column("user", "last_payment_at"):
        op.add_column("user", sa.Column("last_payment_at", sa.TIMESTAMP(timezone=True), nullable=True))
    if not _has_column("user", "last_payment_id"):
        op.add_column("user", sa.Column("last_payment_id", sa.Text(), nullable=True))

    if not _has_index("user", "ix_user_country"):
        op.create_index("ix_user_country", "user", ["country"], unique=False)
    if not _has_index("user", "ix_user_last_payment_at"):
        op.create_index("ix_user_last_payment_at", "user", ["last_payment_at"], unique=False)

    # --- llmusageevent table ---
    if not insp.has_table("llmusageevent"):
        op.create_table(
            "llmusageevent",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("chat_session_id", sa.Integer(), nullable=True),
            sa.Column("tier", sa.Text(), nullable=False),
            sa.Column("model", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("request_tokens", sa.Integer(), nullable=False),
            sa.Column("response_tokens", sa.Integer(), nullable=False),
            sa.Column("total_tokens", sa.Integer(), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=False),
            sa.Column("cost_micro_usd", sa.Integer(), nullable=False),
            sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'USD'")),
            sa.Column("created_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.text("now()")),
            sa.Column("retrieved_chunks", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("retrieved_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("embeddings_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("http_status", sa.Integer(), nullable=False, server_default=sa.text("200")),
            sa.Column("error_code", sa.Text(), nullable=True),
            sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

    # Create indexes for llmusageevent if missing
    if insp.has_table("llmusageevent"):
        existing = {ix["name"] for ix in insp.get_indexes("llmusageevent")}
        if "ix_llmusageevent_created_at" not in existing:
            op.create_index("ix_llmusageevent_created_at", "llmusageevent", ["created_at"], unique=False)
        if "ix_llmusageevent_user" not in existing:
            op.create_index("ix_llmusageevent_user", "llmusageevent", ["user_id", "created_at"], unique=False)
        if "ix_llmusageevent_model" not in existing:
            op.create_index("ix_llmusageevent_model", "llmusageevent", ["model"], unique=False)
        if "ix_llmusageevent_tier" not in existing:
            op.create_index("ix_llmusageevent_tier", "llmusageevent", ["tier"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Drop llmusageevent indexes + table (safely)
    if insp.has_table("llmusageevent"):
        existing = {ix["name"] for ix in insp.get_indexes("llmusageevent")}
        if "ix_llmusageevent_tier" in existing:
            op.drop_index("ix_llmusageevent_tier", table_name="llmusageevent")
        if "ix_llmusageevent_model" in existing:
            op.drop_index("ix_llmusageevent_model", table_name="llmusageevent")
        if "ix_llmusageevent_user" in existing:
            op.drop_index("ix_llmusageevent_user", table_name="llmusageevent")
        if "ix_llmusageevent_created_at" in existing:
            op.drop_index("ix_llmusageevent_created_at", table_name="llmusageevent")
        op.drop_table("llmusageevent")

    # Drop user indexes if present
    if _has_index("user", "ix_user_last_payment_at"):
        op.drop_index("ix_user_last_payment_at", table_name="user")
    if _has_index("user", "ix_user_country"):
        op.drop_index("ix_user_country", table_name="user")

    # Drop user columns (safe)
    op.execute(sa.text('ALTER TABLE "user" DROP COLUMN IF EXISTS last_payment_id'))
    op.execute(sa.text('ALTER TABLE "user" DROP COLUMN IF EXISTS last_payment_at'))
    op.execute(sa.text('ALTER TABLE "user" DROP COLUMN IF EXISTS country'))
