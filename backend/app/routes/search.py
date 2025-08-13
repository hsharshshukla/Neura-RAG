# app/routes/search.py
import logging
import inspect
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import ChatSession, ChatMessage, User
from app.deps.auth import get_current_user
from app.vector_store import query_user_docs  # keep your existing import

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/v1", tags=["search"])

# ---------- helpers ----------
def _resolve_user(db: Session, current_user: Any) -> User:
    if isinstance(current_user, User):
        return current_user
    email = None
    if isinstance(current_user, str):
        email = current_user.strip()
    elif isinstance(current_user, dict):
        email = (current_user.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=401, detail="Invalid auth payload")
    user = db.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def _first_attr(model, names: List[str]):
    for n in names:
        if hasattr(model, n):
            return getattr(model, n)
    return None

def _meta_get(meta: dict, keys: List[str]) -> Optional[str]:
    for k in keys:
        if k in meta and meta[k] is not None:
            return str(meta[k])
    return None

def _call_query_user_docs(user_email: str, question: str, top_k: int, py_filters: Dict[str, Any]) -> List[Any]:
    """
    Call query_user_docs whether or not it supports filters.
    - If it supports 'filter_by' or 'filters', pass them.
    - Else call without and filter in Python.
    """
    sig = None
    try:
        sig = inspect.signature(query_user_docs)
    except Exception:
        sig = None

    supports_filter_by = False
    supports_filters = False
    if sig:
        params = sig.parameters
        supports_filter_by = "filter_by" in params
        supports_filters = "filters" in params

    try_kwargs = dict(user_email=user_email, question=question, top_k=top_k)
    try:
        if supports_filter_by:
            return query_user_docs(**{**try_kwargs, "filter_by": py_filters}) or []
        if supports_filters:
            return query_user_docs(**{**try_kwargs, "filters": py_filters}) or []
        # No filter support
        return query_user_docs(**try_kwargs) or []
    except TypeError:
        # Fallback if signature inspection lied
        return query_user_docs(**try_kwargs) or []

@router.get("/search")
def global_search(
    q: str = Query(..., min_length=2),
    session_id: Optional[str] = None,
    plan: str = "Free",
    limit: int = 10,
    current_user: Any = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> Dict[str, List[Dict[str, Any]]]:
    try:
        user = _resolve_user(db, current_user)
        q_like = f"%{q}%"

        # ------ Chat sessions by title
        title_col = _first_attr(ChatSession, ["title", "name"])
        chat_sel = select(ChatSession).where(ChatSession.user_id == user.id)
        if title_col is not None:
            chat_sel = chat_sel.where(title_col.ilike(q_like))
        chat_rows = db.exec(chat_sel.limit(limit)).all()

        # ------ Messages (resilient columns)
        fk_col = _first_attr(ChatMessage, ["chat_id", "session_id", "chat_session_id"])
        content_col = _first_attr(ChatMessage, ["content", "message", "text", "body"])
        order_col = _first_attr(ChatMessage, ["created_at", "timestamp", "id"])

        msg_rows = []
        if fk_col is not None and content_col is not None:
            msg_sel = (
                select(ChatMessage, ChatSession)
                .join(ChatSession, ChatSession.id == fk_col)
                .where(ChatSession.user_id == user.id)
                .where(content_col.ilike(q_like))
            )
            if order_col is not None:
                msg_sel = msg_sel.order_by(order_col.desc())
            msg_rows = db.exec(msg_sel.limit(limit)).all()

        # ------ Build chats payload
        chats: List[Dict[str, Any]] = []
        for ch in chat_rows:
            title = getattr(ch, "title", None) or getattr(ch, "name", "") or f"Chat {ch.id}"
            chats.append({
                "type": "chat",
                "chat_id": ch.id,
                "title": title,
                "preview": title,
                "id": ch.id,
            })

        for msg, sess in msg_rows:
            preview = ""
            for cand in ("content", "message", "text", "body", "page_content"):
                preview = getattr(msg, cand, None) or preview
                if preview:
                    break
            title = getattr(sess, "title", None) or getattr(sess, "name", "") or f"Chat {sess.id}"
            chats.append({
                "type": "message",
                "chat_id": sess.id,
                "title": title,
                "preview": (preview or "")[:160],
                "message_id": getattr(msg, "id", 0),
                "id": getattr(msg, "id", 0),
            })

        # ------ Docs via vector search (dynamic-filter support)
        is_free = (plan or "").lower().startswith("free")
        py_filters: Dict[str, Any] = {"user_email": user.email}
        if is_free and session_id:
            py_filters["session_id"] = str(session_id)

        raw_docs: List[Any] = _call_query_user_docs(
            user_email=user.email,
            question=q,
            top_k=limit,
            py_filters=py_filters,
        )

        # Post-filter results in Python to enforce ownership and session rules
        want_session = str(session_id) if session_id else None
        doc_items: List[Dict[str, Any]] = []
        for d in raw_docs:
            if isinstance(d, dict):
                meta = (d.get("metadata") or {})
                text = d.get("text") or d.get("content") or d.get("page_content") or ""
            else:
                meta = getattr(d, "metadata", {}) or {}
                text = getattr(d, "page_content", "") or ""

            meta_user = _meta_get(meta, ["user_email", "email", "owner", "user", "user_id"])
            if meta_user and meta_user.lower() != user.email.lower():
                continue
            meta_session = _meta_get(meta, ["session_id", "chat_id", "chat_session_id"])

            if is_free:
                # Free: only docs for current session
                if not want_session or not meta_session or str(meta_session) != want_session:
                    continue

            doc_items.append({
                "type": "doc",
                "filename": meta.get("filename") or meta.get("source") or "Document",
                "snippet": (text or "")[:160],
                "chat_id": meta.get("chat_id") or meta.get("session_id"),
                "id": meta.get("id") or meta.get("chunk_id") or meta.get("source"),
                "chunk_id": meta.get("chunk_id"),
                "session_id": meta.get("session_id"),
            })

        # sort chats by message recency proxy
        chats_sorted = sorted(chats, key=lambda x: x.get("message_id", 0), reverse=True)[:limit]
        return {"chats": chats_sorted, "docs": doc_items[:limit]}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail="Search failed. Check server logs.")
