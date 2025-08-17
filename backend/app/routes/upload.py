# app/routes/upload.py
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlmodel import Session, select
from pathlib import Path
import logging
import uuid

from app.db import get_session
from app.models import User, ChatSession
from app.deps.auth import get_current_user
from app.utils.logger import log_event
from app.vector_store import embed_and_store
from app.parsers.parser import parse_and_clean_bytes  # central parser (txt/md/pdf/docx/pptx/xlsx/csv/json/jpg/png)
from app.storage.storage import get_storage  # NEW

router = APIRouter(prefix="/api/v1", tags=["upload"])

ALLOWED_EXTS = {
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".txt", ".md", ".csv", ".json",
    ".jpg", ".jpeg", ".png",
}
MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB

def _safe_name(name: str) -> str:
    return Path(name or "upload").name[:200]

def _ext(name: str) -> str:
    return Path(name or "").suffix.lower()

@router.post("/upload")
async def upload_file(
    session_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """
    Upload a file, parse & sanitize, and embed into vector store with
    MINIMAL metadata (no filename). We keep session scoping + a random doc_id.
    """
    try:
        # 1) Auth
        user = db.exec(select(User).where(User.email == user_email)).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # 2) Session ownership
        chat = db.exec(
            select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id)
        ).first()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat session not found")

        # 3) Read & validate
        original_name = _safe_name(file.filename or "")
        if _ext(original_name) not in ALLOWED_EXTS:
            raise HTTPException(status_code=415, detail=f"Unsupported file extension: {_ext(original_name) or 'unknown'}")

        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Empty file")
        if len(raw) > MAX_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (> {MAX_SIZE_BYTES // (1024*1024)} MB)",
            )

        # 🔹 Persist original file to storage (opaque path, no name leaks)
        storage = get_storage()
        persisted_doc_id, storage_uri = storage.save(
            user_id=user.id,
            session_id=session_id,
            filename=original_name,  # only used to keep extension; NOT stored as-is
            data=raw,
        )

        # 4) Parse & sanitize (centralized)
        parsed = parse_and_clean_bytes(original_name, raw, getattr(file, "content_type", None))
        text = (parsed.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="No extractable text found.")

        # 5) Minimal metadata (NO filename)
        doc_id = str(uuid.uuid4())
        embed_and_store(
            user_email=user_email,
            text=text,
            metadata={
                "session_id": str(session_id),
                "doc_id": doc_id,
                # NO filename/path/PII in metadata
            },
        )

        log_event("upload", {
            "user": user_email,
            "session_id": session_id,
            "doc_id": doc_id,
            "storage_uri": storage_uri,          # internal locator (file:// or s3://)
            "size_bytes": len(raw),
            "content_type": getattr(file, "content_type", None),
            "chars_indexed": len(text),
        })

        return {
            "ok": True,
            "session_id": session_id,
            "doc_id": doc_id,           # opaque handle if you ever need it later
            "chars_indexed": len(text),
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Upload failed")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
