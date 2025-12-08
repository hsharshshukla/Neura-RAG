# app/analytics/schema.py
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql

metadata = sa.MetaData()

chat_event_table = sa.Table(
    "chat_event",
    metadata,

    # identity / timestamps
    sa.Column("event_id", psql.UUID(as_uuid=True), primary_key=True),
    sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("request_id", sa.Text, nullable=True),

    # actor / routing
    sa.Column("user_id", sa.Text, nullable=True),   # analytics uses TEXT (not FK int)
    sa.Column("plan", sa.Text, nullable=True),
    sa.Column("model", sa.Text, nullable=True),
    sa.Column("provider", sa.Text, nullable=True),

    # session / sequencing
    sa.Column("chat_session_id", psql.UUID(as_uuid=True), nullable=True),
    sa.Column("message_index", sa.Integer, nullable=True),

    # usage / perf
    sa.Column("input_tokens", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("output_tokens", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("latency_ms", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("response_code", sa.Integer, nullable=False, server_default=sa.text("200")),

    # retrieval metrics
    sa.Column("retrieved", sa.Boolean, nullable=False, server_default=sa.text("false")),
    sa.Column("retrieval_latency_ms", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("rag_k", sa.Integer, nullable=True),
    sa.Column("rag_hit", sa.Boolean, nullable=True),
    sa.Column("rag_hit_confidence", sa.Numeric, nullable=True),
    sa.Column("rag_source_kinds", psql.ARRAY(sa.Text), nullable=True),
    sa.Column("rag_doc_ids_hash", psql.ARRAY(sa.Text), nullable=True),

    # policy / quality
    sa.Column("refused", sa.Boolean, nullable=False, server_default=sa.text("false")),
    sa.Column("policy_trigger", sa.Text, nullable=True),
    sa.Column("thumb", sa.SmallInteger, nullable=True),
    sa.Column("csat", sa.SmallInteger, nullable=True),
    sa.Column("feedback_comment", sa.Text, nullable=True),

    # cost
    sa.Column("in_cost", sa.Numeric, nullable=True),
    sa.Column("out_cost", sa.Numeric, nullable=True),
    sa.Column("total_cost", sa.Numeric, nullable=True),

    # pipeline meta
    sa.Column("intent", sa.Text, nullable=True),
    sa.Column("topic", sa.Text, nullable=True),
    sa.Column("pipeline_version", sa.Text, nullable=True),

    # errors / grouping
    sa.Column("error_kind", sa.Text, nullable=True),
    sa.Column("stack_key", sa.Text, nullable=True),
)

__all__ = ["chat_event_table", "metadata"]
