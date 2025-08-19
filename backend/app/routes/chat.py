# app/routes/chat.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlmodel import Session, select, func
from datetime import datetime, date
from app.db import get_session
from app.models import ChatSession, ChatMessage, User
from app.schemas import ChatSessionOut, ChatMessageOut
from app.deps.auth import get_current_user
from app.vector_store import query_user_docs
from app.utils.logger import log_event
import os
from textwrap import shorten
from openai import OpenAI
from app.prompting.product import infer_scope_products, make_system_prompt
from app.utils.redaction import redact_source_identity

from app.config import plan_limit, plan_model, is_session_scoped

STRICT_SCOPE = os.getenv("STRICT_OPENTEXT_SCOPE", "true").lower() == "true"
ANSWER_POLICY = os.getenv("NEURA_ANSWER_POLICY", "opentext_or_context").lower()

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatIn(BaseModel):
    message: str
    session_id: Optional[int] = None


class RenameIn(BaseModel):
    title: str


def _title_from_text(text: str) -> str:
    if not text:
        return "New Chat"
    s = " ".join(text.strip().split())
    return (s[:60] + "…") if len(s) > 60 else s


def _today_user_chat_count(db: Session, user_id: int) -> int:
    start = datetime.combine(date.today(), datetime.min.time())
    end = datetime.combine(date.today(), datetime.max.time())
    return db.exec(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.user_id == user_id,
            ChatMessage.role == "user",
            ChatMessage.created_at >= start,
            ChatMessage.created_at <= end,
        )
    ).one()


@router.get("/sessions", response_model=List[ChatSessionOut])
def get_sessions(
    user_email: str = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        return []
    return db.exec(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.created_at.desc())
    ).all()


@router.get("/{session_id}", response_model=List[ChatMessageOut])
def get_chat_messages(session_id: int, db: Session = Depends(get_session)):
    return db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
    ).all()


@router.patch("/{session_id}/title")
def rename_chat_session(
    session_id: int,
    payload: RenameIn,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    chat = db.exec(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        )
    ).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    new_title = (" ".join((payload.title or "").split()))[:80] or "Untitled"
    chat.title = new_title
    db.add(chat)
    db.commit()
    return {"ok": True, "title": new_title}


@router.post("")
def ask(
    payload: ChatIn,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    message = (payload.message or "").strip()
    session_id = payload.session_id

    # --- Auth / user ---
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # --- Quota check (per plan) ---
    limit = plan_limit(user.tier)
    if limit != -1:
        used = _today_user_chat_count(db, user.id)
        if used >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Daily chat limit reached for your plan ({limit}/day). Upgrade to Mini+ or Pro for unlimited.",
            )

    # --- Ensure a session exists ---
    if not session_id:
        new_session = ChatSession(
            user_id=user.id,
            title=_title_from_text(message),
            created_at=datetime.utcnow(),
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        session_id = new_session.id

    # --- Retrieval scope: Free/Mini = session-only, Pro = global
    if is_session_scoped(user.tier):
        filters = {"session_id": str(session_id)}
        filter_by_user = False
    else:
        filters = {}
        filter_by_user = True

    chunks = query_user_docs(
        user_email=user_email,
        question=message,
        top_k=6,
        filter_by_user=filter_by_user,
        extra_filters=filters,
    )

    def fmt_chunk(ch):
        body = getattr(ch, "page_content", "") or str(ch)
        body = redact_source_identity(body)
        return shorten(body, width=1200, placeholder="…")

    context_blocks = [c for c in (fmt_chunk(c) for c in chunks) if c]
    context_text = "\n\n---\n\n".join(context_blocks)[:12000]

    scope_hits_ctx = infer_scope_products(context_text)

    def context_relevant(q: str, ctx: str) -> bool:
        if not ctx or not q:
            return False
        import re
        q_tokens = re.findall(r"[A-Za-z0-9]{3,}", q.lower())
        stop = {
            "how", "what", "when", "where", "which", "please", "help", "issue", "error", "problem",
            "setup", "set", "configure", "configuration", "config", "steps", "guide", "doc", "docs",
        }
        q_terms = [t for t in q_tokens if len(t) >= 4 and t not in stop]
        if not q_terms:
            return False
        ctx_lc = ctx.lower()
        hits = sum(1 for t in q_terms if t in ctx_lc)
        return hits >= 1 and len(ctx) >= 200

    has_context = bool(context_text.strip()) and bool(scope_hits_ctx) and context_relevant(message, context_text)

    model_name = plan_model(user.tier)
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    grounded = False
    ai = ""

    if has_context:
        grounded = True
        system_prompt = make_system_prompt(grounded=True)
        user_prompt = (
            f"User question:\n{message}\n\n"
            f"Context excerpts (separated by ---):\n{context_text}"
        )
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                top_p=0.9,
                max_tokens=900,
            )
            ai = (completion.choices[0].message.content or "").strip()
        except Exception as e:
            ai = f"RAG call failed: {e}"
    else:
        if os.getenv("NEURA_ANSWER_POLICY", "opentext_or_context").lower() == "context_only":
            ai = (
                "I answer strictly from your uploaded OpenText materials. "
                "Please upload relevant documentation and ask again."
            )
        else:
            scope_hits_msg = infer_scope_products(message)
            in_scope = bool(scope_hits_msg or scope_hits_ctx)
            if in_scope:
                system_prompt = make_system_prompt(grounded=False)
                user_prompt = (
                    f"User question (OpenText-scoped):\n{message}\n\n"
                    f"Detected product(s), if any: {', '.join(scope_hits_msg) or 'None'}."
                )
                try:
                    completion = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.3,
                        top_p=0.9,
                        max_tokens=900,
                    )
                    ai = (completion.choices[0].message.content or "").strip()
                except Exception as e:
                    ai = f"Model call failed: {e}"
            else:
                ai = (
                    "I specialize strictly in OpenText platforms. "
                    "Please ask an OpenText question or upload relevant documentation."
                )

    # --- Persist messages
    now = datetime.utcnow()
    db.add(
        ChatMessage(
            session_id=session_id,
            user_id=user.id,
            role="user",
            content=message,
            created_at=now,
            # timestamp omitted -> DB/model default will fill
        )
    )
    db.add(
        ChatMessage(
            session_id=session_id,
            user_id=user.id,
            role="assistant",
            content=ai,
            created_at=now,
            # timestamp omitted -> DB/model default will fill
        )
    )
    db.commit()

    log_event(
        "chat",
        {
            "user": user_email,
            "tier": user.tier,
            "session_id": session_id,
            "question": message,
            "chunks_used": len(chunks),
            "grounded": grounded,
            "model": model_name,
            "policy": os.getenv("NEURA_ANSWER_POLICY", "opentext_or_context"),
            "ctx_present": bool(context_text),
            "scope": {"ctx": scope_hits_ctx},
        },
    )

    return {"response": ai, "session_id": session_id}
