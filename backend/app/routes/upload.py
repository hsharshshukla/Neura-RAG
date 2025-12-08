# app/routes/upload.py
from __future__ import annotations

from typing import Annotated, Optional
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    status,
    UploadFile,
)
from sqlmodel import Session, select
from sqlalchemy import text
from pathlib import Path
from datetime import datetime, date, timedelta
import logging
import hashlib
import uuid
import io
import os

from app.db import get_session
from app.models import User, ChatSession
from app.deps.auth import get_current_user
from app.utils.logger import log_event
from app.vector_store import embed_and_store
from app.parsers.parser import parse_and_clean_bytes
from app.storage.storage import get_storage
from app.rate_limit import  key_user_or_ip  # SlowAPI limiter

router = APIRouter(prefix="/api/v1", tags=["upload"])
logger = logging.getLogger("uvicorn.error")

ALLOWED_EXTS = {
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".txt", ".md", ".csv", ".json",
    ".jpg", ".jpeg", ".png",
}

GLOBAL_MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
GLOBAL_MAX_SIZE_BYTES = GLOBAL_MAX_UPLOAD_MB * 1024 * 1024


# ---------- plan helpers ----------
def _plan_upload_knobs(tier: str) -> dict:
    t = (tier or "free").strip().lower()

    def geti(name: str, default: int) -> int:
        v = os.getenv(name, "").strip()
        return int(v) if v.isdigit() else default

    if t == "pro":
        return {"max_mb": geti("UPLOAD_MAX_MB_PRO", 50),
                "daily_files": geti("UPLOAD_DAILY_PRO", 100),
                "rpm": geti("UPLOAD_RPM_PRO", 10),
                "rph": geti("UPLOAD_RPH_PRO", 120)}
    if "mini" in t:
        return {"max_mb": geti("UPLOAD_MAX_MB_MINI", 15),
                "daily_files": geti("UPLOAD_DAILY_MINI", 20),
                "rpm": geti("UPLOAD_RPM_MINI", 8),
                "rph": geti("UPLOAD_RPH_MINI", 80)}
    return {"max_mb": geti("UPLOAD_MAX_MB_FREE", 5),
            "daily_files": geti("UPLOAD_DAILY_FREE", 5),
            "rpm": geti("UPLOAD_RPM_FREE", 4),
            "rph": geti("UPLOAD_RPH_FREE", 40)}


# def _enforce_plan_upload_rates(db: Session, user_id: int, tier: str) -> None:
#     knobs = _plan_upload_knobs(tier)
#     rpm, rph = knobs["rpm"], knobs["rph"]
#     now = datetime.utcnow()

#     used_min = db.exec(text("""
#         SELECT COUNT(1) FROM public.upload_link
#         WHERE user_id = :u AND created_at >= :t
#     """).bindparams(u=user_id, t=now - timedelta(minutes=1))).one()

#     used_hr = db.exec(text("""
#         SELECT COUNT(1) FROM public.upload_link
#         WHERE user_id = :u AND created_at >= :t
#     """).bindparams(u=user_id, t=now - timedelta(hours=1))).one()

#     if used_min >= rpm:
#         raise HTTPException(status_code=429, detail=f"Limit reached ({rpm}/min). Try again shortly.")
#     if used_hr >= rph:
#         raise HTTPException(status_code=429, detail=f"Hourly limit reached ({rph}/hr).")
def _enforce_plan_upload_rates(db: Session, user_id: int, tier: str) -> None:
    knobs = _plan_upload_knobs(tier)
    rpm, rph = knobs["rpm"], knobs["rph"]
    now = datetime.utcnow()

    used_min = db.exec(text("""
        SELECT COUNT(1) FROM public.upload_link
        WHERE user_id = :u AND created_at >= :t
    """).bindparams(u=user_id, t=now - timedelta(minutes=1))).one()[0]

    used_hr = db.exec(text("""
        SELECT COUNT(1) FROM public.upload_link
        WHERE user_id = :u AND created_at >= :t
    """).bindparams(u=user_id, t=now - timedelta(hours=1))).one()[0]

    if used_min >= rpm:
        raise HTTPException(status_code=429, detail=f"Limit reached ({rpm}/min). Try again shortly.")

    if used_hr >= rph:
        raise HTTPException(status_code=429, detail=f"Hourly limit reached ({rph}/hr).")


