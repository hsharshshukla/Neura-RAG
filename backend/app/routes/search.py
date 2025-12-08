# app/routes/search.py
from __future__ import annotations

import logging
import inspect
import os
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Request, Response

from sqlmodel import Session, select
from sqlalchemy import text
from datetime import datetime, timedelta

from app.db import get_session
from app.models import ChatSession, ChatMessage, User
from app.deps.auth import get_current_user
from app.vector_store import query_user_docs  # keep your existing import

# 🔒 SlowAPI (endpoint-level guard; plan-aware caps enforced in code)
from app.rate_limit import key_user_or_ip

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/v1", tags=["search"])


# ---------- tier helpers ----------
def _norm_tier(tier: str | None) -> str:
    """
    Normalize to two-tier world.
    - "pro"   -> "pro"
    - everything else ("base"/"free"/"mini"/None) -> "base"
    """
    return "pro" if (tier or "").strip().lower() == "pro" else "base"


# ---------- plan helpers ----------
def _geti(default: int, *env_names: str) -> int:
    for name in env_names:
        if not name:
            continue
        v = os.getenv(name, "").strip()
        if v.isdigit():
            return int(v)
    return default

def _plan_topk(plan_tier: str) -> int:
    """
    Per-request result cap (top_k / limit) by plan.
    Env (ints):
      - Pro : SEARCH_TOPK_PRO
    Default: Pro=12
    """
    if _norm_tier(plan_tier) == "pro":
        return _geti(12, "SEARCH_TOPK_PRO")
    # Base users cannot search; value unused
    return 0

def _plan_search_knobs(plan_tier: str) -> dict:
    """
    Per-plan RPM/RPH for search.
    Env:
      - Pro : SEARCH_RPM_PRO / SEARCH_RPH_PRO
    Defaults: Pro=60/1200
    """
    if _norm_tier(plan_tier) == "pro":
        return {
            "rpm": _geti(60, "SEARCH_RPM_PRO"),
            "rph": _geti(1200, "SEARCH_RPH_PRO"),
        }
    # Base users cannot search; values unused
    return {"rpm": 0, "rph": 0}


# ---------- db helpers ----------
def _ensure_tables(db: Session) -> None:
    """
    Creates a lightweight search_log table if it doesn't exist.
    (Independent from SQLModel metadata to keep this endpoint decoupled.)
    """
    db.exec(text("""
        CREATE TABLE IF NOT EXISTS public.search_log (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            q TEXT NOT NULL,
            session_id TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        );
    """))
    db.commit()

def _log_search(db: Session, user_id: int, q: str, session_id: Optional[str]) -> None:
    db.exec(text("""
        INSERT INTO public.search_log (user_id, q, session_id)
        VALUES (:u, :q, :s)
    """).bindparams(u=user_id, q=q[:1000], s=session_id))
    db.commit()

def _enforce_plan_search_rates(db: Session, user_id: int, plan_tier: str) -> None:
    """
    Enforce per-plan RPM / RPH using timestamps in search_log.
    Call this BEFORE executing the search, then record a row.
    """
    knobs = _plan_search_knobs(plan_tier)
    rpm, rph = knobs["rpm"], knobs["rph"]

    now = datetime.utcnow()
    one_min_ago = now - timedelta(minutes=1)
    one_hr_ago  = now - timedelta(hours=1)

    used_min = db.exec(text("""
        SELECT COUNT(1) FROM public.search_log
        WHERE user_id = :u AND created_at >= :t
    """).bindparams(u=user_id, t=one_min_ago)).one()

    if used_min >= rpm:
        raise HTTPException(status_code=429, detail=f"Per-minute search limit reached for your plan ({rpm}/minute). Try again soon.")

    used_hr = db.exec(text("""
        SELECT COUNT(1) FROM public.search_log
        WHERE user_id = :u AND created_at >= :t
    """).bindparams(u=user_id, t=one_hr_ago)).one()

    if used_hr >= rph:
        raise HTTPException(status_code=429, detail=f"Per-hour search limit reached for your plan ({rph}/hour). Please try later.")


