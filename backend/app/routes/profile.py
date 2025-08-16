# backend/app/routes/profile.py
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from sqlalchemy import func
from datetime import datetime

from app.db import get_session
from app.models import User, ChatSession, Upload
from app.deps.auth import get_current_user

router = APIRouter(prefix="/api/v1/user", tags=["user"])

def _count(db: Session, stmt):
    """Execute a COUNT(*) select and return an int safely across drivers."""
    row = db.exec(stmt).one()
    try:
        return int(row[0])  # Row/tuple
    except Exception:
        try:
            return int(row)  # scalar
        except Exception:
            return 0

@router.get("/profile")
def get_profile(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    files_uploaded = _count(
        db,
        select(func.count(Upload.id)).where(Upload.user_email == user.email)
    )
    chats_created = _count(
        db,
        select(func.count(ChatSession.id)).where(ChatSession.user_id == user.id)
    )

    join_dt = "Unknown"
    try:
        if user.created_at:
            join_dt = user.created_at.strftime("%B %d, %Y")
    except Exception:
        pass

    return {
        "name": user.name or "Neura User",
        "email": user.email,
        "userId": f"usr_{user.id:04}" if isinstance(user.id, int) else f"usr_{user.id}",
        "plan": user.tier,
        "joinDate": join_dt,
        "filesUploaded": files_uploaded,
        "chatsCreated": chats_created
    }

