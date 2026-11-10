"""pro trial fields + billing_event table (superseded by 20250906b_safe_pro_trial_and_billing_event)

Revision ID: 20250906_pro_trial_and_billing_event
Revises: 20250830_cancel_flags
Create Date: 2025-09-06 12:00:00
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20250906_pro_trial_and_billing_event"
down_revision: str | None = "20250830_cancel_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ensure_alembic_version_capacity() -> None:
    """Support databases stamped at 20250830 before its widening guard existed."""
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")


def upgrade() -> None:
    _ensure_alembic_version_capacity()
    # Superseded by 20250906b_safe_pro_trial_and_billing_event, which replaces it.
    # Keep as a no-op to avoid duplicate column/table errors when both branches are merged.
    pass


def downgrade() -> None:
    # No-op; actual objects are managed by the safe replacement revision.
    pass
