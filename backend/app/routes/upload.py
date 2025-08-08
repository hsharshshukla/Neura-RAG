# upload.py — Handles file uploads, parsing, sanitization, and vector embedding
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlmodel import Session, select
from app.db import get_session
from app.models import Upload, User
from app.deps.auth_dependency import get_current_user
from app.parsers.parser import parse_and_clean_file
from app.vector_store import embed_and_store
from app.utils.logger import log_event
from datetime import datetime

router = APIRouter(prefix="/api/v1/upload", tags=["upload"])

@router.get("/history")
def get_uploads(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    return db.query(Upload).filter(
        Upload.user_email == user_email
    ).order_by(Upload.created_at.desc()).all()

@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    # ✅ Parse and sanitize
    parsed = await parse_and_clean_file(file)
    text = parsed["text"]
    filetype = parsed["filetype"]

    # 📦 Get user tier from DB
    user = db.exec(select(User).where(User.email == user_email)).first()
    tier = user.tier if user else "free"

    # 📝 Track upload
    new_upload = Upload(
        filename=file.filename,
        filetype=filetype,
        user_email=user_email,
        created_at=datetime.utcnow()
    )
    db.add(new_upload)
    db.commit()
    db.refresh(new_upload)

    # 🧠 Embed with rich metadata, including session-scoped filtering
    embed_and_store(
        user_email=user_email,
        text=text,
        metadata={
            "user_email": user_email,
            "filename": file.filename,
            "filetype": filetype,
            "tier": tier,
            "visibility": "private",
            "session_id": session_id
        }
    )

    # 📊 Log upload event
    log_event("upload", {
        "user": user_email,
        "session_id": session_id,
        "filename": file.filename,
        "filetype": filetype,
        "size": len(text)
    })

    return {
        "upload_id": new_upload.id,
        "filename": new_upload.filename,
        "filetype": new_upload.filetype,
        "text": text
    }
