"""pro trial fields + billing_event table (superseded by 20250906b_safe_pro_trial_and_billing_event)

Revision ID: 20250906_pro_trial_and_billing_event
Revises: 20250830_cancel_flags
Create Date: 2025-09-06 12:00:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20250906_pro_trial_and_billing_event"
down_revision: Union[str, None] = "20250830_cancel_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # This revision has been superseded by 20250906b_safe_pro_trial_and_billing_event (which `replaces` this one).
    # Keep as a no-op to avoid duplicate column/table errors when both branches are merged.
    pass

def downgrade() -> None:
    # No-op; actual objects are managed by the safe replacement revision.
    pass
