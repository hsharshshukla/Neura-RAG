# app/routes/admin_insights.py
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

router = APIRouter(prefix="/api/v1/admin/analytics/insights", tags=["admin-analytics"])


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
    if r == "24h":
        return now - timedelta(hours=24), now, "24h"
    if r == "7d":
        return now - timedelta(days=7), now, "7d"
    if r == "30d":
        return now - timedelta(days=30), now, "30d"
    if r == "90d":
        return now - timedelta(days=90), now, "90d"
    return now - timedelta(days=7), now, "7d"


def _ensure_admin(user_email: str, db: Session) -> User:
    if require_admin:
        return require_admin(user_email=user_email, db=db)  # type: ignore
    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user or getattr(user, "role", "user") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _all(db: Session, stmt, params: Dict[str, Any]) -> List[Any]:
    """Bind params on the statement and return .all()."""
    return db.exec(stmt.bindparams(**params)).all() or []


def _first(db: Session, stmt, params: Dict[str, Any]):
    """Bind params on the statement and return .first()."""
    return db.exec(stmt.bindparams(**params)).first()


# ------------------ RAG insights ------------------

@router.get("/rag")
def rag_insights(
    range: Optional[str] = Query(default="7d"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    plan: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Returns:
      - top_docs: list of {doc_hash, retrieved, hits, hit_rate} sorted by hits desc
      - zero_hit_docs: docs retrieved but never hit
      - source_mix: counts by rag_source_kinds (flattened)
    Notes:
      - We use hashed doc IDs from chat_event.rag_doc_ids_hash for privacy.
      - 'hit' means rag_hit=true when retrieved=true.
    """
    _ensure_admin(user_email, db)
    start, end, label = _parse_range(range, date_from, date_to)

    filters = ["ts >= :start", "ts < :end", "retrieved = true"]
    params: Dict[str, Any] = {"start": start, "end": end}
    if plan:
        filters.append("plan = :plan")
        params["plan"] = plan
    if model:
        filters.append("model = :model")
        params["model"] = model
    where_clause = " AND ".join(filters)

    # 1) Explode doc hashes and aggregate hits/retrieved
    sql_top = text(f"""
        WITH exploded AS (
          SELECT
            unnest(rag_doc_ids_hash) AS doc_hash,
            rag_hit
          FROM chat_event
          WHERE {where_clause}
            AND rag_doc_ids_hash IS NOT NULL
        )
        SELECT
          doc_hash,
          COUNT(*)                           AS retrieved,
          COUNT(*) FILTER (WHERE rag_hit)    AS hits,
          CASE WHEN COUNT(*) > 0
               THEN (COUNT(*) FILTER (WHERE rag_hit))::float / COUNT(*)
               ELSE 0
          END AS hit_rate
        FROM exploded
        GROUP BY doc_hash
        ORDER BY hits DESC
        LIMIT :limit
    """)
    params_top = {**params, "limit": limit}
    top_docs = [dict(r._mapping) for r in _all(db, sql_top, params_top)]

    # 2) Zero-hit docs: retrieved but never hit
    sql_zero = text(f"""
        WITH exploded AS (
          SELECT
            unnest(rag_doc_ids_hash) AS doc_hash,
            rag_hit
          FROM chat_event
          WHERE {where_clause}
            AND rag_doc_ids_hash IS NOT NULL
        ),
        agg AS (
          SELECT
            doc_hash,
            COUNT(*) AS retrieved,
            COUNT(*) FILTER (WHERE rag_hit) AS hits
          FROM exploded
          GROUP BY doc_hash
        )
        SELECT doc_hash, retrieved
        FROM agg
        WHERE hits = 0
        ORDER BY retrieved DESC
        LIMIT :limit
    """)
    zero_hit_docs = [dict(r._mapping) for r in _all(db, sql_zero, params_top)]

    # 3) Source mix: flatten array<string> rag_source_kinds and count
    sql_sources = text(f"""
        WITH exploded AS (
          SELECT unnest(rag_source_kinds) AS kind
          FROM chat_event
          WHERE {where_clause}
            AND rag_source_kinds IS NOT NULL
        )
        SELECT kind, COUNT(*) AS cnt
        FROM exploded
        GROUP BY kind
        ORDER BY cnt DESC
    """)
    source_mix = [dict(r._mapping) for r in _all(db, sql_sources, params)]

    return {
        "range": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "filters": {"plan": plan, "model": model},
        "top_docs": top_docs,
        "zero_hit_docs": zero_hit_docs,
        "source_mix": source_mix,
    }


# ------------------ Quality insights ------------------

@router.get("/quality")
def quality_insights(
    range: Optional[str] = Query(default="7d"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    plan: Optional[str] = Query(default=None),
    model: Optional[str] = Query(default=None),
    limit_feedback: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Returns:
      - thumbs_up_rate, csat_avg
      - recent_feedback: last N events with non-empty feedback_comment
    """
    _ensure_admin(user_email, db)
    start, end, label = _parse_range(range, date_from, date_to)

    filters = ["ts >= :start", "ts < :end"]
    params: Dict[str, Any] = {"start": start, "end": end}
    if plan:
        filters.append("plan = :plan")
        params["plan"] = plan
    if model:
        filters.append("model = :model")
        params["model"] = model
    where_clause = " AND ".join(filters)

    sql_quality = text(f"""
        WITH base AS (
          SELECT
            NULLIF(thumb, 0) AS thumb_nonzero,
            csat
          FROM chat_event
          WHERE {where_clause}
        )
        SELECT
          CASE WHEN COUNT(*) FILTER (WHERE thumb_nonzero IS NOT NULL) > 0
               THEN (COUNT(*) FILTER (WHERE thumb_nonzero = 1))::float
                    / GREATEST(COUNT(*) FILTER (WHERE thumb_nonzero IS NOT NULL), 1)
               ELSE NULL
          END AS thumbs_up_rate,
          AVG(csat)::numeric(5,2) AS csat_avg
        FROM base
    """)
    row = _first(db, sql_quality, params)
    aggregates = dict(row._mapping) if row else {"thumbs_up_rate": None, "csat_avg": None}

    sql_feedback = text(f"""
        SELECT
          event_id::text AS event_id,
          ts,
          model,
          plan,
          chat_session_id::text AS chat_session_id,
          message_index,
          csat,
          thumb,
          feedback_comment
        FROM chat_event
        WHERE {where_clause}
          AND feedback_comment IS NOT NULL
          AND length(trim(feedback_comment)) > 0
        ORDER BY ts DESC
        LIMIT :limit_feedback
    """)
    params_fb = {**params, "limit_feedback": limit_feedback}
    fb_rows = _all(db, sql_feedback, params_fb)
    recent_feedback = [dict(r._mapping) for r in fb_rows]

    return {
        "range": label,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "filters": {"plan": plan, "model": model},
        **aggregates,
        "recent_feedback": recent_feedback,
    }
