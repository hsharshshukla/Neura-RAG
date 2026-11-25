# app/routes/upload.py

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
import io
import os

from app.db import get_session
from app.models import User, ChatSession
from app.deps.auth import get_current_user
from app.deps.chat_session import require_owned_chat_session
from app.deps.workspace import require_tkp_workspace_access
from app.integrations.tkp.config import get_tkp_settings
from app.services.conversation_attachments import attachment_document_id
from app.utils.logger import log_event
from app.vector_store import embed_and_store
from app.parsers.parser import parse_and_clean_bytes
from app.storage.storage import get_storage
from app.rate_limit import key_user_or_ip, limiter

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
    """Compatibility hook; Alembic release migrations own all upload tables."""
    return None


def _require_attachment_session(
    db: Session, *, user: User, session_id: int | None
) -> ChatSession:
    if user.id is None or session_id is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat = require_owned_chat_session(db, session_id=session_id, user_id=user.id)
    if os.getenv("ORGANIZATIONAL_RAG_MODE", "legacy").lower() == "tkp":
        try:
            access = require_tkp_workspace_access(
                user=user,
                db=db,
                settings=get_tkp_settings(),
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, "Knowledge retrieval is not configured") from exc
        if chat.workspace_id != str(access.workspace_id):
            raise HTTPException(status_code=404, detail="Chat not found")
    return chat


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
    """Check a conversation attachment after authorizing its owning session."""
    _ensure_tables(db)
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    _require_attachment_session(db, user=user, session_id=session_id)

    knobs = _plan_upload_knobs(user.tier or "free")
    max_mb = min(knobs["max_mb"], GLOBAL_MAX_UPLOAD_MB)
    max_bytes = max_mb * 1024 * 1024

    if size > max_bytes:
        raise HTTPException(status_code=413, detail=f"Max {max_mb} MB for your plan")

    link = db.exec(text("""
        SELECT 1 FROM public.upload_link
        WHERE user_id = :u AND session_id = :s AND sha256 = :h AND doc_id = :d
    """).bindparams(
        u=user.id, s=session_id, h=sha256,
        d=attachment_document_id(user.id, session_id, sha256),
    )).first()
    linked = bool(link)

    return {
        # These fields intentionally describe only this authorized conversation.
        # Global blob existence is an internal storage concern and must not be
        # disclosed or cause the frontend to skip logical attachment/indexing.
        "exists": linked,
        "duplicate": linked,
        "linked": linked,
        "max_bytes": max_bytes,
        "max_mb": max_mb,
    }

