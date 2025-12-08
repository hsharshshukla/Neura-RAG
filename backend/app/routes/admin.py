# backend/app/routes/admin.py

from app.db import get_session
from app.deps.admin_dependency import get_current_admin
from app.models import Coupon, User, Upload, ChatSession, ChatMessage, Chat
from app.utils.logger import log_event
from app.vector_store import get_vector_stats
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator, EmailStr
from sqlalchemy import func
from sqlmodel import Session, select, or_
from typing import Dict, Any, List, Literal

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],  # keep your existing admin auth/guard
)

# ---------- request models ----------
class EmailIn(BaseModel):
    email: EmailStr

class SetTierIn(BaseModel):
    # ✅ allow mini (Mini+)
    email: EmailStr
    tier: Literal["free", "mini", "pro"]

# ---------- helpers ----------
def _count_where(db: Session, model, *conds) -> int:
    stmt = select(func.count()).select_from(model)
    if conds:
        stmt = stmt.where(*conds)
    res = db.exec(stmt).one()
    # res can be (count,) or a scalar depending on driver
    return int(res[0] if isinstance(res, (list, tuple)) else res)

def _active_users_24h(db: Session) -> int:
    day_ago = datetime.utcnow() - timedelta(days=1)

    # Preferred: ChatMessage -> ChatSession -> User
    try:
        sess_map = {s.id: s.user_id for s in db.exec(select(ChatSession)).all()}
        emails = set()
        # 🔧 use created_at (not timestamp)
        msgs = db.exec(select(ChatMessage).where(ChatMessage.created_at >= day_ago)).all()
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

# ---------- new: health ----------
@router.get("/health")
async def health():
    """
    Lightweight health check for the Console pill.
    Extend later with queue sizes / DB pings if needed.
    """
    return {"status": "ok"}

# ---------- new: overview (totals for Console Overview.jsx) ----------
@router.get("/overview")
def overview(db: Session = Depends(get_session)) -> Dict[str, Any]:
    totals = {
        "users": 0,
        "documents": 0,      # using Upload as "documents"
        "chat_sessions": 0,  # prefer ChatSession; fallback to Chat
    }
    try:
        totals["users"] = _count_where(db, User)
    except Exception:
        pass
    try:
        totals["documents"] = _count_where(db, Upload)
    except Exception:
        pass
    try:
        totals["chat_sessions"] = _count_where(db, ChatSession)
    except Exception:
        # fallback to legacy Chat rows if ChatSession isn’t present
        try:
            totals["chat_sessions"] = _count_where(db, Chat)
        except Exception:
            pass
    return {"totals": totals}

# ---------- existing: metrics ----------
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
        # 🔧 use created_at (not timestamp)
        queries_24h = _count_where(db, ChatMessage, ChatMessage.created_at >= day_ago)
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
        mini_users = _count_where(db, User, User.tier == "mini")
        free_users = _count_where(db, User, User.tier == "free")
    except Exception:
        pro_users = mini_users = free_users = 0

    free_to_pro = round((pro_users / total_users) * 100, 1) if total_users else 0.0

    return {
        "active_users_24h": active_users_24h,
        "uploads_24h": uploads_24h,
        "queries_24h": queries_24h,
        "total_users": total_users,
        "tiers": {
            "free": free_users,
            "mini": mini_users,
            "pro": pro_users,
        },
        "free_to_pro": free_to_pro,
    }

# ---------- existing: users list/search ----------
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

# ---------- uploads (robust: join upload_link + blob + users; fallback to Upload) ----------
# # ---------- uploads (robust: join upload_link + blob + users; fallback to Upload) ----------
# @router.get("/uploads")
# def uploads(
#     q: str = "",
#     type: str = "",
#     limit: int = 20,
#     offset: int = 0,
#     db: Session = Depends(get_session),
# ):
#     """
#     Preferred: list from upload_link + blob + users (matches upload.py tables).
#     Fallback:  list from Upload model if join isn't available.
#     """
#     like = f"%{q}%" if q else None
#     type_norm = (type or "").lower().lstrip(".")  # normalize "pdf" or ".pdf"

