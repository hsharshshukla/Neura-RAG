# alembic/versions/20250830_add_cancel_schedule_fields.py
from alembic import op
import sqlalchemy as sa

# <= 32 chars or Postgres alembic_version will fail
revision = "20250830_cancel_flags"
down_revision = "20250827_billing_and_usage"
branch_labels = None
depends_on = None

def upgrade():
    # Add columns with a safe default for existing rows
    op.add_column(
        "user",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),  # Postgres boolean literal
        ),
    )
    op.add_column("user", sa.Column("scheduled_plan", sa.String(length=32), nullable=True))
    op.add_column("user", sa.Column("next_renewal_at", sa.DateTime(timezone=True), nullable=True))

    # Backfill in case any row landed NULL (paranoia)
    op.execute('UPDATE "user" SET cancel_at_period_end = FALSE WHERE cancel_at_period_end IS NULL')

    # Drop default so future inserts must set it intentionally
    op.alter_column(
        "user",
        "cancel_at_period_end",
        server_default=None,
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )

def downgrade():
    op.drop_column("user", "next_renewal_at")
    op.drop_column("user", "scheduled_plan")
    op.drop_column("user", "cancel_at_period_end")
