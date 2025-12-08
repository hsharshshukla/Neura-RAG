"""upload: align tables for upload.py/admin.py (no original filenames)

Revision ID: 4e3c6d558c6f
Revises: 1ed74d883919
Create Date: 2025-09-09 16:04:55.922299
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4e3c6d558c6f"
down_revision: Union[str, None] = "1ed74d883919"
branch_labels: Union[str, Sequence[str], None] = None
# Ensure earlier storage/vector work is present.
depends_on: Union[str, Sequence[str], None] = "172de1004b16"


def upgrade() -> None:
    # ---- BLOB (no original filenames) ----
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.blob (
            id BIGSERIAL PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            bytes BIGINT NOT NULL,
            ext TEXT,
            mime TEXT,
            storage_uri TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_blob_sha256 ON public.blob (sha256);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_blob_created_at ON public.blob (created_at);")

    # Ensure columns exist if an older variant of blob is present.
    op.execute("ALTER TABLE public.blob ADD COLUMN IF NOT EXISTS bytes BIGINT;")
    op.execute("ALTER TABLE public.blob ADD COLUMN IF NOT EXISTS ext TEXT;")
    op.execute("ALTER TABLE public.blob ADD COLUMN IF NOT EXISTS mime TEXT;")
    op.execute("ALTER TABLE public.blob ADD COLUMN IF NOT EXISTS storage_uri TEXT;")
    op.execute(
        "ALTER TABLE public.blob "
        "ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW();"
    )

    # ---- UPLOAD LINK (user_id + session_id + sha256 unique triple) ----
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.upload_link (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            session_id INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, session_id, sha256)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_upload_link_user ON public.upload_link (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_upload_link_session ON public.upload_link (session_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_upload_link_created_at ON public.upload_link (created_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_upload_link_sha256 ON public.upload_link (sha256);")

    # ---- EMBEDDING INDEX (lightweight registry; content lives in vector store) ----
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.embedding_index (
            id BIGSERIAL PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            store_key TEXT,
            chunks INTEGER,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_embedding_index_created_at ON public.embedding_index (created_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_embedding_index_sha256 ON public.embedding_index (sha256);")


def downgrade() -> None:
    # Drop only objects we created here.
    op.execute("DROP INDEX IF EXISTS ix_embedding_index_sha256;")
    op.execute("DROP INDEX IF EXISTS ix_embedding_index_created_at;")
    op.execute("DROP TABLE IF EXISTS public.embedding_index;")

    op.execute("DROP INDEX IF EXISTS ix_upload_link_sha256;")
    op.execute("DROP INDEX IF EXISTS ix_upload_link_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_upload_link_session;")
    op.execute("DROP INDEX IF EXISTS ix_upload_link_user;")
    op.execute("DROP TABLE IF EXISTS public.upload_link;")

    op.execute("DROP INDEX IF EXISTS ix_blob_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_blob_sha256;")
    op.execute("DROP TABLE IF EXISTS public.blob;")
