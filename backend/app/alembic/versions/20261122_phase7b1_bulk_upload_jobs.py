"""Phase 7B-1 durable Neura bulk upload job ownership.

Revision ID: 20261122_phase7b1
Revises: 20261113_phase6fc3
"""

import sqlalchemy as sa
from alembic import op

revision = "20261122_phase7b1"
down_revision = "20261113_phase6fc3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tkpbulkuploadjob",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tkpbulkuploadjob_workspace_id",
        "tkpbulkuploadjob",
        ["workspace_id"],
    )
    op.create_index(
        "ix_tkpbulkuploadjob_owner_user_id",
        "tkpbulkuploadjob",
        ["owner_user_id"],
    )
    op.create_table(
        "tkpbulkuploaddocument",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("bulk_job_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("tkp_job_id", sa.String(length=200), nullable=True),
        sa.Column("processing_status", sa.String(length=32), server_default="QUEUED", nullable=False),
        sa.Column("index_status", sa.String(length=32), server_default="NOT_READY", nullable=False),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("source_version_id", sa.String(length=36), nullable=True),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bulk_job_id"], ["tkpbulkuploadjob.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tkpbulkuploaddocument_bulk_job_id",
        "tkpbulkuploaddocument",
        ["bulk_job_id"],
    )
    op.create_index(
        "ix_tkpbulkuploaddocument_workspace_id",
        "tkpbulkuploaddocument",
        ["workspace_id"],
    )
    op.create_index(
        "ix_tkpbulkuploaddocument_owner_user_id",
        "tkpbulkuploaddocument",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_tkpbulkuploaddocument_tkp_job_id",
        "tkpbulkuploaddocument",
        ["tkp_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tkpbulkuploaddocument_tkp_job_id",
        table_name="tkpbulkuploaddocument",
    )
    op.drop_index(
        "ix_tkpbulkuploaddocument_owner_user_id",
        table_name="tkpbulkuploaddocument",
    )
    op.drop_index(
        "ix_tkpbulkuploaddocument_workspace_id",
        table_name="tkpbulkuploaddocument",
    )
    op.drop_index(
        "ix_tkpbulkuploaddocument_bulk_job_id",
        table_name="tkpbulkuploaddocument",
    )
    op.drop_table("tkpbulkuploaddocument")
    op.drop_index(
        "ix_tkpbulkuploadjob_owner_user_id",
        table_name="tkpbulkuploadjob",
    )
    op.drop_index(
        "ix_tkpbulkuploadjob_workspace_id",
        table_name="tkpbulkuploadjob",
    )
    op.drop_table("tkpbulkuploadjob")