# ---------- utility helpers ----------
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
    try:
        sig = inspect.signature(query_user_docs)
    except Exception:
        sig = None

    supports_filter_by = bool(sig and "filter_by" in sig.parameters)
    supports_filters = bool(sig and "filters" in sig.parameters)

    try_kwargs = dict(user_email=user_email, question=question, top_k=top_k)
    try:
        if supports_filter_by:
            return query_user_docs(**{**try_kwargs, "filter_by": py_filters}) or []
        if supports_filters:
            return query_user_docs(**{**try_kwargs, "filters": py_filters}) or []
        return query_user_docs(**try_kwargs) or []
    except TypeError:
        return query_user_docs(**try_kwargs) or []


@router.get("/search")
# @limiter.limit("40/minute; 600/hour", key_func=key_user_or_ip)  # SlowAPI requires request in signature
def global_search(
    request: Request,  # <-- required by SlowAPI
    response: Response,
    q: str = Query(..., min_length=2),
    session_id: Optional[str] = None,  # kept for signature bw-compat; unused for Pro
    plan: str = "Base",  # ignored for security; effective plan derived from user.tier
    limit: int = 10,
    current_user: Any = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> Dict[str, List[Dict[str, Any]]]:
    # Resolve user & enforce tier gating first
    user = _resolve_user(db, current_user)
    plan_tier = _norm_tier(getattr(user, "tier", None))
    if plan_tier != "pro":
        # Hard gate: Base has NO search feature
        raise HTTPException(status_code=403, detail="Search is available on Pro only.")

    try:
        _ensure_tables(db)

        # ---- Plan-based RPM/RPH (DB-backed)
        _enforce_plan_search_rates(db, user.id, plan_tier)

        # ---- Plan-based cap for per-request result size
        plan_cap = _plan_topk(plan_tier)
        limit = max(1, min(limit, plan_cap))

        q_like = f"%{q}%"

        # ---------- Pro: cross-chat search ----------
        chats: List[Dict[str, Any]] = []

        # Chat sessions by title
        title_col = _first_attr(ChatSession, ["title", "name"])
        chat_sel = select(ChatSession).where(ChatSession.user_id == user.id)
        if title_col is not None:
            chat_sel = chat_sel.where(title_col.ilike(q_like))
        chat_rows = db.exec(chat_sel.limit(limit)).all()

        # Messages (resilient columns)
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

        # Build chats payload
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

        # ---------- Pro: user-wide doc search (no session restriction) ----------
        py_filters: Dict[str, Any] = {"user_email": user.email}

        raw_docs: List[Any] = _call_query_user_docs(
            user_email=user.email,
            question=q,
            top_k=limit,          # <- plan-capped
            py_filters=py_filters,
        )

        # Post-filter to enforce ownership
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

            doc_items.append({
                "type": "doc",
                "filename": meta.get("filename") or meta.get("source") or "Document",
                "snippet": (text or "")[:160],
                "chat_id": meta.get("chat_id") or meta.get("session_id"),
                "id": meta.get("id") or meta.get("chunk_id") or meta.get("source"),
                "chunk_id": meta.get("chunk_id"),
                "session_id": meta.get("session_id"),
            })

        # Record the search after enforcement to count towards future windows
        try:
            _log_search(db, user.id, q, session_id)
        except Exception:
            # Never break user flow on logging failure
            logger.exception("search_log insert failed")

        # Sort chats by message recency proxy
        chats_sorted = sorted(chats, key=lambda x: x.get("message_id", 0), reverse=True)[:limit]
        return {"chats": chats_sorted, "docs": doc_items[:limit]}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail="Search failed. Check server logs.")


# # app/routes/search.py
# from __future__ import annotations

# import logging
# import inspect
# import os
# from typing import Dict, Any, List, Optional

# from fastapi import APIRouter, Depends, Query, HTTPException, Request, Response

# from sqlmodel import Session, select
# from sqlalchemy import text
# from datetime import datetime, timedelta

# from app.db import get_session
# from app.models import ChatSession, ChatMessage, User
# from app.deps.auth import get_current_user
# from app.vector_store import query_user_docs  # keep your existing import

# # 🔒 SlowAPI (endpoint-level guard; plan-aware caps enforced in code)
# from app.rate_limit import limiter, key_user_or_ip

# logger = logging.getLogger("uvicorn.error")
# router = APIRouter(prefix="/api/v1", tags=["search"])


