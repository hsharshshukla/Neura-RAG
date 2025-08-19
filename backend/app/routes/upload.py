# app/routes/upload.py
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlmodel import Session, select
from sqlalchemy import text
from pathlib import Path
from datetime import datetime
import logging
import uuid
import hashlib

from app.db import get_session
from app.models import User, ChatSession
from app.deps.auth import get_current_user
from app.utils.logger import log_event
from app.vector_store import embed_and_store
from app.parsers.parser import parse_and_clean_bytes  # txt/md/pdf/docx/pptx/xlsx/csv/json/jpg/png
from app.storage.storage import get_storage

router = APIRouter(prefix="/api/v1", tags=["upload"])

ALLOWED_EXTS = {
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".txt", ".md", ".csv", ".json",
    ".jpg", ".jpeg", ".png",
}
MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


# ---------- helpers ----------
def _safe_name(name: str) -> str:
    return Path(name or "upload").name[:200]


def _ext(name: str) -> str:
    return Path(name or "").suffix.lower()


def _sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


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
def check_duplicate(
    session_id: int,
    sha256: str,
    size: int,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """
    Frontend probe to skip re-uploads. Returns duplicate/existence.
    """
    _ensure_tables(db)

    # Ensure the user exists (keeps tenancy consistent)
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Duplicate if same sha256 (and size, for safety) already stored once.
    blob_stmt = text(
        "SELECT sha256 FROM public.blob WHERE sha256 = :h AND bytes = :b"
    ).bindparams(h=sha256, b=size)
    blob = db.exec(blob_stmt).first()
    exists = bool(blob)

    # Also check if this user-session already linked to that blob.
    link_stmt = text("""
        SELECT 1 FROM public.upload_link
        WHERE user_id = :u AND session_id = :s AND sha256 = :h
    """).bindparams(u=user.id, s=session_id, h=sha256)
    link = db.exec(link_stmt).first()
    has_link = bool(link)

    return {"exists": exists, "duplicate": exists, "linked": has_link}


@router.post("/upload")
async def upload_file(
    session_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """
    Stores content only once by sha256; links content to user+session.
    Response: { ok, duplicate, session_id, doc_id, chars_indexed }
    """
    try:
        _ensure_tables(db)

        # 1) Auth
        user = db.exec(select(User).where(User.email == user_email)).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # 2) Session ownership
        chat = db.exec(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user.id,
            )
        ).first()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat session not found")

        # 3) Read & validate
        original_name = _safe_name(file.filename or "")
        ext = _ext(original_name)
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=415, detail=f"Unsupported file extension: {ext or 'unknown'}")

        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Empty file")
        if len(raw) > MAX_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (> {MAX_SIZE_BYTES // (1024*1024)} MB)",
            )

        sha = _sha256(raw)
        mime = getattr(file, "content_type", None) or ""

        # 4) Check for existing blob
        blob_sel = text(
            "SELECT sha256, storage_uri FROM public.blob WHERE sha256 = :h"
        ).bindparams(h=sha)
        blob_row = db.exec(blob_sel).mappings().first()

        blob_exists = bool(blob_row)
        storage_uri = blob_row["storage_uri"] if blob_row else None

        # 5) If blob missing: persist file once
        if not blob_exists:
            storage = get_storage()
            _, storage_uri = storage.save(
                user_id=user.id,
                session_id=session_id,
                filename=original_name,
                data=raw,
            )
            blob_ins = text("""
                INSERT INTO public.blob (sha256, bytes, ext, mime, storage_uri)
                VALUES (:h, :b, :e, :m, :u)
                ON CONFLICT (sha256) DO NOTHING
            """).bindparams(h=sha, b=len(raw), e=ext, m=mime, u=storage_uri)
            db.exec(blob_ins)
            db.commit()

        # 6) Ensure embeddings exist for this blob (only once per sha256)
        emb_sel = text(
            "SELECT 1 FROM public.embedding_index WHERE sha256 = :h"
        ).bindparams(h=sha)
        embedded = db.exec(emb_sel).first()

        chars_indexed = 0
        if not embedded:
            parsed = parse_and_clean_bytes(original_name, raw, mime)
            text_content = (parsed.get("text") or "").strip()

            if text_content:
                embed_and_store(
                    user_email=user_email,
                    text=text_content,
                    metadata={"sha256": sha, "session_id": str(session_id), "doc_id": sha},
                )
                chars_indexed = len(text_content)
            else:
                log_event("upload_nontext", {
                    "user": user_email, "session_id": session_id, "sha256": sha,
                    "size_bytes": len(raw), "mime": mime, "ext": ext
                })

            emb_ins = text("""
                INSERT INTO public.embedding_index (sha256, store_key, chunks)
                VALUES (:h, :k, :c)
                ON CONFLICT (sha256) DO NOTHING
            """).bindparams(h=sha, k=sha, c=None)
            db.exec(emb_ins)
            db.commit()

        # 7) Create (or keep) the per-user, per-session link to the blob
        doc_id = str(uuid.uuid4())
        link_ins = text("""
            INSERT INTO public.upload_link (user_id, session_id, sha256, doc_id)
            VALUES (:u, :s, :h, :d)
            ON CONFLICT (user_id, session_id, sha256) DO NOTHING
        """).bindparams(u=user.id, s=session_id, h=sha, d=doc_id)
        db.exec(link_ins)
        db.commit()

        duplicate = blob_exists
        log_event("upload_ok", {
            "user": user_email,
            "session_id": session_id,
            "sha256": sha,
            "storage_uri": storage_uri,
            "size_bytes": len(raw),
            "mime": mime,
            "ext": ext,
            "duplicate": duplicate,
            "chars_indexed": chars_indexed,
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
    except Exception as e:
        logging.exception("Upload failed")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
