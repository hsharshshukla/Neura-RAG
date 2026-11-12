# app/routes/chat_status.py
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlmodel import Session, func, select

from app.db import get_session
from app.deps.auth import get_current_user
from app.deps.chat_session import require_owned_chat_session
from app.deps.workspace import require_tkp_workspace_access
from app.integrations.tkp.config import get_tkp_settings
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
    chat = require_owned_chat_session(db, session_id=session_id, user_id=user.id)
    if (os.getenv("ORGANIZATIONAL_RAG_MODE", "legacy") or "legacy").lower() == "tkp":
        try:
            settings = get_tkp_settings()
        except ValidationError as exc:
            raise HTTPException(503, "Knowledge retrieval is not configured") from exc
        access = require_tkp_workspace_access(user=user, db=db, settings=settings)
        if chat.workspace_id != str(access.workspace_id):
            raise HTTPException(404, "Chat not found")

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
