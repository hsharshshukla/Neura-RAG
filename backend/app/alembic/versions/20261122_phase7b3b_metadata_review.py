"""Persist the TKP source identifier needed for metadata review.

Revision ID: 20261122_phase7b3b
Revises: 20261122_phase7b1
"""

import sqlalchemy as sa
from alembic import op

revision = "20261122_phase7b3b"
down_revision = "20261122_phase7b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tkpbulkuploaddocument",
        sa.Column("source_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tkpbulkuploaddocument", "source_id")
