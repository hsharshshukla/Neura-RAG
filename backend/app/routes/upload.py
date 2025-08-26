# app/routes/upload.py
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from sqlmodel import Session, select
from sqlalchemy import text
from pathlib import Path
from datetime import datetime
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

router = APIRouter(prefix="/api/v1", tags=["upload"])
logger = logging.getLogger("uvicorn.error")

ALLOWED_EXTS = {
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".txt", ".md", ".csv", ".json",
    ".jpg", ".jpeg", ".png",
}

# Use env so backend & frontend can match limits
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_SIZE_BYTES = MAX_UPLOAD_MB * 1024 * 1024


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
    Frontend probe to skip re-uploads and preflight size.
    Returns duplicate/existence and 413 if the file exceeds MAX_UPLOAD_MB.
    """
    # Size preflight: fail fast so the UI never tries to upload too-large files
    if size > MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail=f"Max {MAX_UPLOAD_MB} MB")

    _ensure_tables(db)

    # Ensure user exists (tenant guard)
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

    return {
        "exists": exists,
        "duplicate": exists,
        "linked": has_link,
        "max_bytes": MAX_SIZE_BYTES,     # optional: handy for UI
        "max_mb": MAX_UPLOAD_MB,
    }


@router.post("/upload")
async def upload_file(
    request: Request,                         # <-- add Request for early header check
    session_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """
    Stores content only once by sha256; links content to user+session.
    Response: { ok, duplicate, session_id, doc_id, chars_indexed }
    Streaming implementation to avoid 413/memory blow-ups:
      - optional header pre-check (Content-Length)
      - chunked read with hard cap
      - compute sha256 while streaming
      - write to temp file, then pass bytes to storage/parser
    """
    # --- unified limits (env override) ---
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
    MAX_SIZE_BYTES = MAX_UPLOAD_MB * 1024 * 1024
    CHUNK = 1024 * 1024  # 1 MB chunks

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

        # 3) Validate headers and extension
        # Early reject if client told us it's too big
        cl = request.headers.get("content-length")
        if cl and int(cl) > MAX_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"File too large (> {MAX_UPLOAD_MB} MB)")

        original_name = _safe_name(file.filename or "")
        ext = _ext(original_name)
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
                    if size > MAX_SIZE_BYTES:
                        raise HTTPException(status_code=413, detail=f"File too large (> {MAX_UPLOAD_MB} MB)")
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

        # 6) If blob missing: persist file once (prefer stream/path if supported)
        if not blob_exists:
            storage = get_storage()
            try:
                if hasattr(storage, "save_file"):
                    # custom API: save by local file path (if your storage supports it)
                    _, storage_uri = storage.save_file(
                        user_id=user.id,
                        session_id=session_id,
                        filename=original_name,
                        path=str(tmp_path),
                        mime=mime,
                    )
                elif hasattr(storage, "save_stream"):
                    # custom API: save by stream
                    with tmp_path.open("rb") as f:
                        _, storage_uri = storage.save_stream(
                            user_id=user.id,
                            session_id=session_id,
                            filename=original_name,
                            stream=f,
                            mime=mime,
                        )
                elif hasattr(storage, "save_bytes"):
                    # fallback: bytes (loads once into memory)
                    data = tmp_path.read_bytes()
                    _, storage_uri = storage.save_bytes(
                        user_id=user.id,
                        session_id=session_id,
                        filename=original_name,
                        data=data,
                    )
                else:
                    # legacy: save(bytes=...)
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
        emb_sel = text(
            "SELECT 1 FROM public.embedding_index WHERE sha256 = :h"
        ).bindparams(h=sha_hex)
        embedded = db.exec(emb_sel).first()

        chars_indexed = 0
        if not embedded:
            # Parse text from the temp file (read once; consider streaming parser later)
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


# @router.post("/upload")
# async def upload_file(
#     session_id: int = Form(...),
#     file: UploadFile = File(...),
#     db: Session = Depends(get_session),
#     user_email: str = Depends(get_current_user),
# ):
#     """
#     Stores content only once by sha256; links content to user+session.
#     Response: { ok, duplicate, session_id, doc_id, chars_indexed }
#     """
#     try:
#         _ensure_tables(db)

#         # 1) Auth
#         user = db.exec(select(User).where(User.email == user_email)).first()
#         if not user:
#             raise HTTPException(status_code=401, detail="User not found")

#         # 2) Session ownership
#         chat = db.exec(
#             select(ChatSession).where(
#                 ChatSession.id == session_id,
#                 ChatSession.user_id == user.id,
#             )
#         ).first()
#         if not chat:
#             raise HTTPException(status_code=404, detail="Chat session not found")

#         # 3) Read & validate
#         original_name = _safe_name(file.filename or "")
#         ext = _ext(original_name)
#         if ext not in ALLOWED_EXTS:
#             raise HTTPException(status_code=415, detail=f"Unsupported file extension: {ext or 'unknown'}")

#         raw = await file.read()
#         if not raw:
#             raise HTTPException(status_code=400, detail="Empty file")
#         if len(raw) > MAX_SIZE_BYTES:
#             raise HTTPException(
#                 status_code=413,
#                 detail=f"File too large (> {MAX_SIZE_BYTES // (1024*1024)} MB)",
#             )

