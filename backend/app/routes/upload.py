# app/routes/upload.py
from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from fastapi import status
from sqlmodel import Session, select
from sqlalchemy import text
from pathlib import Path
from datetime import datetime, date, timedelta
import logging
import hashlib
import uuid
import os

from app.db import get_session
from app.models import User, ChatSession
from app.deps.auth import get_current_user
from app.utils.logger import log_event
from app.vector_store import embed_and_store
from app.parsers.parser import parse_and_clean_bytes  # txt/md/pdf/docx/pptx/xlsx/csv/json/jpg/png
from app.storage.storage import get_storage

# 🔒 SlowAPI (endpoint-level guard; plan-aware limits enforced inside)
from app.rate_limit import limiter

router = APIRouter(prefix="/api/v1", tags=["upload"])
logger = logging.getLogger("uvicorn.error")

ALLOWED_EXTS = {
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".txt", ".md", ".csv", ".json",
    ".jpg", ".jpeg", ".png",
}

# Global ceiling (safety valve) — plan caps must be <= this unless overridden
GLOBAL_MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
GLOBAL_MAX_SIZE_BYTES = GLOBAL_MAX_UPLOAD_MB * 1024 * 1024


# ---------- plan helpers ----------
def _plan_upload_knobs(tier: str) -> dict:
    """
    Return plan knobs:
      - max_mb: per-file size cap
      - daily_files: per-day upload count
      - rpm/rph: per-minute/hour request caps for /upload (DB-backed)
    Env overrides:
      UPLOAD_MAX_MB_PRO,    UPLOAD_MAX_MB_MINI,    UPLOAD_MAX_MB_FREE
      UPLOAD_DAILY_PRO,     UPLOAD_DAILY_MINI,     UPLOAD_DAILY_FREE
      UPLOAD_RPM_PRO,       UPLOAD_RPM_MINI,       UPLOAD_RPM_FREE
      UPLOAD_RPH_PRO,       UPLOAD_RPH_MINI,       UPLOAD_RPH_FREE
    """
    t = (tier or "free").strip().lower()
    def geti(name: str, default: int) -> int:
        v = os.getenv(name, "").strip()
        return int(v) if v.isdigit() else default

    if t == "pro":
        return {
            "max_mb": geti("UPLOAD_MAX_MB_PRO", 50),
            "daily_files": geti("UPLOAD_DAILY_PRO", 100),
            "rpm": geti("UPLOAD_RPM_PRO", 10),
            "rph": geti("UPLOAD_RPH_PRO", 120),
        }
    if "mini" in t:
        return {
            "max_mb": geti("UPLOAD_MAX_MB_MINI", 15),
            "daily_files": geti("UPLOAD_DAILY_MINI", 20),
            "rpm": geti("UPLOAD_RPM_MINI", 8),
            "rph": geti("UPLOAD_RPH_MINI", 80),
        }
    # free / default
    return {
        "max_mb": geti("UPLOAD_MAX_MB_FREE", 5),
        "daily_files": geti("UPLOAD_DAILY_FREE", 5),
        "rpm": geti("UPLOAD_RPM_FREE", 4),
        "rph": geti("UPLOAD_RPH_FREE", 40),
    }


def _enforce_plan_upload_rates(db: Session, user_id: int, tier: str) -> None:
    """
    Enforce per-plan RPM / RPH for uploads using DB timestamps on upload_link.
    """
    knobs = _plan_upload_knobs(tier)
    rpm, rph = knobs["rpm"], knobs["rph"]

    now = datetime.utcnow()
    one_min_ago = now - timedelta(minutes=1)
    one_hr_ago = now - timedelta(hours=1)

    # Count per-user upload_link inserts (successful uploads) in windows
    used_min = db.exec(text("""
        SELECT COUNT(1)
        FROM public.upload_link
        WHERE user_id = :u AND created_at >= :t
    """).bindparams(u=user_id, t=one_min_ago)).one()

    used_hr = db.exec(text("""
        SELECT COUNT(1)
        FROM public.upload_link
        WHERE user_id = :u AND created_at >= :t
    """).bindparams(u=user_id, t=one_hr_ago)).one()

    if used_min >= rpm:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Per-minute upload limit reached for your plan ({rpm}/minute). Try again in a moment.",
        )
    if used_hr >= rph:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Per-hour upload limit reached for your plan ({rph}/hour). Please try again later.",
        )


def _enforce_plan_daily_count(db: Session, user_id: int, tier: str) -> None:
    """
    Enforce per-plan daily file count using upload_link.created_at (UTC day).
    """
    knobs = _plan_upload_knobs(tier)
    limit = knobs["daily_files"]
    start = datetime.combine(date.today(), datetime.min.time())
    end = datetime.combine(date.today(), datetime.max.time())

    used = db.exec(text("""
        SELECT COUNT(1)
        FROM public.upload_link
        WHERE user_id = :u AND created_at >= :a AND created_at <= :b
    """).bindparams(u=user_id, a=start, b=end)).one()

    if used >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily upload limit reached for your plan ({limit}/day). Upgrade to increase your limit.",
        )


