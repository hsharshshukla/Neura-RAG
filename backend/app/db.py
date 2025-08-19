# app/db.py
from __future__ import annotations

import os
from sqlmodel import SQLModel, create_engine, Session

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
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))

# Create the engine (Supabase requires SSL; you already include sslmode=require in the URL)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # protect against stale connections
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    echo=ECHO_SQL,
    future=True,
)

def get_session():
    """FastAPI dependency: yields a SQLModel Session bound to our engine."""
    with Session(engine) as session:
        yield session


# # import os
# # from sqlmodel import create_engine, Session

# # # Always resolve to the absolute path of chatbot.db within app folder
# # DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "chatbot.db"))
# # DATABASE_URL = f"sqlite:///{DB_PATH}"
# # engine = create_engine(DATABASE_URL, echo=True)

# # def get_session():
# #     return Session(engine)


# # app/db.py
# from sqlmodel import SQLModel, create_engine
# import os

# DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data.db")

# engine = create_engine(
#     DATABASE_URL,
#     pool_pre_ping=True,
#     pool_size=5,
#     max_overflow=10,
#     future=True,
# )
# def get_session():
#     from sqlmodel import Session
#     with Session(engine) as session:
#         yield session
