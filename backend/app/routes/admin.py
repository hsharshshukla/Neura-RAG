# backend/app/routes/admin.py
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select, or_
from sqlalchemy import func

from app.db import get_session
from app.models import User, Upload, ChatSession, ChatMessage, Chat
from app.deps.admin_dependency import get_current_admin
from app.vector_store import get_vector_stats
from app.utils.logger import log_event

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
)

# ---------- request models ----------
class EmailIn(BaseModel):
    email: EmailStr

class SetTierIn(BaseModel):
    email: EmailStr
    tier: Literal["free", "pro"]  # extend later if you add more

# ---------- helpers ----------
def _count_where(db: Session, model, *conds) -> int:
    stmt = select(func.count()).select_from(model)
    if conds:
        stmt = stmt.where(*conds)
    res = db.exec(stmt).one()
    return int(res[0] if isinstance(res, (list, tuple)) else res)

def _active_users_24h(db: Session) -> int:
    day_ago = datetime.utcnow() - timedelta(days=1)

    # Preferred: ChatMessage -> ChatSession -> User
    try:
        sess_map = {s.id: s.user_id for s in db.exec(select(ChatSession)).all()}
        emails = set()
        msgs = db.exec(select(ChatMessage).where(ChatMessage.timestamp >= day_ago)).all()
        for msg in msgs or []:
            uid = sess_map.get(msg.session_id)
            if uid:
                u = db.get(User, uid)
                if u and u.email:
                    emails.add(u.email)
        if emails:
            return len(emails)
    except Exception:
        pass

    # Fallback: legacy Chat
    try:
        emails = {
            c.user_email
            for c in db.exec(select(Chat).where(Chat.created_at >= day_ago)).all()
            if c.user_email
        }
        if emails:
            return len(emails)
    except Exception:
        pass

    # Fallback: new signups in 24h
    try:
        return _count_where(db, User, User.created_at >= day_ago)
    except Exception:
        return 0

# ---------- routes ----------
@router.get("/metrics")
def metrics(db: Session = Depends(get_session)) -> Dict[str, Any]:
    day_ago = datetime.utcnow() - timedelta(days=1)

    active_users_24h = _active_users_24h(db)

    try:
        uploads_24h = _count_where(db, Upload, Upload.created_at >= day_ago)
    except Exception:
        uploads_24h = 0

    # queries in last 24h (prefer ChatMessage, fallback to Chat)
    try:
        queries_24h = _count_where(db, ChatMessage, ChatMessage.timestamp >= day_ago)
    except Exception:
        try:
            queries_24h = _count_where(db, Chat, Chat.created_at >= day_ago)
        except Exception:
            queries_24h = 0

    try:
        total_users = _count_where(db, User)
    except Exception:
        total_users = 0

    try:
        pro_users = _count_where(db, User, User.tier == "pro")
    except Exception:
        pro_users = 0

    free_to_pro = round((pro_users / total_users) * 100, 1) if total_users else 0.0

    return {
        "active_users_24h": active_users_24h,
        "uploads_24h": uploads_24h,
        "queries_24h": queries_24h,
        "free_to_pro": free_to_pro,
    }

@router.get("/users")
def users(
    q: str = "",
    tier: str = "",
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_session),
):
    conds = []
    if q:
        like = f"%{q}%"
        conds.append(or_(User.email.ilike(like), User.name.ilike(like)))
    if tier:
        conds.append(User.tier == tier)

    total = _count_where(db, User, *conds)

    stmt = select(User)
    if conds:
        stmt = stmt.where(*conds)
    items = db.exec(
        stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
    ).all()

    return {"total": total, "items": items}

