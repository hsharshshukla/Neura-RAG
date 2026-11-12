"""Phase 6F-C2 multi-turn answer evidence audit.

Revision ID: 20261112_phase6fc2
Revises: 20261109_phase6fb
"""

import sqlalchemy as sa
from alembic import op

revision = "20261112_phase6fc2"
down_revision = "20261109_phase6fb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "answerevidenceaudit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_message_id", sa.Integer(), nullable=False),
        sa.Column("assistant_message_id", sa.Integer(), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("standalone_query", sa.Text(), nullable=False),
        sa.Column("history_message_ids", sa.JSON(), nullable=False),
        sa.Column("tkp_correlation_id", sa.String(length=36), nullable=True),
        sa.Column("tkp_request", sa.JSON(), nullable=False),
        sa.Column("evidence_lineage", sa.JSON(), nullable=False),
        sa.Column("backend_status", sa.JSON(), nullable=False),
        sa.Column("citation_map", sa.JSON(), nullable=False),
        sa.Column("answer_model", sa.String(length=128), nullable=False),
        sa.Column("prompt_policy_version", sa.String(length=64), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("insufficient_evidence", sa.Boolean(), nullable=False),
        sa.Column("insufficient_reason", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chatsession.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_message_id"], ["chatmessage.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["chatmessage.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_message_id"),
        sa.UniqueConstraint("assistant_message_id"),
    )
    op.create_index("ix_answerevidenceaudit_session_id", "answerevidenceaudit", ["session_id"])
    op.create_index("ix_answerevidenceaudit_user_id", "answerevidenceaudit", ["user_id"])
    op.create_index("ix_answerevidenceaudit_workspace_id", "answerevidenceaudit", ["workspace_id"])
    op.create_index(
        "ix_answerevidenceaudit_tkp_correlation_id",
        "answerevidenceaudit",
        ["tkp_correlation_id"],
    )
    op.create_index("ix_answerevidenceaudit_created_at", "answerevidenceaudit", ["created_at"])
    op.execute(
        """
        CREATE FUNCTION reject_answerevidenceaudit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'answer evidence audits are append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_answerevidenceaudit_append_only
        BEFORE UPDATE OR DELETE ON answerevidenceaudit
        FOR EACH ROW EXECUTE FUNCTION reject_answerevidenceaudit_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_answerevidenceaudit_append_only ON answerevidenceaudit")
    op.execute("DROP FUNCTION IF EXISTS reject_answerevidenceaudit_mutation()")
    op.drop_index("ix_answerevidenceaudit_created_at", table_name="answerevidenceaudit")
    op.drop_index("ix_answerevidenceaudit_tkp_correlation_id", table_name="answerevidenceaudit")
    op.drop_index("ix_answerevidenceaudit_workspace_id", table_name="answerevidenceaudit")
    op.drop_index("ix_answerevidenceaudit_user_id", table_name="answerevidenceaudit")
    op.drop_index("ix_answerevidenceaudit_session_id", table_name="answerevidenceaudit")
    op.drop_table("answerevidenceaudit")
