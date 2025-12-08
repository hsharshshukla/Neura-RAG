

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Keep these exactly as they already are in your file:
# revision = "20250911b_chat_event_add_session_id"
# down_revision = "20250911a_chat_event_user_id_text"
# branch_labels = None
# depends_on = None
# IDs
revision = "20250911b_chat_event_add_session_id"
down_revision = "20250911a_chat_event_user_id_text"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(col["name"] == column for col in insp.get_columns(table))

def _col_type(table: str, column: str) -> str | None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for col in insp.get_columns(table):
        if col["name"] == column:
            return str(col["type"]).lower()
    return None

def upgrade():
    # 1) Add column if missing
    if not _has_column("chat_event", "chat_session_id"):
        op.add_column(
            "chat_event",
            sa.Column("chat_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    else:
        # Optional: if it exists but is TEXT/VARCHAR, try to coerce to UUID
        ctype = _col_type("chat_event", "chat_session_id")
        if ctype and any(t in ctype for t in ("text", "character varying", "varchar")):
            # This will only work if all existing values are valid UUID strings or NULL
            op.execute(
                "ALTER TABLE chat_event "
                "ALTER COLUMN chat_session_id TYPE uuid "
                "USING NULLIF(chat_session_id,'')::uuid"
            )

    # 2) Helpful indexes (safe if repeated)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_event_chat_session_id "
        "ON chat_event (chat_session_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_event_ts ON chat_event (ts)")

def downgrade():
    # Drop index, then column (all IF EXISTS to be safe)
    op.execute("DROP INDEX IF EXISTS ix_chat_event_chat_session_id")
    # ts index may be shared; don’t drop unless you know you created it here.
    # op.execute('DROP INDEX IF EXISTS ix_chat_event_ts')
    op.execute("ALTER TABLE chat_event DROP COLUMN IF EXISTS chat_session_id")
