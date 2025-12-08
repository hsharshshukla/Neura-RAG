# app/routes/admin_refresh.py
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlmodel import Session, select

from app.db import get_session
from app.models import User
from app.deps.auth import get_current_user
from app.analytics.logger import log_chat_event  # used by /_test_event

try:
    from app.deps.admin_dependency import require_admin  # type: ignore
except Exception:
    require_admin = None

router = APIRouter(prefix="/api/v1/admin/analytics", tags=["admin-analytics"])


# ---------- helpers ------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_admin(user_email: str, db: Session) -> User:
    """
    Prefer your existing admin guard; else require role == 'admin'.
    """
    if require_admin:
        return require_admin(user_email=user_email, db=db)  # type: ignore

    user = db.exec(select(User).where(User.email == user_email)).first()
    if not user or getattr(user, "role", "user") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _function_exists(db: Session, func_name: str) -> bool:
    """
    Detect a function in the current schema.
    """
    stmt = text(
        """
        SELECT EXISTS (
          SELECT 1
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
          WHERE p.proname = :fname
            AND n.nspname = current_schema()
        ) AS ok
        """
    ).bindparams(fname=func_name)
    row = db.exec(stmt).first()
    return bool(row and list(row)[0])


def _list_matviews(db: Session, pattern: str = "chat_%") -> List[str]:
    """
    Return fully-qualified matview names in current schema matching pattern.
    """
    stmt = text(
        """
        SELECT schemaname, matviewname
        FROM pg_matviews
        WHERE schemaname = current_schema()
          AND matviewname ILIKE :pat
        ORDER BY matviewname
        """
    ).bindparams(pat=pattern)
    rows = db.exec(stmt).all() or []
    result: List[str] = []
    for r in rows:
        # r is RowMapping; access by attribute or key
        schema = getattr(r, "schemaname", None) or r._mapping["schemaname"]
        name = getattr(r, "matviewname", None) or r._mapping["matviewname"]
        result.append(f'{schema}."{name}"')
    return result


def _safe_exec(db: Session, sql: str, params: Optional[Dict[str, Any]] = None) -> None:
    """
    Execute a statement (DDL or SELECT) with optional params and COMMIT.
    Caller is responsible for catching exceptions.
    """
    stmt = text(sql)
    if params:
        stmt = stmt.bindparams(**params)
    db.exec(stmt)
    db.commit()


# ---------- refresh endpoint ---------------------------------------------------

@router.post("/refresh")
def refresh_rollups(
    days: int = Query(2, ge=1, le=90, description="Recompute daily aggregates for the last N days (UTC)"),
    refresh_sessions: bool = Query(True, description="Run session-level rollups"),
    refresh_daily: bool = Query(True, description="Run daily aggregates"),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Best-effort refresh for analytics artifacts.

    It will:
      1) Call session rollup function if present:
           - fn_update_chat_session_metrics()
           - (fallbacks tried but optional) chat_session_metrics_refresh(), chat_rollups_refresh_sessions()
      2) Call daily rollup function if present (with a window [now-days, now]):
           - fn_update_chat_agg_day(start_ts, end_ts)
           - (fallbacks tried but optional) chat_rollups_refresh_day(start_ts, end_ts), chat_daily_refresh(start_ts, end_ts)
      3) Refresh materialized views matching 'chat_%' (concurrently if possible).
      4) ANALYZE chat_event.

    Returns JSON with what ran and any warnings instead of 500s.
    """
    _ensure_admin(user_email, db)

    now = _now_utc()
    start = now - timedelta(days=days)

    results: Dict[str, Any] = {
        "window": {"start": start.isoformat(), "end": now.isoformat()},
        "called_functions": [],
        "refreshed_matviews": [],
        "analyze_chat_event": None,
        "warnings": [],
    }

    # 1) Session-level rollups
    if refresh_sessions:
        session_funcs = [
            "fn_update_chat_session_metrics",
            "chat_session_metrics_refresh",
            "chat_rollups_refresh_sessions",
        ]
        ran_session = False
        for fname in session_funcs:
            try:
                if _function_exists(db, fname):
                    _safe_exec(db, f"SELECT {fname}()")
                    results["called_functions"].append(f"{fname}()")
                    ran_session = True
                    break
            except Exception as e:
                db.rollback()
                results["warnings"].append(f"{fname}() failed: {e!r}")
        if not ran_session:
            results["warnings"].append("No session rollup function found in current schema.")

    # 2) Daily aggregates over a bounded time window
    if refresh_daily:
        daily_funcs = [
            "fn_update_chat_agg_day",
            "chat_rollups_refresh_day",
            "chat_daily_refresh",
        ]
        ran_daily = False
        for fname in daily_funcs:
            try:
                if _function_exists(db, fname):
                    _safe_exec(db, f"SELECT {fname}(:start_ts, :end_ts)", {"start_ts": start, "end_ts": now})
                    results["called_functions"].append(f"{fname}(:start_ts, :end_ts)")
                    ran_daily = True
                    break
            except Exception as e:
                db.rollback()
                results["warnings"].append(f"{fname}(start,end) failed: {e!r}")
        if not ran_daily:
            results["warnings"].append("No daily rollup function found in current schema.")

    # 3) Refresh materialized views
    try:
        matviews = _list_matviews(db, pattern="chat_%")
        for mv in matviews:
            try:
                # Prefer non-blocking; if it fails (no unique index), fallback to blocking
                _safe_exec(db, f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv}")
                results["refreshed_matviews"].append({"name": mv, "mode": "concurrently"})
            except Exception:
                db.rollback()
                try:
                    _safe_exec(db, f"REFRESH MATERIALIZED VIEW {mv}")
                    results["refreshed_matviews"].append({"name": mv, "mode": "blocking"})
                except Exception as e2:
                    db.rollback()
                    results["warnings"].append(f"refresh {mv} failed: {e2!r}")
    except Exception as e:
        db.rollback()
        results["warnings"].append(f"listing matviews failed: {e!r}")

    # 4) ANALYZE for fresh planner stats on raw events table
    try:
        _safe_exec(db, "ANALYZE chat_event")
        results["analyze_chat_event"] = "ok"
    except Exception as e:
        db.rollback()
        results["analyze_chat_event"] = f"failed: {e!r}"

    return results


# ---------- diagnostics --------------------------------------------------------

@router.get("/_whoami")
def whoami(
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Quick auth + admin check; helps ensure you're hitting the API with the right session.
    """
    try:
        user = _ensure_admin(user_email, db)
        return {"ok": True, "user": {"email": user_email, "id": getattr(user, "id", None), "role": getattr(user, "role", None)}}
    except HTTPException as e:
        return {"ok": False, "user": {"email": user_email}, "error": e.detail}