#         sha = _sha256(raw)
#         mime = getattr(file, "content_type", None) or ""

#         # 4) Check for existing blob
#         blob_sel = text(
#             "SELECT sha256, storage_uri FROM public.blob WHERE sha256 = :h"
#         ).bindparams(h=sha)
#         blob_row = db.exec(blob_sel).mappings().first()

#         blob_exists = bool(blob_row)
#         storage_uri = blob_row["storage_uri"] if blob_row else None

#         # 5) If blob missing: persist file once (support save_bytes or save)
#         if not blob_exists:
#             storage = get_storage()
#             try:
#                 if hasattr(storage, "save_bytes"):
#                     _, storage_uri = storage.save_bytes(
#                         user_id=user.id,
#                         session_id=session_id,
#                         filename=original_name,
#                         data=raw,
#                     )
#                 else:
#                     _, storage_uri = storage.save(
#                         user_id=user.id,
#                         session_id=session_id,
#                         filename=original_name,
#                         data=raw,
#                     )
#             except Exception:
#                 logger.exception("Storage save failed for %s", original_name)
#                 raise HTTPException(status_code=500, detail="Upload failed: storage error")

#             blob_ins = text("""
#                 INSERT INTO public.blob (sha256, bytes, ext, mime, storage_uri)
#                 VALUES (:h, :b, :e, :m, :u)
#                 ON CONFLICT (sha256) DO NOTHING
#             """).bindparams(h=sha, b=len(raw), e=ext, m=mime, u=storage_uri)
#             db.exec(blob_ins)
#             db.commit()

#         # 6) Ensure embeddings exist for this blob (only once per sha256)
#         emb_sel = text(
#             "SELECT 1 FROM public.embedding_index WHERE sha256 = :h"
#         ).bindparams(h=sha)
#         embedded = db.exec(emb_sel).first()

#         chars_indexed = 0
#         if not embedded:
#             # ---- tolerant parser call: 2-arg vs 3-arg and dict vs string
#             try:
#                 try:
#                     parsed = parse_and_clean_bytes(original_name, raw, mime)
#                 except TypeError:
#                     parsed = parse_and_clean_bytes(original_name, raw)

#                 if isinstance(parsed, dict):
#                     text_content = (parsed.get("text") or "").strip()
#                 else:
#                     text_content = (parsed or "").strip()
#             except Exception:
#                 logger.exception("Parsing failed for %s", original_name)
#                 # Treat as non-text; proceed without embeddings
#                 text_content = ""

#             # ---- Optional: allow skipping embeddings via env
#             if os.getenv("DISABLE_EMBED", "").lower() in ("1", "true", "yes"):
#                 logger.info("[upload] Skipping embed_and_store due to DISABLE_EMBED=1")
#             else:
#                 if text_content:
#                     try:
#                         embed_and_store(
#                             user_email=user_email,
#                             text=text_content,
#                             metadata={"sha256": sha, "session_id": str(session_id), "doc_id": sha},
#                         )
#                         chars_indexed = len(text_content)
#                     except Exception:
#                         logger.exception("Embedding/index failed for %s", original_name)
#                         raise HTTPException(status_code=500, detail="Upload failed: embedding error")
#                 else:
#                     log_event("upload_nontext", {
#                         "user": user_email, "session_id": session_id, "sha256": sha,
#                         "size_bytes": len(raw), "mime": mime, "ext": ext
#                     })

#             emb_ins = text("""
#                 INSERT INTO public.embedding_index (sha256, store_key, chunks)
#                 VALUES (:h, :k, :c)
#                 ON CONFLICT (sha256) DO NOTHING
#             """).bindparams(h=sha, k=sha, c=None)
#             db.exec(emb_ins)
#             db.commit()

#         # 7) Create (or keep) the per-user, per-session link to the blob
#         doc_id = str(uuid.uuid4())
#         link_ins = text("""
#             INSERT INTO public.upload_link (user_id, session_id, sha256, doc_id)
#             VALUES (:u, :s, :h, :d)
#             ON CONFLICT (user_id, session_id, sha256) DO NOTHING
#         """).bindparams(u=user.id, s=session_id, h=sha, d=doc_id)
#         db.exec(link_ins)
#         db.commit()

#         duplicate = blob_exists
#         log_event("upload_ok", {
#             "user": user_email,
#             "session_id": session_id,
#             "sha256": sha,
#             "storage_uri": storage_uri,
#             "size_bytes": len(raw),
#             "mime": mime,
#             "ext": ext,
#             "duplicate": duplicate,
#             "chars_indexed": chars_indexed,
#         })

#         return {
#             "ok": True,
#             "duplicate": bool(duplicate),
#             "session_id": session_id,
#             "doc_id": doc_id,
#             "chars_indexed": int(chars_indexed),
#         }

#     except HTTPException:
#         raise
#     except Exception:
#         logger.exception("Upload pipeline failed for %s", getattr(file, "filename", "<unknown>"))
#         raise HTTPException(status_code=500, detail="Upload failed: server error")
