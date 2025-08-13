# app/routes/chat.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlmodel import Session, select
from datetime import datetime
from app.db import get_session
from app.models import ChatSession, ChatMessage, User
from app.schemas import ChatSessionOut, ChatMessageOut
from app.deps.auth import get_current_user
from app.vector_store import query_user_docs
from app.utils.logger import log_event
import os
import re
from textwrap import shorten
from openai import OpenAI
from app.prompting.product import infer_scope_products, make_system_prompt


STRICT_SCOPE = os.getenv("STRICT_OPENTEXT_SCOPE", "true").lower() == "true"
# NEURA_ANSWER_POLICY:
# - "opentext_or_context" (default): allow answers w/o context only if OpenText-scoped
# - "context_only": require context always; otherwise refuse (even if in-scope)
ANSWER_POLICY = os.getenv("NEURA_ANSWER_POLICY", "opentext_or_context").lower()


# 🔹 NEW import
from app.utils.redaction import redact_source_identity

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
    """Rename a chat session owned by the current user."""
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
    is_pro = (user.tier == "pro")

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

    # --- Retrieve chunks (free=session; pro=global) ---
    filters = {} if is_pro else {"session_id": str(session_id)}
    chunks = query_user_docs(
        user_email=user_email,
        question=message,
        top_k=6,
        filter_by_user=not is_pro,
        extra_filters=filters,
    )

    # --- Build redacted context (no filenames/owners/links) ---
    def fmt_chunk(ch):
        body = getattr(ch, "page_content", "") or str(ch)
        body = redact_source_identity(body)
        return shorten(body, width=1200, placeholder="…")

    context_blocks = [c for c in (fmt_chunk(c) for c in chunks) if c]
    context_text = "\n\n---\n\n".join(context_blocks)[:12000]

    # ✅ Detect OpenText cues in retrieved context
    scope_hits_ctx = infer_scope_products(context_text)

    # ✅ Simple relevance check — treat unrelated context as "no context"
    def context_relevant(q: str, ctx: str) -> bool:
        if not ctx or not q:
            return False
        # require at least one meaningful (>=4 chars, not generic) token overlap
        import re
        q_tokens = re.findall(r"[A-Za-z0-9]{3,}", q.lower())
        stop = {
            "how","what","when","where","which","please","help","issue","error","problem",
            "setup","set","configure","configuration","config","steps","guide","doc","docs"
        }
        q_terms = [t for t in q_tokens if len(t) >= 4 and t not in stop]
        if not q_terms:
            return False
        ctx_lc = ctx.lower()
        hits = sum(1 for t in q_terms if t in ctx_lc)
        # ignore trivially small contexts and weak overlaps
        return hits >= 1 and len(ctx) >= 200

    # ✅ Context counts only if it has OT cues AND is textually relevant
    has_context = bool(context_text.strip()) and bool(scope_hits_ctx) and context_relevant(message, context_text)

    # --- Policy & scope detection ---
    # Use your module-level ANSWER_POLICY loaded from .env
    scope_hits_msg = infer_scope_products(message)
    in_scope = bool(scope_hits_msg or scope_hits_ctx)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    grounded = False
    ai = ""

    if has_context:
        # ---------- RAG MODE: must use context ----------
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
        # ---------- NO CONTEXT (or irrelevant context) ----------
        if ANSWER_POLICY == "context_only":
            ai = (
                "I answer strictly from your uploaded OpenText materials. "
                "Please upload relevant OpenText documentation (product/version/config) and ask again."
            )
        else:
            # default: 'opentext_or_context'
            if in_scope:
                # Allowed: OpenText-scoped expert answer without context
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
                # Out-of-scope → professional refusal (no model call)
                ai = (
                    "Let’s keep it professional. I specialize strictly in OpenText platforms "
                    "(e.g., Extended ECM/Content Server, Documentum, Core Content, SAP ArchiveLink, "
                    "Aviator, SMAX, Fortify, etc.). I can’t help with this topic. "
                    "Please ask an OpenText question and include the product/version—or upload relevant "
                    "OpenText documentation—and I’ll provide concrete steps, checks, and pitfalls."
                )

    # --- Persist messages ---
    db.add(ChatMessage(session_id=session_id, role="user", content=message))
    db.add(ChatMessage(session_id=session_id, role="assistant", content=ai))
    db.commit()

    # --- Log ---
    log_event("chat", {
        "user": user_email,
        "session_id": session_id,
        "question": message,
        "chunks_used": len(chunks),
        "grounded": grounded,
        "model": model_name,
        "policy": ANSWER_POLICY,
        "scope": {"msg": scope_hits_msg, "ctx": scope_hits_ctx, "in_scope": in_scope},
        "ctx_relevant": has_context,
    })

    return {"response": ai, "session_id": session_id}