@router.get("/_diag")
def analytics_diag(
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    _ensure_admin(user_email, db)

    # Env (non-sensitive)
    env = {
        "APP_ENV": os.getenv("APP_ENV"),
        "ANALYTICS_DISABLED": os.getenv("ANALYTICS_DISABLED", "false"),
        "ANALYTICS_STRICT": os.getenv("ANALYTICS_STRICT", "false"),
    }

    # DB identity + table status
    info_stmt = text("SELECT current_database() AS db, current_schema() AS schema, now() AT TIME ZONE 'UTC' AS server_utc")
    info = dict(db.exec(info_stmt).first() or {})

    exists_stmt = text("""
        SELECT to_regclass('chat_event') IS NOT NULL AS table_exists
    """)
    table_exists = bool(list(db.exec(exists_stmt).first() or [False])[0])

    columns: List[str] = []
    if table_exists:
        cols_stmt = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'chat_event'
            ORDER BY ordinal_position
        """)
        columns = [r[0] for r in db.exec(cols_stmt).all() or []]

    counts_24h = 0
    ts_bounds: Dict[str, Optional[str]] = {"min_ts": None, "max_ts": None}
    if table_exists:
        c24 = db.exec(text("SELECT COUNT(*) FROM chat_event WHERE ts > now() - interval '24 hours'")).one()
        counts_24h = int(c24 or 0)
        mm = db.exec(text("SELECT MIN(ts) AS min_ts, MAX(ts) AS max_ts FROM chat_event")).first()
        if mm:
            ts_bounds = {"min_ts": str(mm._mapping["min_ts"]), "max_ts": str(mm._mapping["max_ts"])}

    return {
        "env": env,
        "db": info,
        "chat_event": {
            "exists": table_exists,
            "columns": columns,
            "count_24h": counts_24h,
            **ts_bounds,
        },
    }


@router.get("/_peek")
def analytics_peek(
    limit: int = Query(10, ge=1, le=200),
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    _ensure_admin(user_email, db)

    stmt = text("""
        SELECT
          event_id::text,
          ts AT TIME ZONE 'UTC' AS ts_utc,
          user_id,
          plan,
          model,
          chat_session_id::text,
          message_index,
          input_tokens,
          output_tokens,
          latency_ms,
          response_code,
          retrieved,
          rag_hit
        FROM chat_event
        ORDER BY ts DESC
        LIMIT :lim
    """).bindparams(lim=limit)
    rows = [dict(r._mapping) for r in (db.exec(stmt).all() or [])]
    return {"rows": rows, "count": len(rows)}


@router.post("/_test_event")
def analytics_test_event(
    db: Session = Depends(get_session),
    user_email: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Inserts a minimal good event via the same logger used by chat.py and commits it.
    Use this to prove end-to-end insert & commit is working against the right DB.
    """
    _ensure_admin(user_email, db)

    payload: Dict[str, Any] = {
        "event_id": uuid.uuid4(),
        "ts": datetime.now(timezone.utc),
        "request_id": str(uuid.uuid4()),
        "user_id": user_email,  # TEXT column
        "plan": "diag",
        "model": "diag/test",
        "provider": "diag",
        "chat_session_id": uuid.uuid4(),  # UUID column
        "message_index": 0,
        "input_tokens": 5,
        "output_tokens": 7,
        "latency_ms": 123,
        "response_code": 200,
        "retrieved": False,
        "rag_hit": False,
        "in_cost": 0.0,
        "out_cost": 0.0,
        "total_cost": 0.0,
        "intent": "diag",
        "topic": None,
        "pipeline_version": "v0",
    }

    # Insert with the same path chat.py uses
    log_chat_event(db, payload)
    db.commit()

    # Return quick summary after insert
    c24 = db.exec(text("SELECT COUNT(*) FROM chat_event WHERE ts > now() - interval '24 hours'")).one()
    mm = db.exec(text("SELECT MIN(ts) AS min_ts, MAX(ts) AS max_ts FROM chat_event")).first()
    return {
        "ok": True,
        "inserted_event_id": str(payload["event_id"]),
        "count_24h": int(c24 or 0),
        "min_ts": str(mm._mapping["min_ts"]) if mm else None,
        "max_ts": str(mm._mapping["max_ts"]) if mm else None,
    }