@router.get("/uploads")
def uploads(
    q: str = "",
    type: str = "",
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_session),
):
    conds = []
    if q:
        conds.append(Upload.filename.ilike(f"%{q}%"))
    if type:
        conds.append(Upload.filetype == type)

    total = _count_where(db, Upload, *conds)

    stmt = select(Upload)
    if conds:
        stmt = stmt.where(*conds)
    items = db.exec(
        stmt.order_by(Upload.created_at.desc()).offset(offset).limit(limit)
    ).all()

    try:
        stats = get_vector_stats()
    except Exception:
        stats = {"Chunks": "n/a", "Storage": "n/a", "Last Reindex": "n/a"}

    return {"total": total, "items": items, "stats": stats}

@router.get("/sessions")
def sessions(limit: int = 20, db: Session = Depends(get_session)):
    out: List[Dict[str, Any]] = []

    # Preferred: ChatSession + ChatMessage
    try:
        sess_rows = db.exec(
            select(ChatSession).order_by(ChatSession.created_at.desc()).limit(limit)
        ).all()
        if sess_rows:
            users_map = {u.id: u.email for u in db.exec(select(User)).all()}
            for s in sess_rows:
                try:
                    cnt = _count_where(db, ChatMessage, ChatMessage.session_id == s.id)
                except Exception:
                    cnt = 0
                out.append({
                    "id": s.id,
                    "session_id": str(s.id),
                    "user_email": users_map.get(s.user_id, "-"),
                    "created_at": s.created_at,
                    "message_count": cnt,
                    "transcript": "",
                })
            return {"total": len(out), "items": out}
    except Exception:
        pass

    # Fallback: legacy Chat
    try:
        chats = db.exec(select(Chat).order_by(Chat.created_at.desc()).limit(limit)).all()
        for c in chats:
            out.append({
                "id": c.id,
                "session_id": c.id,
                "user_email": c.user_email,
                "created_at": c.created_at,
                "message_count": 0,
                "transcript": "",
            })
    except Exception:
        return {"total": 0, "items": []}

    return {"total": len(out), "items": out}

@router.get("/billing/stats")
def billing_stats(db: Session = Depends(get_session)):
    pro = _count_where(db, User, User.tier == "pro")
    total = _count_where(db, User)
    return {"Active Pro": pro, "MRR": "$0", "Failed Payments": 0, "Total Users": total}

@router.get("/billing/webhooks")
def billing_webhooks():
    return {"items": []}

@router.get("/settings")
def settings():
    return {
        "openai_key_masked": "sk-********",
        "vector_path": "./backend/vector_store",
        "ocr": "Tesseract",
    }

# ---------- user admin actions (JSON bodies only) ----------
@router.post("/users/promote")
def promote_user(
    payload: EmailIn,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    email = payload.email.lower()
    user = db.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.role = "admin"
    db.add(user); db.commit(); db.refresh(user)
    log_event("ADMIN_PROMOTE", {"actor": admin.email, "target": email})
    return {"ok": True, "user": {"email": user.email, "role": user.role, "tier": user.tier}}

@router.post("/users/demote")
def demote_user(
    payload: EmailIn,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    email = payload.email.lower()
    user = db.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.role = "user"
    db.add(user); db.commit(); db.refresh(user)
    log_event("ADMIN_DEMOTE", {"actor": admin.email, "target": email})
    return {"ok": True, "user": {"email": user.email, "role": user.role, "tier": user.tier}}

@router.post("/users/set-tier")
def set_tier(
    payload: SetTierIn,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    email = payload.email.lower()
    user = db.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.tier = payload.tier
    db.add(user); db.commit(); db.refresh(user)
    log_event("ADMIN_SET_TIER", {"actor": admin.email, "target": email, "tier": user.tier})
    return {"ok": True, "user": {"email": user.email, "role": user.role, "tier": user.tier}}

@router.post("/users/logout-all")
def logout_all_for_user(
    payload: EmailIn,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    email = payload.email.lower()
    user = db.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.token_version = (user.token_version or 0) + 1
    db.add(user); db.commit(); db.refresh(user)
    log_event("ADMIN_LOGOUT_ALL", {"actor": admin.email, "target": email, "new_token_version": user.token_version})
    return {"ok": True}
