from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers
revision = "e653098e6dde"
down_revision = '61b4c88e8820'
branch_labels = None
depends_on = None

def upgrade() -> None:
    conn = op.get_bind()
    # Mark all existing users as verified by setting email_verified_at
    conn.execute(
        sa.text("UPDATE \"user\" SET email_verified_at = NOW() WHERE email_verified_at IS NULL")
    )

def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE \"user\" SET email_verified_at = NULL")
    )
