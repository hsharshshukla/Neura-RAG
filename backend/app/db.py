# app/db.py
from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlmodel import SQLModel, Session

# --- Load .env in dev (safe to ignore if not installed) ---
try:
    from dotenv import load_dotenv, find_dotenv
    # finds .env / .env.dev starting from CWD upward
    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    pass


def _is_sqlite(url: str | None) -> bool:
    return bool(url and url.strip().lower().startswith("sqlite:"))


# Read DSN from env (required for non-test runs)
DATABASE_URL = os.getenv("DATABASE_URL")

# Allow SQLite only if you *explicitly* opt in (tests/local only)
ALLOW_SQLITE = os.getenv("ALLOW_SQLITE", "").lower() in ("1", "true", "yes")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Point this to your Supabase pooled URL, e.g.:\n"
        "postgresql+psycopg://postgres:<PW>@<ref>.pooler.supabase.com:6543/postgres?sslmode=require"
    )

if _is_sqlite(DATABASE_URL) and not ALLOW_SQLITE:
    raise RuntimeError(
        "DATABASE_URL points to SQLite. Set a Postgres (Supabase) URL instead, "
        "or set ALLOW_SQLITE=true only for local testing."
    )

# Optional toggles via env
ECHO_SQL = os.getenv("SQL_ECHO", "").lower() in ("1", "true", "yes")
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "2"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "5"))

# Create the engine (Supabase requires SSL; you already include sslmode=require in the URL)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # protect against stale connections
    pool_recycle=300,  
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    echo=ECHO_SQL,
    future=True,
)

def get_session():
    """FastAPI dependency: yields a SQLModel Session bound to our engine."""
    with Session(engine) as session:
        yield session

