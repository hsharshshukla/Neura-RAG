"""Phase 6F-B workspace authorization and authentication integrity.

Revision ID: 20261109_phase6fb
Revises: 20250911b_chat_event_add_session_id
"""

import sqlalchemy as sa
from alembic import op

revision = "20261109_phase6fb"
down_revision = "20250911b_chat_event_add_session_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workspacemembership",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="reader", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),
    )
    op.create_index(
        "ix_workspacemembership_workspace_id",
        "workspacemembership",
        ["workspace_id"],
    )
    op.create_index("ix_workspacemembership_user_id", "workspacemembership", ["user_id"])

    op.add_column("chatsession", sa.Column("workspace_id", sa.String(length=36), nullable=True))
    op.create_index("ix_chatsession_user_id", "chatsession", ["user_id"])
    op.create_index("ix_chatsession_workspace_id", "chatsession", ["workspace_id"])
    op.create_foreign_key(
        "fk_chatsession_workspace",
        "chatsession",
        "workspace",
        ["workspace_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_index("ix_chatmessage_session_id", "chatmessage", ["session_id"])
    op.execute(
        "ALTER TABLE chatsession ADD CONSTRAINT fk_chatsession_user "
        'FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE NOT VALID'
    )
    op.execute(
        "ALTER TABLE chatmessage ADD CONSTRAINT fk_chatmessage_session "
        "FOREIGN KEY (session_id) REFERENCES chatsession(id) ON DELETE CASCADE NOT VALID"
    )
    op.execute(
        "ALTER TABLE chatmessage ADD CONSTRAINT fk_chatmessage_user "
        'FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE NOT VALID'
    )

    op.alter_column("user", "password", existing_type=sa.String(), nullable=True)
    op.add_column("user", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column("user", sa.Column("provider_id", sa.String(length=255), nullable=True))
    op.create_index("ix_user_provider", "user", ["provider"])
    op.create_index("ix_user_provider_id", "user", ["provider_id"])
    op.create_index(
        "uq_user_provider_identity",
        "user",
        ["provider", "provider_id"],
        unique=True,
        postgresql_where=sa.text("provider IS NOT NULL AND provider_id IS NOT NULL"),
    )

    # Older releases created these two tables at request/startup time. Adopt those
    # tables without failing an upgrade, then add the missing integrity constraints.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_verify_token (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_evt_user ON email_verify_token (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_evt_expires ON email_verify_token (expires_at)")
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_email_verify_token_user'
            ) THEN
                ALTER TABLE email_verify_token ADD CONSTRAINT fk_email_verify_token_user
                FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE NOT VALID;
            END IF;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_log (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            q TEXT NOT NULL,
            session_id TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_search_log_user_created ON search_log (user_id, created_at)"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_search_log_user'
            ) THEN
                ALTER TABLE search_log ADD CONSTRAINT fk_search_log_user
                FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE NOT VALID;
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.drop_index("ix_search_log_user_created", table_name="search_log")
    op.drop_table("search_log")
    op.drop_index("idx_evt_expires", table_name="email_verify_token")
    op.drop_index("idx_evt_user", table_name="email_verify_token")
    op.drop_table("email_verify_token")

    op.drop_index("uq_user_provider_identity", table_name="user")
    op.drop_index("ix_user_provider_id", table_name="user")
    op.drop_index("ix_user_provider", table_name="user")
    op.drop_column("user", "provider_id")
    op.drop_column("user", "provider")
    op.alter_column("user", "password", existing_type=sa.String(), nullable=False)

    op.execute("ALTER TABLE chatmessage DROP CONSTRAINT IF EXISTS fk_chatmessage_user")
    op.execute("ALTER TABLE chatmessage DROP CONSTRAINT IF EXISTS fk_chatmessage_session")
    op.execute("ALTER TABLE chatsession DROP CONSTRAINT IF EXISTS fk_chatsession_user")
    op.drop_index("ix_chatmessage_session_id", table_name="chatmessage")
    op.drop_constraint("fk_chatsession_workspace", "chatsession", type_="foreignkey")
    op.drop_index("ix_chatsession_workspace_id", table_name="chatsession")
    op.drop_index("ix_chatsession_user_id", table_name="chatsession")
    op.drop_column("chatsession", "workspace_id")

    op.drop_index("ix_workspacemembership_user_id", table_name="workspacemembership")
    op.drop_index("ix_workspacemembership_workspace_id", table_name="workspacemembership")
    op.drop_table("workspacemembership")
    op.drop_table("workspace")
