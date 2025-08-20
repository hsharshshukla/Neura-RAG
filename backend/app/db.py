# app/db.py
from __future__ import annotations
import os
from sqlalchemy import create_engine
from sqlmodel import SQLModel, Session
from urllib.parse import urlparse

# --- Load .env in dev ---
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    pass

def _normalize_url(url: str) -> str:
    """Ensure SQLAlchemy DSN is in correct format (postgresql+psycopg://)."""
    if not url:
        return url
    # Replace old scheme postgres:// with postgresql+psycopg://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

def _is_sqlite(url: str | None) -> bool:
    return bool(url and url.strip().lower().startswith("sqlite:"))

# --- Env vars ---
DATABASE_URL = _normalize_url(os.getenv("DATABASE_URL"))
ALLOW_SQLITE = os.getenv("ALLOW_SQLITE", "").lower() in ("1", "true", "yes")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Example for Supabase:\n"
        "postgresql+psycopg://postgres:<PW>@<ref>.pooler.supabase.com:6543/postgres?sslmode=require"
    )

if _is_sqlite(DATABASE_URL) and not ALLOW_SQLITE:
    raise RuntimeError(
        "SQLite is only allowed for local testing. Provide a Postgres URL or set ALLOW_SQLITE=true."
    )

ECHO_SQL = os.getenv("SQL_ECHO", "").lower() in ("1", "true", "yes")
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "2"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "5"))

# --- Force IPv4 if host resolves to IPv6 but fails ---
if DATABASE_URL.startswith("postgresql+psycopg://"):
    parsed = urlparse(DATABASE_URL)
    host = parsed.hostname or ""
    if ":" in host:  # looks like IPv6
        raise RuntimeError(
            f"DATABASE_URL host resolves to IPv6 ({host}) which is unreachable. "
            f"Please update to use IPv4 DNS name (e.g. db.supabase.com)."
        )

# --- Engine ---
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    echo=ECHO_SQL,
    future=True,
)

def get_session():
    """FastAPI dependency that yields a Session bound to engine."""
    with Session(engine) as session:
        yield session
