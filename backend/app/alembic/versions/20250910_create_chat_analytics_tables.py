"""create chat analytics tables

Revision ID: 20250910_create_chat_analytics
Revises: 4e3c6d558c6f
Create Date: 2025-09-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# --- Alembic identifiers ---
revision = "20250910_create_chat_analytics"
down_revision = "4e3c6d558c6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Raw append-only event table
    op.create_table(
        "chat_event",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),

        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),  # free | mini+ | pro
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),

        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_index", sa.Integer(), nullable=False),

        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("response_code", sa.Integer(), server_default="200", nullable=False),

        sa.Column("in_cost", sa.Numeric(10, 6), server_default="0", nullable=False),
        sa.Column("out_cost", sa.Numeric(10, 6), server_default="0", nullable=False),
        sa.Column("total_cost", sa.Numeric(10, 6), server_default="0", nullable=False),

        sa.Column("retrieved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("retrieval_latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rag_k", sa.Integer(), nullable=True),
        sa.Column("rag_hit", sa.Boolean(), nullable=True),
        sa.Column("rag_hit_confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("rag_source_kinds", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("rag_doc_ids_hash", postgresql.ARRAY(sa.Text()), nullable=True),

        sa.Column("refused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("policy_trigger", sa.Text(), nullable=True),

        sa.Column("thumb", sa.SmallInteger(), nullable=True),  # -1,0,+1
        sa.Column("csat", sa.SmallInteger(), nullable=True),   # 1..5
        sa.Column("feedback_comment", sa.Text(), nullable=True),

        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=True),

        sa.Column("error_kind", sa.Text(), nullable=True),
        sa.Column("stack_key", sa.Text(), nullable=True),
    )
    op.create_index("ix_chat_event_ts", "chat_event", ["ts"])
    op.create_index("ix_chat_event_user_ts", "chat_event", ["user_id", "ts"])
    op.create_index("ix_chat_event_session_ts", "chat_event", ["chat_session_id", "ts"])
    op.create_index("ix_chat_event_model", "chat_event", ["model"])
    op.create_index("ix_chat_event_retrieved", "chat_event", ["retrieved"])
    op.create_index("ix_chat_event_response_code", "chat_event", ["response_code"])

    # 2) Session-level metrics
    op.create_table(
        "chat_session_metrics",
        sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("messages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_cost", sa.Numeric(10, 6), server_default="0", nullable=False),
        sa.Column("latency_p50_ms", sa.Integer(), nullable=True),
        sa.Column("latency_p90_ms", sa.Integer(), nullable=True),
        sa.Column("rag_hit_rate", sa.Numeric(5, 2), nullable=True),    # 0..1
        sa.Column("thumbs_up_rate", sa.Numeric(5, 2), nullable=True),  # 0..1
        sa.Column("csat_avg", sa.Numeric(5, 2), nullable=True),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index(
        "ix_chat_session_metrics_user_started",
        "chat_session_metrics",
        ["user_id", "started_at"],
    )

    # 3) Daily aggregates
    op.create_table(
        "chat_agg_day",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("plan", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),

        sa.Column("messages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sessions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_cost", sa.Numeric(12, 6), server_default="0", nullable=False),

        sa.Column("latency_p50_ms", sa.Integer(), nullable=True),
        sa.Column("latency_p90_ms", sa.Integer(), nullable=True),
        sa.Column("rag_hit_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("thumbs_up_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("csat_avg", sa.Numeric(5, 2), nullable=True),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
    )
    # Composite PK (nullable dims are allowed in PK here—intentional for “global” rows with NULLs)
    op.create_primary_key(
        "pk_chat_agg_day_composite",
        "chat_agg_day",
        ["day", "user_id", "model", "plan"],
    )
    op.create_index("ix_chat_agg_day_day", "chat_agg_day", ["day"])


def downgrade() -> None:
    op.drop_index("ix_chat_agg_day_day", table_name="chat_agg_day")
    op.drop_constraint("pk_chat_agg_day_composite", "chat_agg_day", type_="primary")
    op.drop_table("chat_agg_day")

    op.drop_index("ix_chat_session_metrics_user_started", table_name="chat_session_metrics")
    op.drop_table("chat_session_metrics")

    op.drop_index("ix_chat_event_response_code", table_name="chat_event")
    op.drop_index("ix_chat_event_retrieved", table_name="chat_event")
    op.drop_index("ix_chat_event_model", table_name="chat_event")
    op.drop_index("ix_chat_event_session_ts", table_name="chat_event")
    op.drop_index("ix_chat_event_user_ts", table_name="chat_event")
    op.drop_index("ix_chat_event_ts", table_name="chat_event")
    op.drop_table("chat_event")
