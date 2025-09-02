# app/routes/chat.py
from __future__ import annotations

import os, time
from textwrap import shorten
from typing import Optional, List, Tuple, Any, Dict
from datetime import datetime, date, timedelta
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlmodel import Session, select, func
from openai import OpenAI

from app.db import get_session
from app.models import ChatSession, ChatMessage, User
from app.schemas import ChatSessionOut, ChatMessageOut
from app.deps.auth import get_current_user
from app.vector_store import query_user_docs
from app.utils.logger import log_event
from app.prompting.product import infer_scope_products, make_system_prompt
from app.utils.redaction import redact_source_identity

# Plan config & helpers
from app.config.plan_policy import (
    plan_limit,
    plan_model,
    is_session_scoped,
    monthly_token_limit_for,
    monthly_tokens_used,
)

# Optional: log LLM usage for analytics/costing
from app.utils.llm_logger import log_llm_event

# 🔒 Rate limiting utilities
from app.rate_limit import limiter, key_user_or_ip

STRICT_SCOPE = os.getenv("STRICT_OPENTEXT_SCOPE", "true").lower() == "true"
ANSWER_POLICY = os.getenv("NEURA_ANSWER_POLICY", "opentext_or_context").lower()

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


# -----------------------------
# Models (kept for compatibility/docs elsewhere if needed)
# -----------------------------
class ChatIn(BaseModel):
    message: str
    session_id: Optional[int] = None


class RenameIn(BaseModel):
    title: str


# ✅ Make Pydantic resolve models when using future annotations
ChatIn.model_rebuild()
RenameIn.model_rebuild()


# -----------------------------
# Helpers
# -----------------------------
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


def _plan_rate_windows_for(tier: str) -> Tuple[int, int]:
    """
    Return (per_minute, per_hour) request caps for the user's plan.
    These stack with router-level SlowAPI limits.
    Override via env: PLAN_CHAT_RPM_FREE/MINI/PRO and PLAN_CHAT_RPH_*.
    """
    t = (tier or "").strip().lower()
    env_min = os.getenv("PLAN_CHAT_RPM_" + t.upper(), None)
    env_hr = os.getenv("PLAN_CHAT_RPH_" + t.upper(), None)

    if t == "pro":
        rpm = int(env_min) if env_min else 10
        rph = int(env_hr) if env_hr else 240
    elif "mini" in t:
        rpm = int(env_min) if env_min else 6
        rph = int(env_hr) if env_hr else 150
    else:
        rpm = int(env_min) if env_min else 3
        rph = int(env_hr) if env_hr else 60
    return rpm, rph


def _enforce_plan_rps(db: Session, user_id: int, tier: str) -> None:
    """
    Enforce plan-based chat rate limits using DB timestamps.
    Counts the user's chat submissions in the last minute/hour.
    Raise HTTPException(429) when exceeded.
    """
    per_min, per_hour = _plan_rate_windows_for(tier)
    now = datetime.utcnow()
    one_min_ago = now - timedelta(minutes=1)
    one_hr_ago = now - timedelta(hours=1)

    q_min = select(func.count(ChatMessage.id)).where(
        ChatMessage.user_id == user_id,
        ChatMessage.role == "user",
        ChatMessage.created_at >= one_min_ago,
    )
    q_hr = select(func.count(ChatMessage.id)).where(
        ChatMessage.user_id == user_id,
        ChatMessage.role == "user",
        ChatMessage.created_at >= one_hr_ago,
    )
    used_min = db.exec(q_min).one()
    used_hr = db.exec(q_hr).one()

    if used_min >= per_min:
        raise HTTPException(
            status_code=429,
            detail=f"Per-minute chat limit reached for your plan ({per_min}/minute). Try again in a moment.",
        )
    if used_hr >= per_hour:
        raise HTTPException(
            status_code=429,
            detail=f"Per-hour chat limit reached for your plan ({per_hour}/hour). Please try again later.",
        )


@asynccontextmanager
async def _maybe_bucket(request: Request, key: str):
    """
    If main.py configured request.app.state.llm_concurrency with a .bucket(key) -> async semaphore,
    use it; otherwise, no-op.
    """
    mgr = getattr(getattr(request.app, "state", object()), "llm_concurrency", None)
    if hasattr(mgr, "bucket"):
        sem = mgr.bucket(key)
        async with sem:
            yield
    else:
        yield


# -----------------------------
# Endpoints
# -----------------------------
@router.get("/sessions", response_model=List[ChatSessionOut])
@limiter.limit("60/minute", key_func=key_user_or_ip)
def get_sessions(
    request: Request,
    response: Response,
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
@limiter.limit("60/minute", key_func=key_user_or_ip)
def get_chat_messages(
    request: Request,
    response: Response,
    session_id: int,
    db: Session = Depends(get_session),
):
    return db.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
    ).all()