#     # Resolve/quote the user table name safely (SQLModel may name it "user" which is reserved).
#     USER_TBL = getattr(User, "__tablename__", "user")
#     USER_TBL_SQL = f'public."{USER_TBL}"'  # quote to avoid reserved keyword issues

#     try:
#         # ---- Count (search over storage_uri and ext) ----
#         count_sql = f"""
#             SELECT COUNT(1)
#             FROM public.upload_link ul
#             JOIN public.blob b ON b.sha256 = ul.sha256
#             JOIN {USER_TBL_SQL} u ON u.id = ul.user_id
#             WHERE (:q IS NULL OR (COALESCE(b.storage_uri,'') ILIKE :like OR COALESCE(b.ext,'') ILIKE :like))
#               AND (:t = '' OR LOWER(REPLACE(COALESCE(b.ext,''), '.', '')) = :t)
#         """
#         total = int(
#             db.connection()
#               .exec_driver_sql(count_sql, {"q": bool(q), "like": like, "t": type_norm})
#               .scalar()
#             or 0
#         )

#         # ---- Rows ----
#         rows_sql = f"""
#             SELECT
#               ul.id           AS link_id,
#               ul.created_at   AS created_at,
#               ul.session_id   AS session_id,
#               u.email         AS user_email,
#               b.sha256        AS sha256,
#               b.bytes         AS size_bytes,
#               COALESCE(NULLIF(b.ext,''), '')        AS ext,
#               COALESCE(NULLIF(b.mime,''), '')       AS mime,
#               COALESCE(NULLIF(b.storage_uri,''), '') AS storage_uri
#             FROM public.upload_link ul
#             JOIN public.blob b ON b.sha256 = ul.sha256
#             JOIN {USER_TBL_SQL} u ON u.id = ul.user_id
#             WHERE (:q IS NULL OR (COALESCE(b.storage_uri,'') ILIKE :like OR COALESCE(b.ext,'') ILIKE :like))
#               AND (:t = '' OR LOWER(REPLACE(COALESCE(b.ext,''), '.', '')) = :t)
#             ORDER BY ul.created_at DESC
#             OFFSET :offset LIMIT :limit
#         """
#         res = db.connection().exec_driver_sql(
#             rows_sql,
#             {"q": bool(q), "like": like, "t": type_norm, "offset": offset, "limit": limit},
#         )
#         rows = [dict(r._mapping) for r in res]

#         # Infer a display filename from storage_uri (last path segment) or sha256.ext
#         def infer_filename(r: dict) -> str:
#             uri = r.get("storage_uri") or ""
#             name = uri.rsplit("/", 1)[-1] if "/" in uri else uri
#             name = name or ""
#             if name:
#                 return name
#             ext = (r.get("ext") or "").lstrip(".")
#             sha = r.get("sha256") or ""
#             return f"{sha}.{ext}" if ext and sha else (sha or "—")

#         items = []
#         for r in rows:
#             items.append({
#                 "id": r.get("link_id"),
#                 "filename": infer_filename(r),
#                 "filetype": (r.get("ext") or "").lstrip("."),
#                 "size_bytes": r.get("size_bytes"),
#                 "user_email": r.get("user_email"),
#                 "user_id": None,  # not selected; add if you need it
#                 "created_at": r.get("created_at"),
#                 "status": "",     # no pipeline state tracked here
#             })

#         try:
#             stats = get_vector_stats()
#         except Exception:
#             stats = {"Chunks": "n/a", "Storage": "n/a", "Last Reindex": "n/a"}

#         return {
#             "total": total,
#             "items": items,
#             "stats": stats,
#             "limit": limit,
#             "offset": offset,
#             "q": q,
#             "type": type,
#         }

