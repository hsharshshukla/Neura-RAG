"""Merge heads after pro_trial/billing_event

Revision ID: 20250906c_merge_heads
Revises: 20250906_pro_trial_and_billing_event, 20250906b_safe_pro_trial_and_billing_event
Create Date: 2025-09-06 18:31:14.280859
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20250906c_merge_heads"
down_revision: Union[str, tuple[str, ...], None] = (
    "20250906_pro_trial_and_billing_event",
    "20250906b_safe_pro_trial_and_billing_event",
)
branch_labels = None
depends_on= None

def upgrade() -> None:
    # merge-only migration; nothing to do
    pass

def downgrade() -> None:
    # cannot automatically un-merge
    pass
