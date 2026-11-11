# app/db.py
from __future__ import annotations
import os
import socket
from collections.abc import Generator
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlmodel import Session

# --- Load .env in dev ---
try:
    from dotenv import load_dotenv, find_dotenv

    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    pass


def _normalize_url(url: str | None) -> str:
    """Ensure SQLAlchemy DSN is in correct format (postgresql+psycopg://)."""
    if not url:
        return ""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _is_sqlite(url: str | None) -> bool:
    return bool(url and url.strip().lower().startswith("sqlite:"))


def _redact_password(dsn: str) -> str:
    try:
        p = urlparse(dsn)
        if p.password:
            netloc = p.netloc.replace(f":{p.password}@", ":***@")
        else:
            netloc = p.netloc
        return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))
    except Exception:
        return dsn


def _diagnose(dsn: str) -> None:
    """Print connection details & DNS resolution for Render logs."""
    try:
        # Basic parse via SQLAlchemy (tolerant of DB URLs)
        u = make_url(dsn)
        sslmode = None
        try:
            # Also peel from the raw querystring to be explicit
            q = parse_qs(urlparse(dsn).query)
            sslmode = (q.get("sslmode") or [""])[0] or None
        except Exception:
            pass

        # print("=== DB DIAG START ===")
        # print(f"Driver     : {u.drivername}")               # e.g. postgresql+psycopg
        # print(f"Username   : {u.username or ''}")
        # print(f"Database   : {u.database or ''}")
        # print(f"Host       : {u.host or ''}")
        # print(f"Port       : {u.port or ''}")
        # if sslmode:
        #     print(f"SSL Mode   : {sslmode}")
        # # Show whether any PG* envs are present (without values)
        # pg_envs = [k for k in os.environ.keys() if k.startswith("PG")]
        # if pg_envs:
        #     print(f"PG* envs   : {', '.join(pg_envs)}")

        # host = u.host or ""
        # port = u.port or 5432
        # if host:
        #     try:
        #         infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        #         v4 = sorted({addr[0] for fam, _, _, _, addr in infos if fam == socket.AF_INET})
        #         v6 = sorted({addr[0] for fam, _, _, _, addr in infos if fam == socket.AF_INET6})
        #         if v4:
        #             print(f"DNS IPv4   : {', '.join(v4)}")
        #         if v6:
        #             print(f"DNS IPv6   : {', '.join(v6)}")
        #         if not v4 and not v6:
        #             print("DNS        : (no A/AAAA records returned)")
        #     except Exception as e:
        #         print(f"DNS error  : {type(e).__name__}: {e}")
        # else:
        #     print("Host       : (empty)")

        # # Print the redacted DSN we will actually pass to SQLAlchemy
        # print(f"DSN (redac): {_redact_password(dsn)}")
        # print("=== DB DIAG END ===")
    except Exception as e:
        print(f"DB DIAG failure: {type(e).__name__}: {e}")


# --- Env vars ---
RAW_DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_URL = _normalize_url(RAW_DATABASE_URL)
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

# Optional toggles via env
ECHO_SQL = os.getenv("SQL_ECHO", "").lower() in ("1", "true", "yes")
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "2"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "5"))
CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "5"))  # seconds

# Log what we are about to use (to Render stdout)
_diagnose(DATABASE_URL)

# --- Extra sanity: don’t allow literal IPv6 host in URL (Render can't reach it) ---
try:
    parsed = urlparse(DATABASE_URL)
    if parsed.hostname and ":" in parsed.hostname:
        # Literal IPv6 present
        print(f"Warning: DATABASE_URL contains a literal IPv6 host: {parsed.hostname}")
except Exception:
    pass

# --- Engine ---
# We pass a short connect_timeout so failures show quickly in logs.
connect_args: dict[str, object] = (
    {"check_same_thread": False}
    if _is_sqlite(DATABASE_URL)
    else {"connect_timeout": CONNECT_TIMEOUT}
)
# sslmode is already in the URL, but adding here doesn’t hurt in psycopg3.
if not _is_sqlite(DATABASE_URL) and "sslmode=" not in (urlparse(DATABASE_URL).query or ""):
    connect_args["sslmode"] = "require"

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    **({} if _is_sqlite(DATABASE_URL) else {"pool_size": POOL_SIZE, "max_overflow": MAX_OVERFLOW}),
    echo=ECHO_SQL,
    future=True,
    connect_args=connect_args,
)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a Session bound to engine."""
    with Session(engine) as session:
        yield session