#     except Exception:
#         # ---- Fallback: use Upload model (legacy) ----
#         conds = []
#         if q:
#             conds.append(Upload.filename.ilike(f"%{q}%"))
#         if type:
#             conds.append(Upload.filetype == type)

#         total = _count_where(db, Upload, *conds)

#         stmt = select(Upload)
#         if conds:
#             stmt = stmt.where(*conds)
#         rows = db.exec(
#             stmt.order_by(Upload.created_at.desc()).offset(offset).limit(limit)
#         ).all()

#         items = []
#         for r in rows:
#             get = (lambda k, d=None: getattr(r, k, d) if hasattr(r, k) else (r.get(k, d) if isinstance(r, dict) else d))
#             items.append({
#                 "id": get("id"),
#                 "filename": get("filename") or get("name") or "—",
#                 "filetype": (get("filetype") or get("ext") or "").lstrip("."),
#                 "size_bytes": get("size_bytes") or get("size"),
#                 "user_email": get("user_email") or get("owner_email") or get("email") or "—",
#                 "user_id": get("user_id"),
#                 "created_at": get("created_at"),
#                 "status": get("status") or get("processing_state") or "",
#             })

#         try:
#             stats = get_vector_stats()
#         except Exception:
#             stats = {"Chunks": "n/a", "Storage": "n/a", "Last Reindex": "n/a"}

#         return {
#             "total": total,
#             "items": items,
#             "stats": stats,
#             "limit": limit,
#             "offset": offset,
#             "q": q,
#             "type": type,
#         }

# ---------- uploads (robust: join upload_link + blob + users; fallback to Upload) ----------
from sqlalchemy import text  # add at top of file if not present

