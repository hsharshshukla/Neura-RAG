"""pro trial fields + billing_event table (safe replacement)

Revision ID: 20250906b_safe_pro_trial_and_billing_event
Revises: 20250830_cancel_flags
Replaces: 20250906_pro_trial_and_billing_event
Create Date: 2025-09-06 12:34:56
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# --- Alembic IDs ---
revision = "20250906b_safe_pro_trial_and_billing_event"
down_revision = "20250830_cancel_flags"
replaces = ("20250906_pro_trial_and_billing_event",)

USER_TABLE = "user"
BILLING_EVENT_TABLE = "billing_event"


def _has_column(conn, table: str, col: str) -> bool:
    insp = Inspector.from_engine(conn)
    cols = [c["name"] for c in insp.get_columns(table)]
    return col in cols


def upgrade():
    conn = op.get_bind()

    # --- user table: add columns iff missing ---
    # These may already exist from 20250827_billing_and_usage / 20250830_cancel_flags
    add_cols = {
        "last_payment_at": sa.DateTime(timezone=False),
        "last_payment_id": sa.Text(),
        "next_renewal_at": sa.DateTime(timezone=False),
        "cancel_at_period_end": sa.Boolean(),
        "scheduled_plan": sa.Text(),
        "is_pro_paid_active": sa.Boolean(),
        "pro_trial_started_at": sa.DateTime(timezone=False),
        "pro_trial_cancelled": sa.Boolean(),
    }

    for col_name, col_type in add_cols.items():
        if not _has_column(conn, USER_TABLE, col_name):
            op.add_column(USER_TABLE, sa.Column(col_name, col_type, nullable=True))

    # Optional: lightweight indexes if not already present (safe CREATE IF NOT EXISTS via raw SQL)
    op.execute(
        f'CREATE INDEX IF NOT EXISTS ix_user_next_renewal_at ON "{USER_TABLE}" (next_renewal_at)'
    )
    op.execute(
        f'CREATE INDEX IF NOT EXISTS ix_user_last_payment_at ON "{USER_TABLE}" (last_payment_at)'
    )

    # --- billing_event: create table iff missing ---
    # Using idempotent CREATE so we don’t collide with prior manual/SQL deployments
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.billing_event (
            id BIGSERIAL PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT,
            provider TEXT,
            user_id INTEGER,
            payload JSONB,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_billing_event_user_id ON public.billing_event (user_id)'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_billing_event_created_at ON public.billing_event (created_at)'
    )


def downgrade():
    # Keep downgrade conservative: only drop objects if they exist.
    conn = op.get_bind()
    # billing_event
    op.execute('DROP TABLE IF EXISTS public.billing_event')

    # user columns (drop only if present)
    maybe_drop = [
        "pro_trial_cancelled",
        "pro_trial_started_at",
        "is_pro_paid_active",
        "scheduled_plan",
        "cancel_at_period_end",
        "next_renewal_at",
        "last_payment_id",
        "last_payment_at",
    ]
    for col in maybe_drop:
        if _has_column(conn, USER_TABLE, col):
            op.drop_column(USER_TABLE, col)

    # indexes will be dropped with table/columns or left harmlessly if already gone