def _ensure_tables(db: Session) -> None:
    """
    Create minimal tables in Postgres if they don't exist.
    These are intentionally independent of your SQLModel metadata.
    """
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
@router.get("/upload/check")
@limiter.limit("60/minute")  # cheap, but prevent scraping
def check_duplicate(
    session_id: int,
    sha256: str,
    size: int,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """
    Frontend probe to skip re-uploads and preflight size.
    Returns duplicate/existence and 413 if the file exceeds plan cap or global cap.
    """
    _ensure_tables(db)

    # Ensure user exists (tenant guard)
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Plan caps
    knobs = _plan_upload_knobs(user.tier or "free")
    plan_max_mb = knobs["max_mb"]
    # Respect the tighter of (plan cap) vs (global ceiling), unless you want plan > global
    effective_max_mb = min(plan_max_mb, GLOBAL_MAX_UPLOAD_MB)
    effective_max_bytes = effective_max_mb * 1024 * 1024

    # Size preflight: fail fast so the UI never tries to upload too-large files
    if size > effective_max_bytes:
        raise HTTPException(status_code=413, detail=f"Max {effective_max_mb} MB for your plan")

    # Duplicate if same sha256+size already stored once.
    blob_stmt = text(
        "SELECT sha256 FROM public.blob WHERE sha256 = :h AND bytes = :b"
    ).bindparams(h=sha256, b=size)
    blob = db.exec(blob_stmt).first()
    exists = bool(blob)

    # Already linked to this session?
    link_stmt = text("""
        SELECT 1 FROM public.upload_link
        WHERE user_id = :u AND session_id = :s AND sha256 = :h
    """).bindparams(u=user.id, s=session_id, h=sha256)
    link = db.exec(link_stmt).first()
    has_link = bool(link)

    return {
        "exists": exists,
        "duplicate": exists,
        "linked": has_link,
        "max_bytes": effective_max_bytes,
        "max_mb": effective_max_mb,
        "plan_max_mb": plan_max_mb,
        "global_max_mb": GLOBAL_MAX_UPLOAD_MB,
    }


@router.post("/upload")
@limiter.limit("8/minute; 80/hour")  # coarse guard; plan-aware caps enforced below
async def upload_file(
    request: Request,
    session_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """
    Stores content only once by sha256; links content to user+session.
    Response: { ok, duplicate, session_id, doc_id, chars_indexed }
    Streaming implementation to avoid 413/memory blow-ups:
      - header pre-check (Content-Length)
      - chunked read with hard cap (plan-aware)
      - compute sha256 while streaming
      - write to temp file, then pass bytes to storage/parser
    """
    # Streaming chunk size
    CHUNK = 1024 * 1024  # 1 MB

    try:
        _ensure_tables(db)

        # 1) Auth
        user = db.exec(select(User).where(User.email == user_email)).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        tier = user.tier or "free"
        knobs = _plan_upload_knobs(tier)

        # Effective per-file cap (plan vs global)
        effective_max_mb = min(knobs["max_mb"], GLOBAL_MAX_UPLOAD_MB)
        effective_max_bytes = effective_max_mb * 1024 * 1024

        # Enforce per-plan RPM/RPH and daily count BEFORE reading body fully
        _enforce_plan_upload_rates(db, user.id, tier)
        _enforce_plan_daily_count(db, user.id, tier)

        # 2) Session ownership
        chat = db.exec(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user.id,
            )
        ).first()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat session not found")

        # 3) Validate headers and extension
        cl = request.headers.get("content-length")
        if cl and int(cl) > effective_max_bytes:
            raise HTTPException(status_code=413, detail=f"File too large (> {effective_max_mb} MB for your plan)")

        original_name = Path(file.filename or "").name[:200] or "upload"
        ext = Path(original_name).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=415, detail=f"Unsupported file extension: {ext or 'unknown'}")

        mime = getattr(file, "content_type", None) or ""

        # 4) Stream to a temp file while hashing and enforcing size cap
        tmp_dir = Path("./uploads/tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"up-{uuid.uuid4()}-{original_name}"

        sha = hashlib.sha256()
        size = 0

        try:
            with tmp_path.open("wb") as out:
                while True:
                    chunk = await file.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > effective_max_bytes:
                        raise HTTPException(status_code=413, detail=f"File too large (> {effective_max_mb} MB for your plan)")
                    sha.update(chunk)
                    out.write(chunk)
        finally:
            await file.close()

        if size == 0:
            raise HTTPException(status_code=400, detail="Empty file")

        sha_hex = sha.hexdigest()

        # 5) Check for existing blob
        blob_sel = text(
            "SELECT sha256, storage_uri FROM public.blob WHERE sha256 = :h"
        ).bindparams(h=sha_hex)
        blob_row = db.exec(blob_sel).mappings().first()

        blob_exists = bool(blob_row)
        storage_uri = blob_row["storage_uri"] if blob_row else None

        # 6) If blob missing: persist file once
        if not blob_exists:
            storage = get_storage()
            try:
                if hasattr(storage, "save_file"):
                    _, storage_uri = storage.save_file(
                        user_id=user.id,
                        session_id=session_id,
                        filename=original_name,
                        path=str(tmp_path),
                        mime=mime,
                    )
                elif hasattr(storage, "save_stream"):
                    with tmp_path.open("rb") as f:
                        _, storage_uri = storage.save_stream(
                            user_id=user.id,
                            session_id=session_id,
                            filename=original_name,
                            stream=f,
                            mime=mime,
                        )
                elif hasattr(storage, "save_bytes"):
                    data = tmp_path.read_bytes()
                    _, storage_uri = storage.save_bytes(
                        user_id=user.id,
                        session_id=session_id,
                        filename=original_name,
                        data=data,
                    )
                else:
                    data = tmp_path.read_bytes()
                    _, storage_uri = storage.save(
                        user_id=user.id,
                        session_id=session_id,
                        filename=original_name,
                        data=data,
                    )
            except Exception:
                logger.exception("Storage save failed for %s", original_name)
                raise HTTPException(status_code=500, detail="Upload failed: storage error")

            blob_ins = text("""
                INSERT INTO public.blob (sha256, bytes, ext, mime, storage_uri)
                VALUES (:h, :b, :e, :m, :u)
                ON CONFLICT (sha256) DO NOTHING
            """).bindparams(h=sha_hex, b=size, e=ext, m=mime, u=storage_uri)
            db.exec(blob_ins)
            db.commit()

        # 7) Ensure embeddings exist for this blob (only once per sha256)
        emb_sel = text("SELECT 1 FROM public.embedding_index WHERE sha256 = :h").bindparams(h=sha_hex)
        embedded = db.exec(emb_sel).first()

        chars_indexed = 0
        if not embedded:
            # Parse text from the temp file
            try:
                raw = tmp_path.read_bytes()
                try:
                    parsed = parse_and_clean_bytes(original_name, raw, mime)
                except TypeError:
                    parsed = parse_and_clean_bytes(original_name, raw)
                text_content = (parsed.get("text") if isinstance(parsed, dict) else parsed or "").strip()
            except Exception:
                logger.exception("Parsing failed for %s", original_name)
                text_content = ""

            if os.getenv("DISABLE_EMBED", "").lower() in ("1", "true", "yes"):
                logger.info("[upload] Skipping embed_and_store due to DISABLE_EMBED=1")
            else:
                if text_content:
                    try:
                        embed_and_store(
                            user_email=user_email,
                            text=text_content,
                            metadata={"sha256": sha_hex, "session_id": str(session_id), "doc_id": sha_hex},
                        )
                        chars_indexed = len(text_content)
                    except Exception:
                        logger.exception("Embedding/index failed for %s", original_name)
                        raise HTTPException(status_code=500, detail="Upload failed: embedding error")
                else:
                    log_event("upload_nontext", {
                        "user": user_email, "session_id": session_id, "sha256": sha_hex,
                        "size_bytes": size, "mime": mime, "ext": ext
                    })

            emb_ins = text("""
                INSERT INTO public.embedding_index (sha256, store_key, chunks)
                VALUES (:h, :k, :c)
                ON CONFLICT (sha256) DO NOTHING
            """).bindparams(h=sha_hex, k=sha_hex, c=None)
            db.exec(emb_ins)
            db.commit()

        # 8) Create per-user, per-session link to the blob
        doc_id = str(uuid.uuid4())
        link_ins = text("""
            INSERT INTO public.upload_link (user_id, session_id, sha256, doc_id)
            VALUES (:u, :s, :h, :d)
            ON CONFLICT (user_id, session_id, sha256) DO NOTHING
        """).bindparams(u=user.id, s=session_id, h=sha_hex, d=doc_id)
        db.exec(link_ins)
        db.commit()

        duplicate = blob_exists
        log_event("upload_ok", {
            "user": user_email,
            "session_id": session_id,
            "sha256": sha_hex,
            "storage_uri": storage_uri,
            "size_bytes": size,
            "mime": mime,
            "ext": ext,
            "duplicate": duplicate,
            "chars_indexed": chars_indexed,
            "plan": tier,
        })

        return {
            "ok": True,
            "duplicate": bool(duplicate),
            "session_id": session_id,
            "doc_id": doc_id,
            "chars_indexed": int(chars_indexed),
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Upload pipeline failed for %s", getattr(file, "filename", "<unknown>"))
        raise HTTPException(status_code=500, detail="Upload failed: server error")
    finally:
        # best-effort cleanup
        try:
            if 'tmp_path' in locals() and tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
