# backend/app/alembic/versions/7f0f2a1f2b3c_chatmessage_timestamp_to_timestamp.py
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "7f0f2a1f2b3c"
down_revision = "172de1004b16"  # <-- set to your current head
branch_labels = None
depends_on = None


def upgrade():
    # Convert INT epoch -> TIMESTAMP
    op.alter_column(
        "chatmessage",
        "timestamp",
        existing_type=sa.Integer(),
        type_=sa.TIMESTAMP(timezone=False),
        postgresql_using='to_timestamp("timestamp")',
        existing_nullable=False,
    )

    # Ensure DB-side default exists
    op.alter_column(
        "chatmessage",
        "timestamp",
        server_default=sa.text("now()"),
        existing_type=sa.TIMESTAMP(timezone=False),
        existing_nullable=False,
    )
    # Index already exists from initial schema; no change needed.


def downgrade():
    # Remove default
    op.alter_column(
        "chatmessage",
        "timestamp",
        server_default=None,
        existing_type=sa.TIMESTAMP(timezone=False),
        existing_nullable=False,
    )

    # Convert TIMESTAMP back -> INT epoch
    op.alter_column(
        "chatmessage",
        "timestamp",
        type_=sa.Integer(),
        existing_type=sa.TIMESTAMP(timezone=False),
        postgresql_using='extract(epoch from "timestamp")::int',
        existing_nullable=False,
    )
