# app/routes/admin_actives.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlmodel import Session, select

from app.db import get_session
from app.models import User
from app.deps.auth import get_current_user

try:
    from app.deps.admin_dependency import require_admin  # type: ignore
except Exception:
    require_admin = None

router = APIRouter(prefix="/api/v1/admin/analytics", tags=["admin-analytics"])

# ---------- helpers

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _parse_range(rng: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> Tuple[datetime, datetime, str]:
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

    r = (rng or "7d").lower()
    if r == "24h": return now - timedelta(hours=24), now, "24h"
    if r == "7d":  return now - timedelta(days=7),  now, "7d"
    if r == "30d": return now - timedelta(days=30), now, "30d"
    if r == "90d": return now - timedelta(days=90), now, "90d"
    return now - timedelta(days=7), now, "7d"

def _ensure_admin(user_email: str, db: Session) -> User:
    if require_admin:
        return require_admin(user_email=user_email, db=db)  # type: ignore
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user or getattr(user, "role", "user") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def _column_exists(db: Session, table: str, column: str) -> bool:
    q = text("""
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = current_schema()
            AND table_name = :t AND column_name = :c
        )
    """).bindparams(t=table, c=column)
    row = db.exec(q).first()
    return bool(row and list(row)[0])

# ---------- endpoint

@router.get("/actives")
def active_chats_timeseries(
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    range: Optional[str] = Query(default="7d"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    plan: Optional[str] = Query(default=None),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Returns timeseries buckets with:
      bucket, active_chats (distinct sessions), messages, input_tokens, output_tokens, total_cost
    """
    _ensure_admin(user_email, db)
    start, end, label = _parse_range(range, date_from, date_to)

    bucket_expr = {
        "day":   "date_trunc('day', ts)",
        "week":  "date_trunc('week', ts)",
        "month": "date_trunc('month', ts)",
    }[granularity]

    # Determine key for "active chats": prefer distinct chat_session_id; else fallback to distinct user_id
    has_session = _column_exists(db, "chat_event", "chat_session_id")
    distinct_key = "chat_session_id" if has_session else "user_id"

    filters = ["ts >= :start", "ts < :end"]
    params: Dict[str, Any] = {"start": start, "end": end}
    if model:
        filters.append("model = :model")
        params["model"] = model
    if plan:
        filters.append("plan = :plan")
        params["plan"] = plan
    where_clause = " AND ".join(filters)

    sql = text(f"""
        SELECT
          {bucket_expr} AS bucket,
          COUNT(DISTINCT {distinct_key})       AS active_chats,
          COUNT(*)::bigint                     AS messages,
          COALESCE(SUM(input_tokens), 0)       AS input_tokens,
          COALESCE(SUM(output_tokens), 0)      AS output_tokens,
          COALESCE(SUM(total_cost), 0)::numeric(12,6) AS total_cost
        FROM chat_event
        WHERE {where_clause}
        GROUP BY 1
        ORDER BY 1
    """)
    rows = db.exec(sql.bindparams(**params)).all() or []

    data: List[Dict[str, Any]] = []
    for r in rows:
        m = dict(r._mapping)
        b = m["bucket"]
        if isinstance(b, datetime):
            m["bucket"] = b.date().isoformat()
        data.append(m)

    return {
        "range": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "granularity": granularity,
        "rows": data,
    }
