from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import ChatSession


def require_owned_chat_session(db: Session, *, session_id: int, user_id: int) -> ChatSession:
    session = db.exec(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
    ).first()
    if session is None:
        # Use the same response for absent and foreign sessions to prevent enumeration.
        raise HTTPException(status_code=404, detail="Chat not found")
    return session
