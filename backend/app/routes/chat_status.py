# app/routes/chat_status.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from app.db import get_session
from app.deps.auth import get_current_user
from app.deps.chat_session import require_owned_chat_session
from app.models import ChatMessage, User

router = APIRouter(prefix="/api/v1/chat", tags=["chat-status"])


@router.get("/{session_id}/status")
def chat_status(
    session_id: int,
    since_id: int | None = None,
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Simple polling endpoint.
    Returns whether there's an assistant message after `since_id` (if provided),
    or whether the latest message is by 'assistant'.
    """
    user = db.exec(select(User).where(User.email == user_email)).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    require_owned_chat_session(db, session_id=session_id, user_id=user.id)

    if since_id is not None:
        newer = db.exec(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.session_id == session_id,
                ChatMessage.user_id == user.id,
                ChatMessage.id > since_id,
                ChatMessage.role == "assistant",
            )
        ).one()
        return {"answered": newer > 0, "latest_id": since_id}

    last = db.exec(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.user_id == user.id,
        )
        .order_by(ChatMessage.id.desc())
    ).first()
    if not last:
        return {"answered": False, "latest_id": None}
    return {"answered": last.role == "assistant", "latest_id": last.id}
