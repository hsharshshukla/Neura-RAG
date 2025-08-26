"""backfill legacy users as verified

Revision ID: 9c2f7f3c5b1a
Revises: 61b4c88e8820
Create Date: 2025-08-26 10:30:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = "9c2f7f3c5b1a"
down_revision = "61b4c88e8820"
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    # Pick a cutoff at or just before you added verification (adjust if needed)
    cutoff = "2025-08-24T00:00:00Z"
    conn.execute(text("""
        UPDATE "user"
        SET email_verified_at = NOW()
        WHERE email_verified_at IS NULL
          AND created_at < :cutoff
    """), {"cutoff": cutoff})

def downgrade():
    conn = op.get_bind()
    cutoff = "2025-08-24T00:00:00Z"
    # Best‑effort rollback: only undo rows we set in upgrade (created before cutoff)
    conn.execute(text("""
        UPDATE "user"
        SET email_verified_at = NULL
        WHERE created_at < :cutoff
    """), {"cutoff": cutoff})
