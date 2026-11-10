# alembic/versions/20250830_add_cancel_schedule_fields.py
import sqlalchemy as sa
from alembic import op

revision = "20250830_cancel_flags"
down_revision = "20250827_billing_and_usage"
branch_labels = None
depends_on = None


def _ensure_alembic_version_capacity() -> None:
    """Widen Alembic's revision column without changing existing values."""
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")


def upgrade() -> None:
    # Later legacy revision identifiers exceed Alembic's historical VARCHAR(32)
    # default. Expand the bookkeeping column before Alembic writes the next id.
    # Repeating this widening is safe; the immediate successor branches repeat it
    # for databases that were already stamped at this revision before this guard
    # was added.
    _ensure_alembic_version_capacity()
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


def downgrade() -> None:
    op.drop_column("user", "next_renewal_at")
    op.drop_column("user", "scheduled_plan")
    op.drop_column("user", "cancel_at_period_end")
    # Do not shrink alembic_version. Other installed branch revisions may be
    # longer than 32 characters, and narrowing would be lossy or fail outright.