@router.get("/uploads")
def uploads(
    q: str = "",
    type: str = "",
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_session),
):
    """
    Preferred: list from upload_link + blob + users (matches upload.py tables).
    Fallback:  list from Upload model if join isn't available.
    """
    like = f"%{q}%" if q else None
    type_norm = (type or "").lower().lstrip(".")  # normalize "pdf" or ".pdf"

    # Resolve/quote the user table name safely (SQLModel may name it "user" which is reserved).
    USER_TBL = getattr(User, "__tablename__", "user")
    USER_TBL_SQL = f'public."{USER_TBL}"'  # quote to avoid reserved keyword issues

    try:
        conn = db.connection()

        # ---- WHERE (built dynamically to avoid param-style gotchas) ----
        where_clauses = []
        params: dict[str, object] = {}

        if like:
            where_clauses.append("(COALESCE(b.storage_uri,'') ILIKE :like OR COALESCE(b.ext,'') ILIKE :like)")
            params["like"] = like

        if type_norm:
            where_clauses.append("LOWER(REPLACE(COALESCE(b.ext,''), '.', '')) = :t")
            params["t"] = type_norm

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # ---- COUNT ----
        count_sql = f"""
            SELECT COUNT(1)
            FROM public.upload_link ul
            JOIN public.blob b ON b.sha256 = ul.sha256
            JOIN {USER_TBL_SQL} u ON u.id = ul.user_id
            {where_sql}
        """
        total = int(conn.execute(text(count_sql), params).scalar() or 0)

        # ---- ROWS ----
        rows_sql = f"""
            SELECT
              ul.id           AS link_id,
              ul.created_at   AS created_at,
              ul.session_id   AS session_id,
              u.email         AS user_email,
              b.sha256        AS sha256,
              b.bytes         AS size_bytes,
              COALESCE(NULLIF(b.ext,''), '')         AS ext,
              COALESCE(NULLIF(b.mime,''), '')        AS mime,
              COALESCE(NULLIF(b.storage_uri,''), '') AS storage_uri
            FROM public.upload_link ul
            JOIN public.blob b ON b.sha256 = ul.sha256
            JOIN {USER_TBL_SQL} u ON u.id = ul.user_id
            {where_sql}
            ORDER BY ul.created_at DESC
            OFFSET :offset LIMIT :limit
        """
        row_params = {**params, "offset": offset, "limit": limit}
        res = conn.execute(text(rows_sql), row_params)
        rows = [dict(r._mapping) for r in res]

        # Infer a display filename from storage_uri (last path segment) or sha256.ext
        def infer_filename(r: dict) -> str:
            uri = r.get("storage_uri") or ""
            name = uri.rsplit("/", 1)[-1] if "/" in uri else uri
            name = name or ""
            if name:
                return name
            ext = (r.get("ext") or "").lstrip(".")
            sha = r.get("sha256") or ""
            return f"{sha}.{ext}" if ext and sha else (sha or "—")

        items = []
        for r in rows:
            items.append({
                "id": r.get("link_id"),
                "filename": infer_filename(r),
                "filetype": (r.get("ext") or "").lstrip("."),
                "size_bytes": r.get("size_bytes"),
                "user_email": r.get("user_email"),
                "user_id": None,  # not selected; add if you need it
                "created_at": r.get("created_at"),
                "status": "",     # no pipeline state tracked here
            })

        try:
            stats = get_vector_stats()
        except Exception:
            stats = {"Chunks": "n/a", "Storage": "n/a", "Last Reindex": "n/a"}

        return {
            "total": total,
            "items": items,
            "stats": stats,
            "limit": limit,
            "offset": offset,
            "q": q,
            "type": type,
        }

    except Exception:
        # Important: reset failed transaction so fallback SELECTs work
        try:
            db.rollback()
        except Exception:
            pass

        # ---- Fallback: use Upload model (legacy) ----
        conds = []
        if q:
            conds.append(Upload.filename.ilike(f"%{q}%"))
        if type_norm:
            conds.append(Upload.filetype == type_norm)

        total = _count_where(db, Upload, *conds)

        stmt = select(Upload)
        if conds:
            stmt = stmt.where(*conds)
        rows = db.exec(
            stmt.order_by(Upload.created_at.desc()).offset(offset).limit(limit)
        ).all()

        items = []
        for r in rows:
            get = (lambda k, d=None: getattr(r, k, d) if hasattr(r, k) else (r.get(k, d) if isinstance(r, dict) else d))
            items.append({
                "id": get("id"),
                "filename": get("filename") or get("name") or "—",
                "filetype": (get("filetype") or get("ext") or "").lstrip("."),
                "size_bytes": get("size_bytes") or get("size"),
                "user_email": get("user_email") or get("owner_email") or get("email") or "—",
                "user_id": get("user_id"),
                "created_at": get("created_at"),
                "status": get("status") or get("processing_state") or "",
            })

        try:
            stats = get_vector_stats()
        except Exception:
            stats = {"Chunks": "n/a", "Storage": "n/a", "Last Reindex": "n/a"}

        return {
            "total": total,
            "items": items,
            "stats": stats,
            "limit": limit,
            "offset": offset,
            "q": q,
            "type": type,
        }


# ---------- existing: sessions ----------
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

# ── Session detail (read-only transcript for Console) ──────────────────────────
# ---------- admin: single session (messages + owner) ----------
from typing import Optional

