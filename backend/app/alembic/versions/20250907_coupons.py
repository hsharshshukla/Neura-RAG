"""add coupons tables

Revision ID: 20250907_add_coupons
Revises: 20250906c_merge_heads
Create Date: 2025-09-07 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20250907_add_coupons"
down_revision = "20250906c_merge_heads"
branch_labels = None
depends_on = None


def upgrade():
    # --- coupon ---
    op.create_table(
        "coupon",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("amount_type", sa.String(length=16), nullable=False),
        sa.Column("duration", sa.String(length=16), nullable=False),
        sa.Column("duration_in_months", sa.Integer(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("is_limited_redemptions", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("per_customer_limit", sa.Integer(), nullable=True),
        sa.Column("applies_to_variants", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
    )
    # NOTE: unique constraint on code already creates a unique index. No extra index needed.

    # --- coupon_redemption ---
    op.create_table(
        "coupon_redemption",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("coupon.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=True),
        sa.Column("amount_discounted", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("coupon_id", "user_id", "order_id", name="uq_coupon_user_order"),
    )

    # Idempotent secondary indexes (create only if missing)
    op.execute("CREATE INDEX IF NOT EXISTS ix_coupon_redemption_coupon_id ON coupon_redemption (coupon_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_coupon_redemption_user_id ON coupon_redemption (user_id)")


def downgrade():
    # Drop indexes if they exist, then tables
    op.execute("DROP INDEX IF EXISTS ix_coupon_redemption_user_id")
    op.execute("DROP INDEX IF EXISTS ix_coupon_redemption_coupon_id")
    op.drop_table("coupon_redemption")
    op.drop_table("coupon")
