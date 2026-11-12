"""Phase 6F-C3 stream retry idempotency.

Revision ID: 20261113_phase6fc3
Revises: 20261112_phase6fc2
"""

import sqlalchemy as sa
from alembic import op

revision = "20261113_phase6fc3"
down_revision = "20261112_phase6fc2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "answerevidenceaudit",
        sa.Column("client_request_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "answerevidenceaudit",
        sa.Column("answer_confidence", sa.Float(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_answer_audit_stream_request",
        "answerevidenceaudit",
        ["user_id", "workspace_id", "client_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_answer_audit_stream_request",
        "answerevidenceaudit",
        type_="unique",
    )
    op.drop_column("answerevidenceaudit", "answer_confidence")
    op.drop_column("answerevidenceaudit", "client_request_id")
