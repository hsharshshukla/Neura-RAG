# app/routes/admin_usage.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlmodel import Session, select

from app.db import get_session
from app.models import User
from app.deps.auth import get_current_user

# ---- plan limits (fallback to "unlimited") -----------------------------------
try:
    from app.config.plan_policy import monthly_token_limit_for  # type: ignore
except Exception:
    def monthly_token_limit_for(plan: str) -> int | None:
        # -1 or None => unlimited
        return -1

# ---- admin guard -------------------------------------------------------------
try:
    from app.deps.admin_dependency import require_admin  # type: ignore
except Exception:
    require_admin = None

router = APIRouter(prefix="/api/v1/admin/analytics", tags=["admin-analytics"])


# ---------- helpers ------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _parse_range(
    rng: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> Tuple[datetime, datetime, str]:
    now = _now_utc()
    if date_from and date_to:
        try:
            start = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            end = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(400, "Invalid ISO date_from/date_to")
        if start >= end:
            raise HTTPException(400, "date_from must be earlier than date_to")
        return start, end, "custom"

    r = (rng or "30d").lower()
    if r == "24h": return now - timedelta(hours=24), now, "24h"
    if r == "7d":  return now - timedelta(days=7),  now, "7d"
    if r == "30d": return now - timedelta(days=30), now, "30d"
    if r == "90d": return now - timedelta(days=90), now, "90d"
    return now - timedelta(days=30), now, "30d"

def _ensure_admin(user_email: str, db: Session) -> User:
    if require_admin:
        return require_admin(user_email=user_email, db=db)  # type: ignore
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user or getattr(user, "role", "user") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def _all(db: Session, stmt, params: Dict[str, Any]) -> List[Any]:
    return db.exec(stmt.bindparams(**params)).all() or []

def _first(db: Session, stmt, params: Dict[str, Any]):
    return db.exec(stmt.bindparams(**params)).first()


# ---------- 1) Active chats by day/week/month ---------------------------------

