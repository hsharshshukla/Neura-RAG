# app/routes/chat_status.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, func
from typing import Optional

from app.db import get_session
from app.models import ChatMessage

router = APIRouter(prefix="/api/v1/chat", tags=["chat-status"])

@router.get("/{session_id}/status")
def chat_status(session_id: int, since_id: Optional[int] = None, db: Session = Depends(get_session)):
    """
    Simple polling endpoint.
    Returns whether there's an assistant message after `since_id` (if provided),
    or whether the latest message is by 'assistant'.
    """
    if since_id is not None:
        newer = db.exec(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.session_id == session_id,
                ChatMessage.id > since_id,
                ChatMessage.role == "assistant",
            )
        ).one()
        return {"answered": newer > 0, "latest_id": since_id}

    last = db.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id.desc())
    ).first()
    if not last:
        return {"answered": False, "latest_id": None}
    return {"answered": last.role == "assistant", "latest_id": last.id}