@router.patch("/{session_id}/title")
@limiter.limit("15/minute; 200/hour", key_func=key_user_or_ip)
def rename_chat_session(
    request: Request,
    response: Response,
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
# @limiter.limit("5/minute; 120/hour", key_func=key_user_or_ip)
async def ask(
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
):
    # --- Accept legacy and new payload shapes ---
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        body = {}

    # message can be at:
    #   A) body["message"]
    #   B) body["payload"]
    #   C) body["query"]["payload"]
    message = (
        (body.get("message") or "")
        or (body.get("payload") or "")
        or ((body.get("query") or {}).get("payload") or "")
    )
    message = str(message).strip()

    raw_sid = body.get("session_id")
    try:
        session_id: Optional[int] = int(raw_sid) if raw_sid is not None else None
    except (TypeError, ValueError):
        session_id = None

    if not message:
        raise HTTPException(status_code=422, detail="message/payload is required")

    # --- Auth / user ---
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # --- Plan-aware RPM/RPH (DB-backed) ---
    _enforce_plan_rps(db, user.id, user.tier or "free")

    # --- Daily chat quota (per plan) ---
    limit = plan_limit(user.tier)
    if limit != -1:
        used = _today_user_chat_count(db, user.id)
        if used >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Daily chat limit reached for your plan ({limit}/day). Upgrade to Mini+ or Pro for unlimited.",
            )

    # --- Monthly token hard cap ---
    monthly_cap = monthly_token_limit_for(user.tier)
    if monthly_cap > 0:
        used_tokens = monthly_tokens_used(db, user.id)
        if used_tokens >= monthly_cap:
            raise HTTPException(
                status_code=402,
                detail="Monthly token limit reached for your plan. Upgrade to increase your limit.",
            )

    # --- Ensure a session exists ---
    created_new_session = False
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
        created_new_session = True

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
            "how","what","when","where","which","please","help","issue","error","problem",
            "setup","set","configure","configuration","config","steps","guide","doc","docs",
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
    req_tokens = 0
    res_tokens = 0
    latency_ms = 0

    # ---- Optional per-user/IP concurrency guard (no-op if not configured)
    key = key_user_or_ip(request)
    async with _maybe_bucket(request, key):
        if has_context:
            grounded = True
            system_prompt = make_system_prompt(grounded=True)
            user_prompt = (
                f"User question:\n{message}\n\n"
                f"Context excerpts (separated by ---):\n{context_text}"
            )
            try:
                start = time.perf_counter()
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
                latency_ms = int((time.perf_counter() - start) * 1000)
                ai = (completion.choices[0].message.content or "").strip()
                usage = getattr(completion, "usage", None) or {}
                req_tokens = int(usage.get("prompt_tokens", 0))
                res_tokens = int(usage.get("completion_tokens", 0))
            except Exception as e:
                ai = f"RAG call failed: {e}"
        else:
            if ANSWER_POLICY == "context_only":
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
                        start = time.perf_counter()
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
                        latency_ms = int((time.perf_counter() - start) * 1000)
                        ai = (completion.choices[0].message.content or "").strip()
                        usage = getattr(completion, "usage", None) or {}
                        req_tokens = int(usage.get("prompt_tokens", 0))
                        res_tokens = int(usage.get("completion_tokens", 0))
                    except Exception as e:
                        ai = f"Model call failed: {e}"
                else:
                    ai = (
                        "I specialize strictly in OpenText platforms. "
                        "Please ask an OpenText question or upload relevant documentation."
                    )

    # --- Persist messages
    now = datetime.utcnow()
    db.add(ChatMessage(
        session_id=session_id,
        user_id=user.id,
        role="user",
        content=message,
        created_at=now,
    ))
    db.add(ChatMessage(
        session_id=session_id,
        user_id=user.id,
        role="assistant",
        content=ai,
        created_at=now,
    ))
    db.commit()

    # --- Analytics: usage + cost
    try:
        if req_tokens or res_tokens:
            log_llm_event(
                db=db,
                user_id=user.id,
                tier=user.tier,
                model=model_name,
                provider="openai",
                request_tokens=req_tokens,
                response_tokens=res_tokens,
                latency_ms=latency_ms,
                chat_session_id=session_id,
                retrieved_chunks=len(chunks),
                retrieved_tokens=0,
            )
    except Exception:
        pass

    # --- App event log
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
            "policy": ANSWER_POLICY,
            "ctx_present": bool(context_text),
            "scope": {"ctx": scope_hits_ctx},
        },
    )

    result: Dict[str, Any] = {"response": ai, "session_id": session_id}
    if created_new_session:
        result["title"] = _title_from_text(message)
    return result