@router.get("/sessions/{session_id}")
def session_detail(session_id: int, db: Session = Depends(get_session)):
    """
    Returns a read-only view of a chat session for Console.
    Tries new ChatSession/ChatMessage first; falls back to legacy Chat rows.
    """
    # Preferred: ChatSession + ChatMessage
    try:
        s = db.get(ChatSession, session_id)
        if s:
            # owner
            owner_email: Optional[str] = None
            try:
                u = db.get(User, s.user_id) if getattr(s, "user_id", None) else None
                owner_email = getattr(u, "email", None)
            except Exception:
                owner_email = None

            # messages
            msgs = db.exec(
                select(ChatMessage)
                .where(ChatMessage.session_id == s.id)
                .order_by(ChatMessage.created_at.asc())
            ).all()

            messages = []
            for m in msgs or []:
                messages.append({
                    "id": getattr(m, "id", None),
                    "role": getattr(m, "role", "user"),
                    "content": getattr(m, "content", "") or getattr(m, "text", ""),
                    "created_at": getattr(m, "created_at", None),
                })

            return {
                "session": {
                    "id": s.id,
                    "created_at": s.created_at,
                    "user_email": owner_email or "-",
                    "message_count": len(messages),
                },
                "messages": messages,
            }
    except Exception:
        pass

    # Fallback: legacy Chat table (if you don’t have ChatMessage rows)
    try:
        c = db.get(Chat, session_id)
        if c:
            return {
                "session": {
                    "id": c.id,
                    "created_at": c.created_at,
                    "user_email": getattr(c, "user_email", "-"),
                    "message_count": 0,
                },
                "messages": [
                    {
                        "id": c.id,
                        "role": "user",
                        "content": getattr(c, "prompt", "") or getattr(c, "content", "") or "",
                        "created_at": c.created_at,
                    }
                ],
            }
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="Session not found")


# ---------- existing: billing ----------
@router.get("/billing/stats")
def billing_stats(db: Session = Depends(get_session)):
    pro = _count_where(db, User, User.tier == "pro")
    mini = _count_where(db, User, User.tier == "mini")
    free = _count_where(db, User, User.tier == "free")
    total = _count_where(db, User)
    # You can compute MRR once billing is wired
    return {
        "Active Pro": pro,
        "Active Mini": mini,
        "Active Free": free,
        "MRR": "$0",
        "Failed Payments": 0,
        "Total Users": total,
    }

@router.get("/billing/webhooks")
def billing_webhooks():
    return {"items": []}

# ---------- existing: settings ----------
@router.get("/settings")
def settings():
    return {
        "openai_key_masked": "sk-********",
        "vector_path": "./backend/vector_store",
        "ocr": "Tesseract",
    }

# ---------- existing: user admin actions (JSON bodies only) ----------
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
    user.tier = payload.tier  # ✅ accepts free | mini | pro
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

# ---------- coupons (schema-agnostic → mapped to your DB columns) ----------


from typing import Literal, Optional
from typing_extensions import Annotated
from pydantic import BaseModel, Field, StringConstraints, field_validator
from datetime import datetime

# --- request model (Pydantic v2 style) ---
CodeStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]

class CouponCreate(BaseModel):
    code: CodeStr
    discount_type: Literal["percent", "fixed"]
    value: int = Field(gt=0)                    # validated further below
    # Optional limits
    max_redemptions: Optional[int] = Field(default=None, gt=0)
    per_user_limit: Optional[int] = Field(default=None, gt=0)
    # Windows (accept ISO strings); you were already passing null or ISO
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    # Only for "fixed" (UI-enforced; default to USD)
    currency: Optional[Literal["USD", "INR"]] = "USD"

    @field_validator("value")
    @classmethod
    def _check_value(cls, v, info):
        data = info.data or {}
        dtype = data.get("discount_type")
        currency = data.get("currency") or "USD"
        # Percent: 1..100
        if dtype == "percent":
            if not (1 <= v <= 100):
                raise ValueError("Percent value must be between 1 and 100")
        # Fixed: USD ≤ 10; INR ≤ 100
        elif dtype == "fixed":
            max_for_currency = 10 if currency == "USD" else 100
            if not (1 <= v <= max_for_currency):
                raise ValueError(f"Fixed value for {currency} must be between 1 and {max_for_currency}")
        return v

