# backend/scripts/migrate_sqlite_to_supabase.py

import os, json
from datetime import datetime
from typing import Any, Dict, Iterable

from sqlmodel import create_engine, Session, select
from sqlalchemy import MetaData, Table, Column, Integer, String, Text, DateTime, Boolean, LargeBinary
from sqlalchemy.dialects.postgresql import insert as pg_insert
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import  text
from uuid import uuid5, NAMESPACE_URL


# OPTIONAL: pgvector for embeddings
try:
    from pgvector.sqlalchemy import Vector
except Exception:
    Vector = None

# --- CONFIG ---
SQLITE_URL = os.getenv("SQLITE_URL", "sqlite:///./data.db")  # adjust if your file is elsewhere
PG_URL = os.getenv("DATABASE_URL")  # must be set in PowerShell before running

# --- Connect engines ---
src = create_engine(SQLITE_URL)
dst = create_engine(PG_URL, pool_pre_ping=True, future=True)

def sqlite_tables():
    with src.connect() as c:
        rows = c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return set(r[0] for r in rows)

SQLITE_TABLES = sqlite_tables()
print("SQLite has tables:", sorted(SQLITE_TABLES))


# --- Import your SQLModel models for the core tables ---
# Make sure Python can import your backend package
import sys
from pathlib import Path
BACKEND_DIR = Path(__file__).resolve().parents[2]  # -> backend/
sys.path.append(str(BACKEND_DIR))

from app.models import (
    User, Chat, Upload, UploadedFile, ChatSession,
    ChatMessage, UsageLog, PasswordResetToken, DailyUsage
)

CORE_TABLES = [User, Chat, Upload, UploadedFile, ChatSession,
               ChatMessage, UsageLog, PasswordResetToken, DailyUsage]

# --- Helpers ---
def as_epoch(v, fallback_dt=None):
    if v is None:
        if fallback_dt:
            return int((fallback_dt if isinstance(fallback_dt, datetime) else as_dt(fallback_dt)).timestamp())
        return None
    if isinstance(v, (int, float)):  # already numeric
        return int(v)
    s = str(v)
    # try numeric string
    try:
        return int(float(s))
    except Exception:
        pass
    # try datetime string
    dt = as_dt(s)
    return int(dt.timestamp()) if dt else None

def as_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v)
    # ISO or ISO-like
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            pass
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    # epoch seconds
    try:
        return datetime.utcfromtimestamp(float(s))
    except Exception:
        return None

