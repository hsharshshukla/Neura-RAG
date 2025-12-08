# app/routes/admin_summary.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_range(
    range_: Optional[str], date_from: Optional[str], date_to: Optional[str]
) -> Tuple[datetime, datetime, str]:
    now = _now_utc()
    if date_from and date_to:
        try:
            start = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            end = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(400, "Invalid ISO format for date_from/date_to")
        if start >= end:
            raise HTTPException(400, "date_from must be earlier than date_to")
        return start, end, "custom"

    r = (range_ or "7d").lower()
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
        raise HTTPException(403, "Admin access required")
    return user


def _column_exists(db: Session, table: str, column: str) -> bool:
    q = text(
        """
        SELECT EXISTS (
          SELECT 1
          FROM information_schema.columns
          WHERE table_schema = current_schema()
            AND table_name = :tbl
            AND column_name = :col
        )
        """
    )
    row = db.exec(q.bindparams(tbl=table, col=column)).first()
    return bool(row and list(row)[0])


@router.get("/summary")
def analytics_summary(
    range: Optional[str] = Query(default="7d"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    plan: Optional[str] = Query(default=None),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Shape matches the React page:
      { messages, sessions, latency_p50_ms, latency_p90_ms, rag_hit_rate,
        thumbs_up_rate, csat_avg, total_cost }
    """
    _ensure_admin(user_email, db)
    start, end, label = _parse_range(range, date_from, date_to)

    filters = ["ts >= :start", "ts < :end"]
    params: Dict[str, Any] = {"start": start, "end": end}
    if model:
        filters.append("model = :model")
        params["model"] = model
    if plan:
        filters.append("plan = :plan")
        params["plan"] = plan
    where_clause = " AND ".join(filters)

    has_session_id = _column_exists(db, "chat_event", "chat_session_id")
    sessions_expr = (
        "COUNT(DISTINCT chat_session_id) AS sessions"
        if has_session_id else
        "COUNT(DISTINCT user_id) AS sessions"
    )

    stmt = text(f"""
        WITH base AS (
          SELECT
            input_tokens,
            output_tokens,
            total_cost,
            latency_ms,
            response_code,
            retrieved,
            rag_hit,
            NULLIF(thumb, 0) AS thumb_nonzero,
            csat,
            (error_kind IS NOT NULL OR response_code >= 400) AS is_error,
            user_id
            {", chat_session_id" if has_session_id else ""}
          FROM chat_event
          WHERE {where_clause}
        )
        SELECT
          COUNT(*)::bigint                             AS messages,
          {sessions_expr},
          COALESCE(SUM(input_tokens), 0)              AS input_tokens,
          COALESCE(SUM(output_tokens), 0)             AS output_tokens,
          COALESCE(SUM(total_cost), 0)::numeric(12,6) AS total_cost,
          PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY latency_ms) AS latency_p50_ms,
          PERCENTILE_DISC(0.9) WITHIN GROUP (ORDER BY latency_ms) AS latency_p90_ms,
          CASE WHEN COUNT(*) FILTER (WHERE retrieved) > 0
               THEN (COUNT(*) FILTER (WHERE retrieved AND rag_hit))::float
                    / GREATEST(COUNT(*) FILTER (WHERE retrieved), 1)
               ELSE NULL
          END AS rag_hit_rate,
          CASE WHEN COUNT(*) FILTER (WHERE thumb_nonzero IS NOT NULL) > 0
               THEN (COUNT(*) FILTER (WHERE thumb_nonzero = 1))::float
                    / GREATEST(COUNT(*) FILTER (WHERE thumb_nonzero IS NOT NULL), 1)
               ELSE NULL
          END AS thumbs_up_rate,
          AVG(csat)::numeric(5,2) AS csat_avg
        FROM base
    """).bindparams(**params)

    row = db.exec(stmt).first()
    if not row:
        return {
            "range": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "messages": 0,
            "sessions": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_cost": "0.000000",
            "latency_p50_ms": None,
            "latency_p90_ms": None,
            "rag_hit_rate": None,
            "thumbs_up_rate": None,
            "csat_avg": None,
        }

    m = dict(row._mapping)
    return {
        "range": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "messages": int(m["messages"] or 0),
        "sessions": int(m["sessions"] or 0),
        "input_tokens": int(m["input_tokens"] or 0),
        "output_tokens": int(m["output_tokens"] or 0),
        "total_cost": str(m["total_cost"] or "0.000000"),
        "latency_p50_ms": m["latency_p50_ms"],
        "latency_p90_ms": m["latency_p90_ms"],
        "rag_hit_rate": m["rag_hit_rate"],
        "thumbs_up_rate": m["thumbs_up_rate"],
        "csat_avg": m["csat_avg"],
    }