# # ---------- plan helpers ----------
# def _plan_topk(plan_tier: str) -> int:
#     """
#     Per-request result cap (top_k / limit) by plan.
#     Env overrides (ints): SEARCH_TOPK_FREE, SEARCH_TOPK_MINI, SEARCH_TOPK_PRO
#     Defaults: Free=5, Mini+=8, Pro=12
#     """
#     p = (plan_tier or "free").strip().lower()
#     def geti(name: str, default: int) -> int:
#         v = os.getenv(name, "").strip()
#         return int(v) if v.isdigit() else default

#     if p == "pro":
#         return geti("SEARCH_TOPK_PRO", 12)
#     if "mini" in p:
#         return geti("SEARCH_TOPK_MINI", 8)
#     # treat "base" like "free" for caps
#     return geti("SEARCH_TOPK_FREE", 5)


# def _plan_search_knobs(plan_tier: str) -> dict:
#     """
#     Per-plan RPM/RPH for search.
#     Env overrides:
#       SEARCH_RPM_FREE, SEARCH_RPH_FREE
#       SEARCH_RPM_MINI, SEARCH_RPH_MINI
#       SEARCH_RPM_PRO,  SEARCH_RPH_PRO
#     Defaults: Free=20/300, Mini+=40/800, Pro=60/1200
#     """
#     p = (plan_tier or "free").strip().lower()
#     def geti(name: str, default: int) -> int:
#         v = os.getenv(name, "").strip()
#         return int(v) if v.isdigit() else default

#     if p == "pro":
#         return {"rpm": geti("SEARCH_RPM_PRO", 60), "rph": geti("SEARCH_RPH_PRO", 1200)}
#     if "mini" in p:
#         return {"rpm": geti("SEARCH_RPM_MINI", 40), "rph": geti("SEARCH_RPH_MINI", 800)}
#     # treat "base" like "free" for knobs
#     return {"rpm": geti("SEARCH_RPM_FREE", 20), "rph": geti("SEARCH_RPH_FREE", 300)}


# # ---------- db helpers ----------
# def _ensure_tables(db: Session) -> None:
#     """
#     Creates a lightweight search_log table if it doesn't exist.
#     (Independent from SQLModel metadata to keep this endpoint decoupled.)
#     """
#     db.exec(text("""
#         CREATE TABLE IF NOT EXISTS public.search_log (
#             id BIGSERIAL PRIMARY KEY,
#             user_id INTEGER NOT NULL,
#             q TEXT NOT NULL,
#             session_id TEXT,
#             created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
#         );
#     """))
#     db.commit()


# def _log_search(db: Session, user_id: int, q: str, session_id: Optional[str]) -> None:
#     db.exec(text("""
#         INSERT INTO public.search_log (user_id, q, session_id)
#         VALUES (:u, :q, :s)
#     """).bindparams(u=user_id, q=q[:1000], s=session_id))
#     db.commit()


# def _enforce_plan_search_rates(db: Session, user_id: int, plan_tier: str) -> None:
#     """
#     Enforce per-plan RPM / RPH using timestamps in search_log.
#     Call this BEFORE executing the search, then record a row.
#     """
#     knobs = _plan_search_knobs(plan_tier)
#     rpm, rph = knobs["rpm"], knobs["rph"]

#     now = datetime.utcnow()
#     one_min_ago = now - timedelta(minutes=1)
#     one_hr_ago  = now - timedelta(hours=1)

#     used_min = db.exec(text("""
#         SELECT COUNT(1) FROM public.search_log
#         WHERE user_id = :u AND created_at >= :t
#     """).bindparams(u=user_id, t=one_min_ago)).one()

#     if used_min >= rpm:
#         raise HTTPException(status_code=429, detail=f"Per-minute search limit reached for your plan ({rpm}/minute). Try again soon.")

#     used_hr = db.exec(text("""
#         SELECT COUNT(1) FROM public.search_log
#         WHERE user_id = :u AND created_at >= :t
#     """).bindparams(u=user_id, t=one_hr_ago)).one()

#     if used_hr >= rph:
#         raise HTTPException(status_code=429, detail=f"Per-hour search limit reached for your plan ({rph}/hour). Please try later.")