def as_vec(v):
    """Parse embedding from JSON/text -> list[float]."""
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [float(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8", errors="ignore")
    if isinstance(v, str):
        v2 = v.strip()
        # JSON array?
        try:
            arr = json.loads(v2)
            if isinstance(arr, (list, tuple)):
                return [float(x) for x in arr]
        except Exception:
            pass
        # Comma/space separated numbers
        v2 = v2.strip("[](){}")
        try:
            return [float(x) for x in v2.split(",")]
        except Exception:
            try:
                return [float(x) for x in v2.split()]
            except Exception:
                return None
    return None

def chunked(iterable: Iterable, size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch

def copy_sqlmodel_table(model, batch_size=1000):
    from datetime import datetime

    # --- small local helpers (no external deps) ---
    def _as_dt(v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        s = str(v)
        # handles 'YYYY-MM-DD HH:MM:SS[.ffffff]' and ISO with 'T'
        try:
            # also handles already-epoch-like numeric strings accidentally
            if s.isdigit():
                return datetime.utcfromtimestamp(int(s))
            return datetime.fromisoformat(s.replace("Z", "+00:00").replace("T", " ")[:26])
        except Exception:
            # last resort: try float epoch
            try:
                return datetime.utcfromtimestamp(float(s))
            except Exception:
                return None

    def _as_epoch(v, fallback_dt=None):
        if v is None:
            if fallback_dt:
                return int((fallback_dt if isinstance(fallback_dt, datetime) else _as_dt(fallback_dt)).timestamp())
            return None
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v)
        # numeric string?
        try:
            return int(float(s))
        except Exception:
            pass
        # datetime string?
        dt = _as_dt(s)
        return int(dt.timestamp()) if dt else None

    table_name = model.__table__.name
    if table_name not in SQLITE_TABLES:
        print(f"… {table_name}: SKIP (not in sqlite)")
        return

    """Copy rows for tables that have SQLModel classes."""
    with Session(src) as s_src:
        rows = s_src.exec(select(model)).all()
    if not rows:
        print(f"… {model.__name__}: 0 rows")
        return

    inserted = 0
    with Session(dst) as s_dst:
        for batch in chunked(rows, batch_size):
            payload = []
            for r in batch:
                data = r.model_dump() if hasattr(r, "model_dump") else r.dict()

                # normalize common datetime-ish fields to real datetimes
                for k in ("created_at", "updated_at", "expires_at"):
                    if k in data:
                        data[k] = _as_dt(data[k])

                # SPECIAL CASE: chatmessage.timestamp must be an int epoch
                if table_name == "chatmessage":
                    data["created_at"] = _as_dt(data.get("created_at"))
                    data["timestamp"] = _as_epoch(data.get("timestamp"), fallback_dt=data.get("created_at"))

                    # chatmessage PK/FKs should be ints in PG
                    for k in ("id", "session_id", "user_id"):
                        if k in data and isinstance(data[k], str):
                            # coerce "123" or "123.0" to int when possible
                            try:
                                data[k] = int(float(data[k]))
                            except Exception:
                                pass

                payload.append(data)

            table = model.__table__
            if "id" in table.c:
                stmt = pg_insert(table).values(payload).on_conflict_do_nothing(index_elements=["id"])
            else:
                stmt = pg_insert(table).values(payload).on_conflict_do_nothing()
            s_dst.exec(stmt)
            s_dst.commit()
            inserted += len(payload)

    print(f"✔ {model.__name__}: {inserted} rows copied")


def synthesize_chat_from_sessions(batch_size=1000):
    """Create Chat rows in Postgres from SQLite chatsession + chatmessage."""
    # 1) Load users (id -> email)
    with src.connect() as c:
        user_rows = c.exec_driver_sql("SELECT id, email FROM user").mappings().all()
        users = {int(r["id"]): r["email"] for r in user_rows}

        # 2) Load sessions
        sess_rows = c.exec_driver_sql(
            "SELECT id, user_id, title, created_at FROM chatsession"
        ).mappings().all()

        # 3) Latest message timestamp per session
        msg_rows = c.exec_driver_sql(
            "SELECT session_id, created_at FROM chatmessage"
        ).mappings().all()
    latest = {}
    for r in msg_rows:
        sid = r["session_id"]
        dt  = as_dt(r["created_at"])
        if dt is None:
            continue
        if sid not in latest or dt > latest[sid]:
            latest[sid] = dt

    # 4) Build payload
    from app.models import Chat  # ensure table exists in metadata
    payload = []
    for s in sess_rows:
        sid        = int(s["id"])
        user_email = users.get(int(s["user_id"]), None)
        title      = s["title"] or f"Session {sid}"
        created_at = as_dt(s["created_at"]) or datetime.utcnow()
        updated_at = latest.get(sid, created_at)

        # deterministic UUID from session id, so re-runs don't duplicate
        chat_id = str(uuid5(NAMESPACE_URL, f"neura-chat-session:{sid}"))

        payload.append({
            "id": chat_id,
            "user_email": user_email or "",
            "title": title,
            "created_at": created_at,
            "updated_at": updated_at,
        })

    if not payload:
        print("… chat synth: no sessions found")
        return

    # 5) Insert with upsert
    table = Chat.__table__
    with Session(dst) as s_dst:
        for batch in chunked(payload, batch_size):
            stmt = pg_insert(table).values(batch).on_conflict_do_nothing(index_elements=["id"])
            s_dst.exec(stmt)
            s_dst.commit()
    print(f"✔ chat synth: {len(payload)} rows inserted (ON CONFLICT DO NOTHING)")

# --- Raw table copies for tables without SQLModel classes ---
def copy_upload_link(batch_size=2000):
    meta_src = MetaData()
    meta_dst = MetaData()

    t_src = Table("upload_link", meta_src, autoload_with=src)
    # target schema matches the Alembic migration we created
    t_dst = Table(
        "upload_link",
        meta_dst,
        Column("id", String, primary_key=True),
        Column("upload_id", Integer, nullable=False),
        Column("user_email", String, nullable=False),
        Column("url", Text, nullable=False),
        Column("expires_at", DateTime(timezone=True), nullable=False),
        Column("used", Boolean, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )

    with src.connect() as c_src, dst.connect() as c_dst:
        rows = c_src.execute(t_src.select()).mappings().all()
        if not rows:
            print("… upload_link: 0 rows")
            return
        total = 0
        for batch in chunked(rows, batch_size):
            payload = []
            for r in batch:
                payload.append({
                    "id": str(r.get("id")),
                    "upload_id": int(r.get("upload_id")) if r.get("upload_id") is not None else None,
                    "user_email": r.get("user_email"),
                    "url": r.get("url"),
                    "expires_at": as_dt(r.get("expires_at")),
                    "used": bool(r.get("used")) if r.get("used") is not None else False,
                    "created_at": as_dt(r.get("created_at")) or datetime.utcnow(),
                })
            stmt = pg_insert(t_dst).values(payload).on_conflict_do_nothing(index_elements=["id"])
            c_dst.execute(stmt)
            c_dst.commit()
            total += len(payload)
    print(f"✔ upload_link: {total} rows copied")

def copy_blob(batch_size=500):
    meta_src = MetaData()
    meta_dst = MetaData()

    t_src = Table("blob", meta_src, autoload_with=src)
    t_dst = Table(
        "blob",
        meta_dst,
        Column("id", String, primary_key=True),
        Column("upload_id", Integer),
        Column("user_email", String, nullable=False),
        Column("mime_type", String),
        Column("size_bytes", Integer),
        Column("sha256", String(64)),
        Column("data", LargeBinary, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    with src.connect() as c_src, dst.connect() as c_dst:
        rows = c_src.execute(t_src.select()).mappings().all()
        if not rows:
            print("… blob: 0 rows")
            return
        total = 0
        for batch in chunked(rows, batch_size):
            payload = []
            for r in batch:
                payload.append({
                    "id": str(r.get("id")),
                    "upload_id": int(r.get("upload_id")) if r.get("upload_id") is not None else None,
                    "user_email": r.get("user_email"),
                    "mime_type": r.get("mime_type"),
                    "size_bytes": int(r.get("size_bytes")) if r.get("size_bytes") is not None else None,
                    "sha256": r.get("sha256"),
                    "data": r.get("data"),  # SQLite BLOB -> bytes -> PG BYTEA (psycopg handles)
                    "created_at": as_dt(r.get("created_at")) or datetime.utcnow(),
                })
            stmt = pg_insert(t_dst).values(payload).on_conflict_do_nothing(index_elements=["id"])
            c_dst.execute(stmt)
            c_dst.commit()
            total += len(payload)
    print(f"✔ blob: {total} rows copied")

def copy_embedding_index(batch_size=1000, dim=1536):
    if Vector is None:
        print("⚠ embedding_index skipped (pgvector not installed). pip install pgvector to migrate it.")
        return

    meta_src = MetaData()
    meta_dst = MetaData()

    t_src = Table("embedding_index", meta_src, autoload_with=src)
    t_dst = Table(
        "embedding_index",
        meta_dst,
        Column("id", String, primary_key=True),
        Column("user_email", String, nullable=False),
        Column("session_id", String),
        Column("upload_id", Integer),
        Column("chunk_id", String),
        Column("content", Text, nullable=False),
        Column("embedding", Vector(dim=dim), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )

    with src.connect() as c_src, dst.connect() as c_dst:
        rows = c_src.execute(t_src.select()).mappings().all()
        if not rows:
            print("… embedding_index: 0 rows")
            return
        total = 0
        for batch in chunked(rows, batch_size):
            payload = []
            for r in batch:
                vec = as_vec(r.get("embedding"))
                if vec is None:
                    # skip bad rows but keep going
                    continue
                payload.append({
                    "id": str(r.get("id")),
                    "user_email": r.get("user_email"),
                    "session_id": r.get("session_id"),
                    "upload_id": int(r.get("upload_id")) if r.get("upload_id") is not None else None,
                    "chunk_id": r.get("chunk_id"),
                    "content": r.get("content") or "",
                    "embedding": vec,
                    "created_at": as_dt(r.get("created_at")) or datetime.utcnow(),
                })
            if not payload:
                continue
            stmt = pg_insert(t_dst).values(payload).on_conflict_do_nothing(index_elements=["id"])
            c_dst.execute(stmt)
            c_dst.commit()
            total += len(payload)
    print(f"✔ embedding_index: {total} rows copied")



def synthesize_chat_from_sessions(batch_size=1000):
    # load users (id -> email)
    with src.connect() as c:
        users = {int(r["id"]): r["email"]
                 for r in c.exec_driver_sql("SELECT id, email FROM user").mappings().all()}

        sessions = c.exec_driver_sql(
            "SELECT id, user_id, title, created_at FROM chatsession"
        ).mappings().all()

        msgs = c.exec_driver_sql(
            "SELECT session_id, created_at FROM chatmessage"
        ).mappings().all()

    # latest message per session
    latest = {}
    for r in msgs:
        sid = r["session_id"]
        dt  = as_dt(r["created_at"])
        if dt and (sid not in latest or dt > latest[sid]):
            latest[sid] = dt

    # build Chat rows
    from app.models import Chat
    payload = []
    for s in sessions:
        sid = int(s["id"])
        chat_id = str(uuid5(NAMESPACE_URL, f"neura-chat-session:{sid}"))  # deterministic
        created_at = as_dt(s["created_at"]) or datetime.utcnow()
        payload.append({
            "id": chat_id,
            "user_email": users.get(int(s["user_id"]), "") or "",
            "title": s["title"] or f"Session {sid}",
            "created_at": created_at,
            "updated_at": latest.get(sid, created_at),
        })

    if not payload:
        print("… chat synth: no sessions found")
        return

    table = Chat.__table__
    with Session(dst) as s_dst:
        for batch in chunked(payload, batch_size):
            stmt = pg_insert(table).values(batch).on_conflict_do_nothing(index_elements=["id"])
            s_dst.exec(stmt)
            s_dst.commit()
    print(f"✔ chat synth: {len(payload)} rows inserted (ON CONFLICT DO NOTHING)")


def main():
    # --- copy core tables that DO exist in sqlite (skip Chat here) ---
    for model in [User, Upload, UploadedFile, ChatSession, ChatMessage,
                  UsageLog, PasswordResetToken, DailyUsage]:
        copy_sqlmodel_table(model)

    # --- create Chat rows in Postgres from sessions + messages ---
    synthesize_chat_from_sessions()

    # --- extra tables created via Alembic (copy only if present in sqlite) ---
    if "upload_link" in SQLITE_TABLES:
        copy_upload_link()
    else:
        print("… upload_link: SKIP (not in sqlite)")

    if "blob" in SQLITE_TABLES:
        copy_blob()
    else:
        print("… blob: SKIP (not in sqlite)")

    if "embedding_index" in SQLITE_TABLES:
        copy_embedding_index()
    else:
        print("… embedding_index: SKIP (not in sqlite)")


# def main():
#     # core SQLModel-backed tables first (respecting typical dependencies)
#     for model in CORE_TABLES:
#         copy_sqlmodel_table(model)

#     # raw tables created via Alembic (no SQLModel classes)
#     # Comment out any you don't actually use.
#     try:
#         copy_upload_link()
#     except Exception as e:
#         print("⚠ upload_link copy error:", e)
#     try:
#         copy_blob()
#     except Exception as e:
#         print("⚠ blob copy error:", e)
#     try:
#         copy_embedding_index()
#     except Exception as e:
#         print("⚠ embedding_index copy error:", e)

if __name__ == "__main__":
    main()
