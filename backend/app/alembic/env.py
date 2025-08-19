# backend/app/alembic/env.py

from __future__ import annotations
import os
import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# --- Load .env so Alembic sees your variables ---
try:
    from dotenv import load_dotenv  # pip install python-dotenv
    HERE = Path(__file__).resolve()
    BACKEND_ROOT = HERE.parents[2]          # .../backend/
    for fname in (".env.dev", ".env"):      # load dev first, then .env (no override)
        p = BACKEND_ROOT / fname
        if p.exists():
            load_dotenv(p, override=False)
except Exception:
    HERE = Path(__file__).resolve()
    BACKEND_ROOT = HERE.parents[2]

# --- Alembic Config ---
config = context.config

# Prefer direct DB for migrations (ALEMBIC_URL), else fallback to DATABASE_URL
db_url = os.getenv("ALEMBIC_URL") or os.getenv("DATABASE_URL")
if not db_url:
    raise RuntimeError("Alembic needs ALEMBIC_URL or DATABASE_URL set.")
# Escape % for ConfigParser interpolation
config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Make `app/` importable no matter where we run from ---
# Insert backend/ at sys.path so `app.models` imports correctly
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Import models so metadata is populated
from app.models import *  # noqa: F401,F403
target_metadata = SQLModel.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
