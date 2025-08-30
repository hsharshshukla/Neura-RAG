from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250824_add_email_verification"
down_revision = '67eec25b6a9f'   # 👈 parent revision id
branch_labels = None
depends_on = None

def upgrade():
    # Columns may already exist (you hot-fixed). Keep upgrade idempotent.
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ NULL')
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS email_verification_token_hash TEXT NULL')
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS email_verification_expires_at TIMESTAMPTZ NULL')
    # Index for token lookups (index=True inside add_column doesn't create it)
    op.execute('CREATE INDEX IF NOT EXISTS idx_user_email_verif_hash ON "user"(email_verification_token_hash)')

def downgrade():
    op.execute('DROP INDEX IF EXISTS idx_user_email_verif_hash')
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS email_verification_expires_at')
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS email_verification_token_hash')
    op.execute('ALTER TABLE "user" DROP COLUMN IF EXISTS email_verified_at')