@router.get("/actives")
def actives(
    range: Optional[str] = Query(default="7d"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    granularity: str = Query(default="day", pattern="^(day|week|month)$"),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Rows: { bucket, active_chats, messages } grouped by day/week/month.
    """
    _ensure_admin(user_email, db)
    start, end, label = _parse_range(range, date_from, date_to)

    if granularity == "week":
        group_expr = "date_trunc('week', ts)"
    elif granularity == "month":
        group_expr = "date_trunc('month', ts)"
    else:
        group_expr = "date_trunc('day', ts)"

    sql = text(f"""
        SELECT
          {group_expr} AS bucket,
          COUNT(*)::bigint AS messages,
          COUNT(DISTINCT chat_session_id) AS active_chats
        FROM chat_event
        WHERE ts >= :start AND ts < :end
        GROUP BY 1
        ORDER BY 1
    """)
    rows = [dict(r._mapping) for r in _all(db, sql, {"start": start, "end": end})]
    for r in rows:
        if isinstance(r["bucket"], datetime):
            r["bucket"] = r["bucket"].date().isoformat()
    return {"range": label, "start": start.isoformat(), "end": end.isoformat(), "rows": rows}


# ---------- 2) Tokens by plan vs monthly limits -------------------------------

@router.get("/usage_vs_limits")
def tokens_usage_vs_limits(
    range: Optional[str] = Query(default="30d"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Per-plan tokens in window and comparison against monthly plan limits.
    Rows: plan, input_tokens, output_tokens, total_tokens, monthly_limit, pct_of_limit, remaining
    """
    _ensure_admin(user_email, db)
    start, end, label = _parse_range(range, date_from, date_to)

    sql = text("""
        SELECT
          COALESCE(NULLIF(TRIM(LOWER(plan)), ''), 'unknown') AS plan,
          COALESCE(SUM(input_tokens), 0)  AS input_tokens,
          COALESCE(SUM(output_tokens), 0) AS output_tokens
        FROM chat_event
        WHERE ts >= :start AND ts < :end
        GROUP BY 1
        ORDER BY 2 + 3 DESC
    """)
    rows = [dict(r._mapping) for r in _all(db, sql, {"start": start, "end": end})]

    data: List[Dict[str, Any]] = []
    for m in rows:
        plan = m["plan"]
        total = int(m["input_tokens"] or 0) + int(m["output_tokens"] or 0)
        limit_val = monthly_token_limit_for(plan)
        if limit_val is None or (isinstance(limit_val, int) and limit_val < 0):
            monthly_limit = None
            pct = None
            remaining = None
        else:
            monthly_limit = int(limit_val)
            pct = float(total) / monthly_limit if monthly_limit > 0 else None
            remaining = max(monthly_limit - total, 0)
        data.append({
            "plan": plan,
            "input_tokens": int(m["input_tokens"] or 0),
            "output_tokens": int(m["output_tokens"] or 0),
            "total_tokens": total,
            "monthly_limit": monthly_limit,  # null => unlimited
            "pct_of_limit": pct,             # 0..1 or null
            "remaining": remaining,          # null if unlimited
        })

    return {"range": label, "start": start.isoformat(), "end": end.isoformat(), "rows": data}


# ---------- 3) Top users by token usage (filter by plan) ----------------------

@router.get("/users/token_usage")
def users_token_usage(
    range: Optional[str] = Query(default="7d"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    plan: Optional[str] = Query(default=None, description="Filter by plan/tier (e.g. free|base|mini|pro)"),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Top users by tokens used. Uses chat_event.user_id (text, usually email).
    """
    _ensure_admin(user_email, db)
    start, end, label = _parse_range(range, date_from, date_to)

    filters = ["ts >= :start", "ts < :end"]
    params: Dict[str, Any] = {"start": start, "end": end, "lim": limit}
    if plan:
        filters.append("LOWER(plan) = LOWER(:plan)")
        params["plan"] = plan
    where_clause = " AND ".join(filters)

    sql = text(f"""
        SELECT
          COALESCE(NULLIF(TRIM(LOWER(plan)), ''), 'unknown') AS plan,
          user_id,
          COALESCE(SUM(input_tokens), 0)  AS input_tokens,
          COALESCE(SUM(output_tokens), 0) AS output_tokens
        FROM chat_event
        WHERE {where_clause}
        GROUP BY plan, user_id
        ORDER BY (COALESCE(SUM(input_tokens),0) + COALESCE(SUM(output_tokens),0)) DESC
        LIMIT :lim
    """)
    rows = [dict(r._mapping) for r in _all(db, sql, params)]

    # Attach a best-effort user primary key if present in Users table
    emails = [r["user_id"] for r in rows if r.get("user_id")]
    user_map: Dict[str, Any] = {}
    if emails:
        found = db.exec(select(User).where(User.email.in_(emails))).all() or []
        user_map = {u.email: u.id for u in found}

    out: List[Dict[str, Any]] = []
    for r in rows:
        total = int(r["input_tokens"] or 0) + int(r["output_tokens"] or 0)
        out.append({
            "plan": r["plan"],
            "user_email": r["user_id"],
            "user_id": user_map.get(r["user_id"]),  # may be None
            "input_tokens": int(r["input_tokens"] or 0),
            "output_tokens": int(r["output_tokens"] or 0),
            "total_tokens": total,
        })
    return {"range": label, "start": start.isoformat(), "end": end.isoformat(), "rows": out}


# ---------- 4) Top users by uploaded documents --------------------------------

_CANDIDATE_TABLES = [
    "documents", "document", "user_documents", "user_document",
    "files", "file", "user_files", "user_file", "uploads", "upload",
]
_TIME_COLUMNS = ["created_at", "uploaded_at", "ts", "timestamp"]
_SIZE_COLUMNS = ["size_bytes", "bytes", "size"]

def _find_uploads_table(db: Session) -> Optional[str]:
    for tbl in _CANDIDATE_TABLES:
        q = text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = :tbl
              AND column_name IN ('user_id','id')
        """)
        row = db.exec(q.bindparams(tbl=tbl)).first()
        if row and int(list(row)[0]) >= 2:
            return tbl
    return None

def _first_existing_col(db: Session, table: str, candidates: List[str]) -> Optional[str]:
    q = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = :tbl
          AND column_name = ANY(:cols)
        LIMIT 1
    """)
    row = db.exec(q.bindparams(tbl=table, cols=candidates)).first()
    return row[0] if row else None

@router.get("/users/uploads")
def users_uploads(
    range: Optional[str] = Query(default="30d"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Top users by number of uploaded documents (best-effort table autodetect).
    If a time column exists, we filter by window; otherwise returns all-time.
    """
    _ensure_admin(user_email, db)
    start, end, label = _parse_range(range, date_from, date_to)

    tbl = _find_uploads_table(db)
    if not tbl:
        return {
            "range": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "rows": [],
            "note": "No uploads table found (looked for: " + ", ".join(_CANDIDATE_TABLES) + ")",
        }

    tcol = _first_existing_col(db, tbl, _TIME_COLUMNS)
    scol = _first_existing_col(db, tbl, _SIZE_COLUMNS)

    where_clause = ""
    params: Dict[str, Any] = {"lim": limit}
    if tcol:
        where_clause = f"WHERE {tcol} >= :start AND {tcol} < :end"
        params["start"] = start
        params["end"] = end

    sql = text(f"""
        SELECT
          user_id,
          COUNT(*)::bigint AS files,
          {f"COALESCE(SUM({scol}),0)" if scol else "0"} AS size_bytes
        FROM {tbl}
        {where_clause}
        GROUP BY user_id
        ORDER BY files DESC
        LIMIT :lim
    """)
    rows = [dict(r._mapping) for r in _all(db, sql, params)]

    out: List[Dict[str, Any]] = []
    if rows and isinstance(rows[0]["user_id"], int):
        ids = [r["user_id"] for r in rows]
        found = db.exec(select(User).where(User.id.in_(ids))).all() or []
        id_to_email = {u.id: u.email for u in found}
        for r in rows:
            out.append({
                "user_id": r["user_id"],
                "user_email": id_to_email.get(r["user_id"]),
                "files": int(r["files"] or 0),
                "size_bytes": int(r["size_bytes"] or 0),
            })
    else:
        for r in rows:
            out.append({
                "user_id": r["user_id"],
                "user_email": r["user_id"] if isinstance(r["user_id"], str) else None,
                "files": int(r["files"] or 0),
                "size_bytes": int(r["size_bytes"] or 0),
            })

    return {"range": label, "start": start.isoformat(), "end": end.isoformat(), "rows": out}
