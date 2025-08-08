from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.db import get_session
from app.models import User,ChatSession,Upload
from app.deps.auth_dependency import get_current_user
from datetime import datetime

router = APIRouter(prefix="/api/v1/user", tags=["user"])

@router.get("/profile")
def get_profile(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        return { "error": "User not found" }

    files_uploaded = db.exec(
    select(Upload).where(Upload.user_email == user.email)
    ).count()

    chats_created = db.exec(
        select(ChatSession).where(ChatSession.user_email == user.email)
    ).count()

    return {
        "name": user.name or "Neura User",
        "email": user.email,
        "userId": f"usr_{user.id:04}",
        "plan": user.tier,
        "joinDate": user.created_at.strftime("%B %d, %Y") if user.created_at else "Unknown",
        "filesUploaded": files_uploaded,
        "chatsCreated": chats_created
    }