# # ---------- utility helpers (existing patterns) ----------
# def _resolve_user(db: Session, current_user: Any) -> User:
#     if isinstance(current_user, User):
#         return current_user
#     email = None
#     if isinstance(current_user, str):
#         email = current_user.strip()
#     elif isinstance(current_user, dict):
#         email = (current_user.get("email") or "").strip()
#     if not email:
#         raise HTTPException(status_code=401, detail="Invalid auth payload")
#     user = db.exec(select(User).where(User.email == email)).first()
#     if not user:
#         raise HTTPException(status_code=401, detail="User not found")
#     return user

# def _first_attr(model, names: List[str]):
#     for n in names:
#         if hasattr(model, n):
#             return getattr(model, n)
#     return None

# def _meta_get(meta: dict, keys: List[str]) -> Optional[str]:
#     for k in keys:
#         if k in meta and meta[k] is not None:
#             return str(meta[k])
#     return None

# def _call_query_user_docs(user_email: str, question: str, top_k: int, py_filters: Dict[str, Any]) -> List[Any]:
#     """
#     Call query_user_docs whether or not it supports filters.
#     - If it supports 'filter_by' or 'filters', pass them.
#     - Else call without and filter in Python.
#     """
#     try:
#         sig = inspect.signature(query_user_docs)
#     except Exception:
#         sig = None

#     supports_filter_by = bool(sig and "filter_by" in sig.parameters)
#     supports_filters = bool(sig and "filters" in sig.parameters)

#     try_kwargs = dict(user_email=user_email, question=question, top_k=top_k)
#     try:
#         if supports_filter_by:
#             return query_user_docs(**{**try_kwargs, "filter_by": py_filters}) or []
#         if supports_filters:
#             return query_user_docs(**{**try_kwargs, "filters": py_filters}) or []
#         return query_user_docs(**try_kwargs) or []
#     except TypeError:
#         return query_user_docs(**try_kwargs) or []


# @router.get("/search")
# @limiter.limit("40/minute; 600/hour", key_func=key_user_or_ip)  # SlowAPI requires request in signature
# def global_search(
#     request: Request,  # <-- required by SlowAPI
#     response: Response,
#     q: str = Query(..., min_length=2),
#     session_id: Optional[str] = None,
#     plan: str = "Free",  # ignored for security; effective plan derived from user.tier
#     limit: int = 10,
#     current_user: Any = Depends(get_current_user),
#     db: Session = Depends(get_session),
# ) -> Dict[str, List[Dict[str, Any]]]:
#     try:
#         _ensure_tables(db)

#         user = _resolve_user(db, current_user)

#         # 👇 Always derive effective plan from the actual user tier (ignore client param)
#         plan_tier = (getattr(user, "tier", None) or "free")
#         plan_tier_lc = plan_tier.lower()

#         # ---- Plan-based RPM/RPH (DB-backed)
#         _enforce_plan_search_rates(db, user.id, plan_tier)

#         # ---- Plan-based cap for per-request result size
#         plan_cap = _plan_topk(plan_tier)
#         limit = max(1, min(limit, plan_cap))

#         q_like = f"%{q}%"

#         # ---------- Pro-only: cross-chat search ----------
#         chats: List[Dict[str, Any]] = []
#         if plan_tier_lc == "pro":
#             # Chat sessions by title
#             title_col = _first_attr(ChatSession, ["title", "name"])
#             chat_sel = select(ChatSession).where(ChatSession.user_id == user.id)
#             if title_col is not None:
#                 chat_sel = chat_sel.where(title_col.ilike(q_like))
#             chat_rows = db.exec(chat_sel.limit(limit)).all()

#             # Messages (resilient columns)
#             fk_col = _first_attr(ChatMessage, ["chat_id", "session_id", "chat_session_id"])
#             content_col = _first_attr(ChatMessage, ["content", "message", "text", "body"])
#             order_col = _first_attr(ChatMessage, ["created_at", "timestamp", "id"])

#             msg_rows = []
#             if fk_col is not None and content_col is not None:
#                 msg_sel = (
#                     select(ChatMessage, ChatSession)
#                     .join(ChatSession, ChatSession.id == fk_col)
#                     .where(ChatSession.user_id == user.id)
#                     .where(content_col.ilike(q_like))
#                 )
#                 if order_col is not None:
#                     msg_sel = msg_sel.order_by(order_col.desc())
#                 msg_rows = db.exec(msg_sel.limit(limit)).all()

