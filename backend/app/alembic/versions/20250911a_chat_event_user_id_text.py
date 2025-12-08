"""fix: chat_event.user_id -> TEXT to accept int/uuid/email"""

# revision identifiers, used by Alembic.
revision = "20250911a_chat_event_user_id_text"
down_revision = "20250910b_chat_rollups"   # ← your current head
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql

def upgrade() -> None:
    # If it was UUID earlier (as your error suggests), cast safely to text
    op.alter_column(
        "chat_event",
        "user_id",
        type_=sa.Text(),
        existing_type=psql.UUID(as_uuid=True),
        postgresql_using="user_id::text",
        existing_nullable=True,
    )

def downgrade() -> None:
    # WARNING: will fail if any non-uuid values are present in user_id
    op.alter_column(
        "chat_event",
        "user_id",
        type_=psql.UUID(as_uuid=True),
        existing_type=sa.Text(),
        postgresql_using="user_id::uuid",
        existing_nullable=True,
    )