# def _enforce_plan_daily_count(db: Session, user_id: int, tier: str) -> None:
#     knobs = _plan_upload_knobs(tier)
#     limit = knobs["daily_files"]
#     start = datetime.combine(date.today(), datetime.min.time())
#     end = datetime.combine(date.today(), datetime.max.time())

#     used = db.exec(text("""
#         SELECT COUNT(1) FROM public.upload_link
#         WHERE user_id = :u AND created_at BETWEEN :a AND :b
#     """).bindparams(u=user_id, a=start, b=end)).one()

#     if used >= limit:
#         raise HTTPException(status_code=429, detail=f"Daily upload limit reached ({limit}/day).")

def _enforce_plan_daily_count(db: Session, user_id: int, tier: str) -> None:
    knobs = _plan_upload_knobs(tier)
    limit = knobs["daily_files"]
    start = datetime.combine(date.today(), datetime.min.time())
    end = datetime.combine(date.today(), datetime.max.time())

    used = db.exec(text("""
        SELECT COUNT(1) FROM public.upload_link
        WHERE user_id = :u AND created_at BETWEEN :a AND :b
    """).bindparams(u=user_id, a=start, b=end)).one()[0]

    if used >= limit:
        raise HTTPException(status_code=429, detail=f"Daily upload limit reached ({limit}/day).")


def _ensure_tables(db: Session) -> None:
    db.exec(text("""
        CREATE TABLE IF NOT EXISTS public.blob (
            id BIGSERIAL PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            bytes BIGINT NOT NULL,
            ext TEXT,
            mime TEXT,
            storage_uri TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
    """))
    db.exec(text("""
        CREATE TABLE IF NOT EXISTS public.upload_link (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            session_id INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, session_id, sha256)
        );
    """))
    db.exec(text("""
        CREATE TABLE IF NOT EXISTS public.embedding_index (
            id BIGSERIAL PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            store_key TEXT,
            chunks INTEGER,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
    """))
    db.commit()


