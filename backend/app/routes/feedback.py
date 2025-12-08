# app/routes/feedback.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlmodel import Session

from app.db import get_session
from app.deps.auth import get_current_user

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

class FeedbackIn(BaseModel):
    session_id: int                     # your ChatSession.id (INT)
    message_index: Optional[int] = None # if omitted, we target the most recent event
    thumb: Optional[int] = None         # -1, 0, +1
    csat: Optional[int] = None          # 1..5
    comment: Optional[str] = None

    @field_validator("thumb")
    @classmethod
    def _thumb_range(cls, v):
        if v is None: return v
        if v not in (-1, 0, 1):
            raise ValueError("thumb must be -1, 0, or 1")
        return v

    @field_validator("csat")
    @classmethod
    def _csat_range(cls, v):
        if v is None: return v
        if not (1 <= v <= 5):
            raise ValueError("csat must be between 1 and 5")
        return v

def _now_utc():
    return datetime.now(timezone.utc)

@router.post("")
def submit_feedback(
    payload: FeedbackIn,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    """
    Upserts feedback into chat_event for the user's session:
      - If message_index is provided, update that specific event row.
      - Else, update the most recent event for the session.
    Notes:
      - chat_event.user_id in your schema should match your users table type.
      - chat_event.chat_session_id is a UUID derived from session_id; we recompute it here.
    """
    # Resolve user_id (we only need it for scoping the update)
    user_row = db.exec(text("SELECT id FROM \"user\" WHERE email = :email LIMIT 1"), {"email": user_email}).first()
    if not user_row:
        raise HTTPException(401, "User not found")
    user_id = user_row[0]

    # Deterministic UUID mapping for analytics chat_session_id
    # Must match the mapping used in chat.py
    from uuid import uuid5, NAMESPACE_URL
    chat_session_uuid = uuid5(NAMESPACE_URL, f"chat-session:{payload.session_id}")

    # Build dynamic SETs and params
    sets = []
    params: Dict[str, Any] = {
        "user_id": str(user_id) if isinstance(user_id, str) else user_id,
        "chat_session_id": str(chat_session_uuid),
    }
    if payload.thumb is not None:
        sets.append("thumb = :thumb")
        params["thumb"] = payload.thumb
    if payload.csat is not None:
        sets.append("csat = :csat")
        params["csat"] = payload.csat
    if payload.comment is not None:
        sets.append("feedback_comment = :comment")
        params["comment"] = payload.comment.strip()

    if not sets:
        raise HTTPException(400, "Nothing to update (provide thumb, csat, or comment)")

    where = ["user_id = :user_id", "chat_session_id = :chat_session_id"]
    if payload.message_index is not None:
        where.append("message_index = :message_index")
        params["message_index"] = payload.message_index

    # If message_index is omitted, target the latest event in the session
    sql = text(f"""
        WITH target AS (
          SELECT event_id
          FROM chat_event
          WHERE {" AND ".join(where)}
          ORDER BY ts DESC
          LIMIT 1
        )
        UPDATE chat_event ce
        SET {", ".join(sets)}
        FROM target
        WHERE ce.event_id = target.event_id
        RETURNING ce.event_id::text AS event_id, ce.message_index, ce.thumb, ce.csat, ce.feedback_comment
    """)

    row = db.exec(sql, params).first()
    if not row:
        raise HTTPException(404, "No chat event found for this user/session")

    db.commit()
    return {"ok": True, **dict(row._mapping)}