#             # Build chats payload
#             for ch in chat_rows:
#                 title = getattr(ch, "title", None) or getattr(ch, "name", "") or f"Chat {ch.id}"
#                 chats.append({
#                     "type": "chat",
#                     "chat_id": ch.id,
#                     "title": title,
#                     "preview": title,
#                     "id": ch.id,
#                 })

#             for msg, sess in msg_rows:
#                 preview = ""
#                 for cand in ("content", "message", "text", "body", "page_content"):
#                     preview = getattr(msg, cand, None) or preview
#                     if preview:
#                         break
#                 title = getattr(sess, "title", None) or getattr(sess, "name", "") or f"Chat {sess.id}"
#                 chats.append({
#                     "type": "message",
#                     "chat_id": sess.id,
#                     "title": title,
#                     "preview": (preview or "")[:160],
#                     "message_id": getattr(msg, "id", 0),
#                     "id": getattr(msg, "id", 0),
#                 })

#         # ---------- Docs via vector search ----------
#         # Lite tiers = session-scoped only. Treat "base" like free; include "mini".
#         is_lite = plan_tier_lc in {"free", "mini", "base"}

#         py_filters: Dict[str, Any] = {"user_email": user.email}
#         if is_lite:
#             # Require session_id for lite tiers; otherwise no docs
#             if session_id:
#                 py_filters["session_id"] = str(session_id)
#             else:
#                 # Record the search even when empty to enforce RPM/RPH windows
#                 try:
#                     _log_search(db, user.id, q, session_id)
#                 except Exception:
#                     logger.exception("search_log insert failed")
#                 chats_sorted = sorted(chats, key=lambda x: x.get("message_id", 0), reverse=True)[:limit]
#                 return {"chats": chats_sorted, "docs": []}

#         raw_docs: List[Any] = _call_query_user_docs(
#             user_email=user.email,
#             question=q,
#             top_k=limit,          # <- plan-capped
#             py_filters=py_filters,
#         )

#         # Post-filter results in Python to enforce ownership and session rules
#         want_session = str(session_id) if session_id else None
#         doc_items: List[Dict[str, Any]] = []
#         for d in raw_docs:
#             if isinstance(d, dict):
#                 meta = (d.get("metadata") or {})
#                 text = d.get("text") or d.get("content") or d.get("page_content") or ""
#             else:
#                 meta = getattr(d, "metadata", {}) or {}
#                 text = getattr(d, "page_content", "") or ""

#             meta_user = _meta_get(meta, ["user_email", "email", "owner", "user", "user_id"])
#             if meta_user and meta_user.lower() != user.email.lower():
#                 continue
#             meta_session = _meta_get(meta, ["session_id", "chat_id", "chat_session_id"])

#             if is_lite:
#                 # Lite: only docs for current session
#                 if not want_session or not meta_session or str(meta_session) != want_session:
#                     continue

#             doc_items.append({
#                 "type": "doc",
#                 "filename": meta.get("filename") or meta.get("source") or "Document",
#                 "snippet": (text or "")[:160],
#                 "chat_id": meta.get("chat_id") or meta.get("session_id"),
#                 "id": meta.get("id") or meta.get("chunk_id") or meta.get("source"),
#                 "chunk_id": meta.get("chunk_id"),
#                 "session_id": meta.get("session_id"),
#             })

#         # Record the search after enforcement to count towards future windows
#         try:
#             _log_search(db, user.id, q, session_id)
#         except Exception:
#             # Never break user flow on logging failure
#             logger.exception("search_log insert failed")

#         # Sort chats by message recency proxy (Pro only; otherwise it's already empty)
#         chats_sorted = sorted(chats, key=lambda x: x.get("message_id", 0), reverse=True)[:limit]
#         return {"chats": chats_sorted, "docs": doc_items[:limit]}

#     except HTTPException:
#         raise
#     except Exception:
#         logger.exception("Search failed")
#         raise HTTPException(status_code=500, detail="Search failed. Check server logs.")