# ---------- routes ----------
@router.get("/upload/check", response_model=None)
# @limiter.limit("60/minute", key_func=key_user_or_ip)
def check_duplicate(
    request: Request,
    response: Response,
    session_id: int,
    sha256: str,
    size: int,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """Check if upload already exists and validate file size per plan."""
    _ensure_tables(db)
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    knobs = _plan_upload_knobs(user.tier or "free")
    max_mb = min(knobs["max_mb"], GLOBAL_MAX_UPLOAD_MB)
    max_bytes = max_mb * 1024 * 1024

    if size > max_bytes:
        raise HTTPException(status_code=413, detail=f"Max {max_mb} MB for your plan")

    blob = db.exec(text("""
        SELECT 1 FROM public.blob WHERE sha256 = :h AND bytes = :b
    """).bindparams(h=sha256, b=size)).first()
    exists = bool(blob)

    link = db.exec(text("""
        SELECT 1 FROM public.upload_link
        WHERE user_id = :u AND session_id = :s AND sha256 = :h
    """).bindparams(u=user.id, s=session_id, h=sha256)).first()

    return {
        "exists": exists,
        "duplicate": exists,
        "linked": bool(link),
        "max_bytes": max_bytes,
        "max_mb": max_mb,
    }

@router.post("/upload", response_model=None)
async def upload_file(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    session_id: Optional[int] = Form(None),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):


    """Upload handler: deduplicate, parse, embed, and record."""
    _ensure_tables(db)

    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    tier = user.tier or "free"
    knobs = _plan_upload_knobs(tier)
    effective_max_mb = min(knobs["max_mb"], GLOBAL_MAX_UPLOAD_MB)
    effective_max_bytes = effective_max_mb * 1024 * 1024

    _enforce_plan_upload_rates(db, user.id, tier)
    _enforce_plan_daily_count(db, user.id, tier)

    chat = db.exec(select(ChatSession)
                   .where(ChatSession.id == session_id, ChatSession.user_id == user.id)).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat session not found")

    cl = request.headers.get("content-length")
    if cl and int(cl) > effective_max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large (> {effective_max_mb} MB)")

    original_name = Path(file.filename or "").name[:200] or "upload"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {ext or 'unknown'}")

    mime = getattr(file, "content_type", "") or ""
    sha = hashlib.sha256()
    size = 0
    data_stream = io.BytesIO()
    CHUNK = 1024 * 1024

    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > effective_max_bytes:
            raise HTTPException(status_code=413, detail=f"File too large (> {effective_max_mb} MB)")
        sha.update(chunk)
        data_stream.write(chunk)

    await file.close()
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    sha_hex = sha.hexdigest()
    data_stream.seek(0)

    blob_row = db.exec(text("""
        SELECT sha256, storage_uri FROM public.blob WHERE sha256 = :h
    """).bindparams(h=sha_hex)).mappings().first()

    blob_exists = bool(blob_row)
    storage_uri = blob_row["storage_uri"] if blob_row else None

    if not blob_exists:
        storage = get_storage()
        try:
            _, storage_uri = storage.save_stream(
                user_id=user.id,
                session_id=session_id,
                filename=original_name,
                stream=data_stream,
                mime=mime,
            )
        except Exception:
            logger.exception("Storage save failed for %s", original_name)
            raise HTTPException(status_code=500, detail="Storage error")

        db.exec(text("""
            INSERT INTO public.blob (sha256, bytes, ext, mime, storage_uri)
            VALUES (:h, :b, :e, :m, :u)
            ON CONFLICT (sha256) DO NOTHING
        """).bindparams(h=sha_hex, b=size, e=ext, m=mime, u=storage_uri))
        db.commit()

    embedded = db.exec(text("SELECT 1 FROM public.embedding_index WHERE sha256 = :h")
                       .bindparams(h=sha_hex)).first()

    chars_indexed = 0
    if not embedded:
        try:
            data_stream.seek(0)
            raw = data_stream.read()
            try:
                parsed = parse_and_clean_bytes(original_name, raw, mime)
            except TypeError:
                parsed = parse_and_clean_bytes(original_name, raw)
            text_content = (parsed.get("text") if isinstance(parsed, dict) else parsed or "").strip()
        except Exception:
            logger.exception("Parsing failed for %s", original_name)
            text_content = ""

        if os.getenv("DISABLE_EMBED", "").lower() not in ("1", "true", "yes"):
            if text_content:
                try:
                    embed_and_store(
                        user_email=user_email,
                        text=text_content,
                        metadata={"sha256": sha_hex,
                                  "session_id": str(session_id),
                                  "doc_id": sha_hex},
                    )
                    chars_indexed = len(text_content)
                except Exception:
                    logger.exception("Embedding failed for %s", original_name)
                    raise HTTPException(status_code=500, detail="Embedding error")
            else:
                log_event("upload_nontext", {
                    "user": user_email, "session_id": session_id,
                    "sha256": sha_hex, "size_bytes": size, "mime": mime, "ext": ext,
                })

        db.exec(text("""
            INSERT INTO public.embedding_index (sha256, store_key, chunks)
            VALUES (:h, :k, :c)
            ON CONFLICT (sha256) DO NOTHING
        """).bindparams(h=sha_hex, k=sha_hex, c=None))
        db.commit()

    doc_id = str(uuid.uuid4())
    db.exec(text("""
        INSERT INTO public.upload_link (user_id, session_id, sha256, doc_id)
        VALUES (:u, :s, :h, :d)
        ON CONFLICT (user_id, session_id, sha256) DO NOTHING
    """).bindparams(u=user.id, s=session_id, h=sha_hex, d=doc_id))
    db.commit()

    log_event("upload_ok", {
        "user": user_email, "session_id": session_id,
        "sha256": sha_hex, "storage_uri": storage_uri,
        "size_bytes": size, "mime": mime, "ext": ext,
        "duplicate": blob_exists, "chars_indexed": chars_indexed, "plan": tier,
    })

    return {
        "ok": True,
        "duplicate": bool(blob_exists),
        "session_id": session_id,
        "doc_id": doc_id,
        "chars_indexed": int(chars_indexed),
    }

