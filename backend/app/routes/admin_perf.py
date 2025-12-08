# app/routes/admin_perf.py
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_range(range_: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> Tuple[datetime, datetime, str]:
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
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _all(db: Session, stmt, params: Dict[str, Any]) -> List[Any]:
    return db.exec(stmt.bindparams(**params)).all() or []


@router.get("/perf")
def perf_breakdown(
    group_by: str = Query("model", pattern="^(model|plan|day)$"),
    range: Optional[str] = Query(default="7d", description="24h|7d|30d|90d"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    plan: Optional[str] = Query(default=None),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Performance breakdown grouped by `model`, `plan`, or `day`.
    Returns rows with:
      group_key, messages, input_tokens, output_tokens, total_cost,
      latency_p50_ms, latency_p90_ms, error_rate
    """
    _ensure_admin(user_email, db)
    start, end, label = _parse_range(range, date_from, date_to)

    # Build WHERE filters
    filters = ["ts >= :start", "ts < :end"]
    params: Dict[str, Any] = {"start": start, "end": end}
    if model:
        filters.append("model = :model")
        params["model"] = model
    if plan:
        filters.append("plan = :plan")
        params["plan"] = plan
    where_clause = " AND ".join(filters)

    # Group expression
    if group_by == "day":
        group_expr = "date_trunc('day', ts)"
        order_expr = "group_key"
    elif group_by == "plan":
        group_expr = "plan"
        order_expr = "group_key"
    else:
        group_expr = "model"
        order_expr = "group_key"

    sql = text(f"""
        WITH base AS (
          SELECT
            {group_expr} AS group_key,
            input_tokens,
            output_tokens,
            total_cost,
            latency_ms,
            (error_kind IS NOT NULL OR response_code >= 400) AS is_error
          FROM chat_event
          WHERE {where_clause}
        ),
        agg AS (
          SELECT
            group_key,
            COUNT(*)::bigint                                AS messages,
            COALESCE(SUM(input_tokens), 0)                  AS input_tokens,
            COALESCE(SUM(output_tokens), 0)                 AS output_tokens,
            COALESCE(SUM(total_cost), 0)::numeric(12,6)     AS total_cost,
            PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY latency_ms) AS latency_p50_ms,
            PERCENTILE_DISC(0.9) WITHIN GROUP (ORDER BY latency_ms) AS latency_p90_ms,
            (COUNT(*) FILTER (WHERE is_error))::float / GREATEST(COUNT(*), 1) AS error_rate
          FROM base
          GROUP BY group_key
        )
        SELECT * FROM agg
        ORDER BY {order_expr} ASC
    """)

    rows = _all(db, sql, params)

    def _coerce_row(r) -> Dict[str, Any]:
        m = dict(r._mapping)
        g = m["group_key"]
        if isinstance(g, datetime):
            m["group_key"] = g.date().isoformat()
        return m

    data: List[Dict[str, Any]] = [_coerce_row(r) for r in rows]

    return {
        "range": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "group_by": group_by,
        "rows": data,
    }
