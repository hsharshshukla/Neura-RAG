"""merge heads

Revision ID: 61b4c88e8820
Revises: 20250824_add_email_verification, 67eec25b6a9f
Create Date: 2025-08-25 22:24:36.798385
"""
from alembic import op
import sqlalchemy as sa

revision = "61b4c88e8820"
down_revision = ("20250824_add_email_verification", "67eec25b6a9f")  # ✅ two parents, no self
branch_labels = None
depends_on = None

def upgrade():
    pass  # merge only

def downgrade():
    pass