@router.post("/coupons", status_code=status.HTTP_201_CREATED)
def coupons_create(
    payload: CouponCreate,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    # Enforce unique code
    existing = db.exec(select(Coupon).where(Coupon.code == payload.code)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Coupon code exists")

    # Your existing table requires legacy fields. Map them here:
    # - name: NOT NULL -> reuse code as display name
    # - amount_type: "percent" | "fixed" (matches your DB)
    # - amount: the integer value provided
    # - currency: only meaningful for fixed (ok to store for both)
    # - is_limited_redemptions: true iff max_redemptions provided
    # - per_customer_limit: from per_user_limit
    # - starts_at / expires_at map directly
    # - status: default "active"
    c = Coupon(
        code=payload.code,
        name=payload.code,  # satisfy NOT NULL
        amount=payload.value,
        amount_type=payload.discount_type,   # "percent" or "fixed"
        currency=(payload.currency if payload.discount_type == "fixed" else None),
        duration="once",                     # reasonable default for your schema
        duration_in_months=None,
        starts_at=payload.starts_at,
        expires_at=payload.ends_at,
        is_limited_redemptions=payload.max_redemptions is not None,
        max_redemptions=payload.max_redemptions or 1,   # your table showed 1 earlier; keep sane default
        per_customer_limit=payload.per_user_limit,
        applies_to_variants=None,
        status="active",
        created_at=datetime.utcnow(),
    )

    db.add(c); db.commit(); db.refresh(c)
    log_event(
        "ADMIN_COUPON_CREATE",
        {
            "actor": admin.email,
            "code": c.code,
            "type": c.amount_type,
            "value": c.amount,
            "currency": c.currency,
        },
    )

    # Return a normalized shape that Console expects
    return {
        "id": c.id,
        "code": c.code,
        "discount_type": c.amount_type,
        "value": c.amount,
        "currency": c.currency,
        "max_redemptions": c.max_redemptions,
        "per_user_limit": c.per_customer_limit,
        "starts_at": c.starts_at,
        "ends_at": c.expires_at,
        "created_at": c.created_at,
    }



@router.get("/coupons")
def coupons_list(
    q: str = "",
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_session),
):
    conds = []
    if q:
        like = f"%{q}%"
        # Handle either modern or legacy column names in search
        try:
            conds.append(or_(Coupon.code.ilike(like), Coupon.amount_type.ilike(like)))
        except Exception:
            # fallback if amount_type column doesn't exist
            conds.append(or_(Coupon.code.ilike(like), Coupon.discount_type.ilike(like)))

    total = _count_where(db, Coupon, *conds)

    stmt = select(Coupon)
    if conds:
        stmt = stmt.where(*conds)
    rows = db.exec(
        stmt.order_by(Coupon.created_at.desc()).offset(offset).limit(limit)
    ).all()

    # Map ORM rows → UI-friendly shape consistently
    items = []
    for c in rows:
        # Try both sets of names to be tolerant
        discount_type = getattr(c, "amount_type", None) or getattr(c, "discount_type", None)
        value = getattr(c, "amount", None) or getattr(c, "value", None)
        starts_at = getattr(c, "starts_at", None)
        ends_at = getattr(c, "expires_at", None) or getattr(c, "ends_at", None)
        max_redemptions = getattr(c, "max_redemptions", None)
        per_user_limit = getattr(c, "per_customer_limit", None) or getattr(c, "per_user_limit", None)
        currency = getattr(c, "currency", None)

        items.append({
            "id": getattr(c, "id", None),
            "code": getattr(c, "code", ""),
            "discount_type": discount_type,
            "value": value,
            "currency": currency,
            "max_redemptions": max_redemptions,
            "per_user_limit": per_user_limit,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "created_at": getattr(c, "created_at", None),
        })

    return {"total": total, "items": items, "limit": limit, "offset": offset, "q": q}



@router.delete("/coupons/{coupon_id}", status_code=status.HTTP_204_NO_CONTENT)
def coupons_delete(
    coupon_id: int,
    db: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    c = db.get(Coupon, coupon_id)
    if not c:
        raise HTTPException(status_code=404, detail="Coupon not found")
    code = getattr(c, "code", None)
    db.delete(c)
    db.commit()
    log_event("ADMIN_COUPON_DELETE", {"actor": admin.email, "id": coupon_id, "code": code})
    return