@router.post("/upload", response_model=None)
@limiter.limit("6/minute;60/hour")
async def upload_file(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    session_id: Optional[int] = Form(None),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """Upload, index, and link a local conversation attachment."""
    try:
        return await _upload_conversation_attachment(
            request=request,
            file=file,
            session_id=session_id,
            db=db,
            user_email=user_email,
        )
    finally:
        await file.close()


async def _upload_conversation_attachment(
    *,
    request: Request,
    file: UploadFile,
    session_id: int | None,
    db: Session,
    user_email: str,
):
    _ensure_tables(db)

    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    chat = _require_attachment_session(db, user=user, session_id=session_id)
    if user.id is None or chat.id is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    session_id = chat.id

    tier = user.tier or "free"
    knobs = _plan_upload_knobs(tier)
    effective_max_mb = min(knobs["max_mb"], GLOBAL_MAX_UPLOAD_MB)
    effective_max_bytes = effective_max_mb * 1024 * 1024

    _enforce_plan_upload_rates(db, user.id, tier)
    _enforce_plan_daily_count(db, user.id, tier)

    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > effective_max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large (> {effective_max_mb} MB)",
                )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid content length") from None

    original_name = Path(file.filename or "").name[:200] or "upload"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {ext or 'unknown'}")

    mime = getattr(file, "content_type", "") or ""
    sha = hashlib.sha256()
    size = 0
    data_stream = io.BytesIO()
    CHUNK = 1024 * 1024
    try:
        while True:
            chunk = await file.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > effective_max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large (> {effective_max_mb} MB)",
                )
            sha.update(chunk)
            data_stream.write(chunk)

        if size == 0:
            raise HTTPException(status_code=400, detail="Empty file")

        sha_hex = sha.hexdigest()
        doc_id = attachment_document_id(user.id, session_id, sha_hex)
        # Serialize physical blob reuse and logical indexing across all workers.
        lock_key = int.from_bytes(bytes.fromhex(sha_hex[:16]), "big", signed=True)
        db.exec(text("SELECT pg_advisory_xact_lock(:key)").bindparams(key=lock_key))
        linked = db.exec(text("""
            SELECT doc_id FROM public.upload_link
            WHERE user_id = :u AND session_id = :s AND sha256 = :h
        """).bindparams(u=user.id, s=session_id, h=sha_hex)).first()
        if linked and linked[0] == doc_id:
            existing_doc_id = linked[0] if not hasattr(linked, "doc_id") else linked.doc_id
            db.rollback()
            return {
                "ok": True,
                "duplicate": True,
                "session_id": session_id,
                "doc_id": str(existing_doc_id),
                "chars_indexed": 0,
            }

        try:
            data_stream.seek(0)
            raw = data_stream.read()
            try:
                parsed = parse_and_clean_bytes(original_name, raw, mime)
            except TypeError:
                parsed = parse_and_clean_bytes(original_name, raw)
            text_content = (
                parsed.get("text") if isinstance(parsed, dict) else parsed or ""
            ).strip()
        except Exception as exc:
            logger.exception("Parsing failed for %s", original_name)
            raise HTTPException(
                status_code=422,
                detail="File content could not be parsed",
            ) from exc

        if not text_content:
            log_event("upload_nontext", {
                "user": user_email, "session_id": session_id,
                "sha256": sha_hex, "size_bytes": size, "mime": mime, "ext": ext,
            })
            raise HTTPException(status_code=422, detail="No indexable content found")

        if os.getenv("DISABLE_EMBED", "").lower() in ("1", "true", "yes"):
            raise HTTPException(status_code=503, detail="Attachment indexing is disabled")

        try:
            embed_and_store(
                user_email=user_email,
                text=text_content,
                metadata={
                    "attachment_kind": "conversation_attachment",
                    "user_id": str(user.id),
                    "user_email": user_email,
                    "session_id": str(session_id),
                    "filename": original_name,
                    "sha256": sha_hex,
                    "doc_id": doc_id,
                },
                replace_existing=True,
            )
            chars_indexed = len(text_content)
        except Exception as exc:
            logger.exception("Embedding failed for %s", original_name)
            raise HTTPException(status_code=500, detail="Embedding error") from exc

        blob_row = db.exec(text("""
            SELECT sha256, bytes, storage_uri FROM public.blob WHERE sha256 = :h
        """).bindparams(h=sha_hex)).mappings().first()
        blob_exists = bool(blob_row)
        if blob_row and blob_row["bytes"] != size:
            raise HTTPException(status_code=500, detail="Storage integrity error")

        storage = None
        new_storage_uri = None
        commit_started = False
        try:
            if not blob_exists:
                storage = get_storage()
                try:
                    data_stream.seek(0)
                    _, new_storage_uri = storage.save_stream(
                        user_id=user.id,
                        session_id=session_id,
                        filename=original_name,
                        stream=data_stream,
                        mime=mime,
                    )
                except Exception as exc:
                    logger.exception("Storage save failed")
                    raise HTTPException(status_code=500, detail="Storage error") from exc
                db.exec(text("""
                    INSERT INTO public.blob (sha256, bytes, ext, mime, storage_uri)
                    VALUES (:h, :b, :e, :m, :u)
                """).bindparams(h=sha_hex, b=size, e=ext, m=mime, u=new_storage_uri))

            db.exec(text("""
                INSERT INTO public.embedding_index (sha256, store_key, chunks)
                VALUES (:h, :k, :c)
                ON CONFLICT (sha256) DO NOTHING
            """).bindparams(h=sha_hex, k=doc_id, c=None))
            db.exec(text("""
                INSERT INTO public.upload_link (user_id, session_id, sha256, doc_id)
                VALUES (:u, :s, :h, :d)
                ON CONFLICT (user_id, session_id, sha256)
                DO UPDATE SET doc_id = EXCLUDED.doc_id
            """).bindparams(u=user.id, s=session_id, h=sha_hex, d=doc_id))
            commit_started = True
            db.commit()
        except Exception:
            # A failed commit may have succeeded remotely, so never delete its blob.
            if new_storage_uri and storage is not None and not commit_started:
                try:
                    storage.delete(new_storage_uri)
                except Exception:
                    logger.exception("Could not remove uncommitted attachment blob")
            elif new_storage_uri and commit_started:
                logger.warning("Attachment blob may require reconciliation after commit failure")
            db.rollback()
            raise

        log_event("upload_ok", {
            "user": user_email, "session_id": session_id,
            "sha256": sha_hex,
            "size_bytes": size, "mime": mime, "ext": ext,
            "storage_reused": blob_exists, "chars_indexed": chars_indexed, "plan": tier,
        })

        return {
            "ok": True,
            # A newly completed logical attachment is never a duplicate, even
            # when its immutable bytes reused an existing physical blob.
            "duplicate": False,
            "session_id": session_id,
            "doc_id": doc_id,
            "chars_indexed": int(chars_indexed),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        data_stream.close()

