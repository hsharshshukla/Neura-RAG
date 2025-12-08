# backend/app/analytics/logger.py
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Iterable, Optional
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

# Canonical table definition (must match DB)
from app.analytics.schema import chat_event_table

# ---------- logging ----------
log = logging.getLogger(__name__)
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[analytics] %(levelname)s: %(message)s"))
    log.addHandler(h)
log.setLevel(logging.INFO)

# Allowed/known columns (anything else will be dropped)
ALLOWED_KEYS = {c.name for c in chat_event_table.columns}

# Env flags
ANALYTICS_DISABLED = os.getenv("ANALYTICS_DISABLED", "false").strip().lower() == "true"
ANALYTICS_STRICT = os.getenv("ANALYTICS_STRICT", "false").strip().lower() == "true"
APP_ENV = os.getenv("APP_ENV", "dev").strip().lower()

# Safety caps
MAX_FEEDBACK_LEN = int(os.getenv("ANALYTICS_MAX_FEEDBACK_LEN", "4000"))  # avoid giant payloads


# -----------------------------
# Helpers
# -----------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _tz_aware(dt: Any) -> datetime:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return _now_utc()

def _as_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        s = str(v)
        return s if s else None
    except Exception:
        return None

def _to_uuid(v: Any) -> Optional[UUID]:
    if v in (None, "", 0):
        return None
    if isinstance(v, UUID):
        return v
    try:
        return UUID(str(v))
    except Exception:
        return None

def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default

def _as_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "t", "yes", "y"}
    try:
        return bool(v)
    except Exception:
        return default

def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default

def _as_array_text(v: Any) -> Optional[list[str]]:
    if v is None:
        return None
    if isinstance(v, (list, tuple, set)):
        arr = [str(x) for x in v if x is not None]
        return arr if arr else None
    s = str(v)
    return [s] if s else None

def _clean_costs(data: Dict[str, Any]) -> None:
    # in/out cost optional; total_cost should be present for dashboards
    in_c = _as_float(data.get("in_cost", 0.0), 0.0)
    out_c = _as_float(data.get("out_cost", 0.0), 0.0)
    data["in_cost"] = in_c
    data["out_cost"] = out_c
    if data.get("total_cost") is None:
        data["total_cost"] = float(in_c) + float(out_c)

def _clamp_thumb(v: Any) -> int:
    """
    Normalize thumb to -1, 0, or +1.
    Accepts bools, strings ('up'/'down'), or ints.
    """
    if v is None:
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"up", "1", "true", "y", "yes"}:
            return 1
        if s in {"down", "-1", "no"}:
            return -1
        return 0
    try:
        i = int(v)
        if i > 0:
            return 1
        if i < 0:
            return -1
        return 0
    except Exception:
        return 0

def _clamp_csat(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        i = int(v)
        if i < 1: i = 1
        if i > 5: i = 5
        return i
    except Exception:
        return None

def _debug_preview(d: Mapping[str, Any]) -> str:
    keys = sorted(k for k in d.keys() if k in ALLOWED_KEYS)
    show = []
    for k in keys[:14]:
        val = d.get(k)
        show.append(f"{k}={repr(val)[:60]}")
    return ", ".join(show) + (" ..." if len(keys) > 14 else "")


# -----------------------------
# Public API
# -----------------------------
def sanitize_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Drop unknown keys and apply safe defaults for required fields.
    Coerce types to match DB schema (notably user_id -> TEXT, chat_session_id -> UUID).
    """
    # Keep only known columns
    src = dict(payload)
    cleaned: Dict[str, Any] = {k: v for k, v in src.items() if k in ALLOWED_KEYS}

    # Required identifiers / timestamps
    ev = cleaned.get("event_id")
    cleaned["event_id"] = ev if isinstance(ev, UUID) else (_to_uuid(ev) or uuid.uuid4())
    cleaned["ts"] = _tz_aware(cleaned.get("ts"))

    # Request/session identity
    cleaned["request_id"] = _as_text(cleaned.get("request_id"))
    cleaned["user_id"] = _as_text(cleaned.get("user_id"))  # TEXT column post-migration
    cleaned["plan"] = _as_text(cleaned.get("plan"))
    cleaned["model"] = _as_text(cleaned.get("model"))
    if "chat_session_id" in ALLOWED_KEYS:
        cleaned["chat_session_id"] = _to_uuid(cleaned.get("chat_session_id"))

    # Numeric/boolean defaults
    cleaned["input_tokens"] = _as_int(cleaned.get("input_tokens"), 0)
    cleaned["output_tokens"] = _as_int(cleaned.get("output_tokens"), 0)
    cleaned["latency_ms"] = _as_int(cleaned.get("latency_ms"), 0)
    cleaned["retrieval_latency_ms"] = _as_int(cleaned.get("retrieval_latency_ms"), 0)
    cleaned["response_code"] = _as_int(cleaned.get("response_code"), 200)
    cleaned["retrieved"] = _as_bool(cleaned.get("retrieved"), False)
    cleaned["rag_hit"] = _as_bool(cleaned.get("rag_hit"), False)
    cleaned["refused"] = _as_bool(cleaned.get("refused"), False)

    # Feedback
    cleaned["thumb"] = _clamp_thumb(cleaned.get("thumb"))
    cleaned["csat"] = _clamp_csat(cleaned.get("csat"))
    fb = _as_text(cleaned.get("feedback_comment"))
    if fb and len(fb) > MAX_FEEDBACK_LEN:
        fb = fb[:MAX_FEEDBACK_LEN]
    cleaned["feedback_comment"] = fb

    # Arrays (TEXT[])
    if "rag_source_kinds" in ALLOWED_KEYS:
        cleaned["rag_source_kinds"] = _as_array_text(cleaned.get("rag_source_kinds"))
    if "rag_doc_ids_hash" in ALLOWED_KEYS:
        cleaned["rag_doc_ids_hash"] = _as_array_text(cleaned.get("rag_doc_ids_hash"))

    # Monetary fields
    _clean_costs(cleaned)

    return cleaned


def heartbeat(db: Session) -> bool:
    """Quick connectivity check to chat_event table."""
    try:
        db.execute(chat_event_table.select().limit(1))
        return True
    except SQLAlchemyError as e:
        log.error("chat_event heartbeat failed: %s", e)
        return False


def log_chat_event(db: Session, payload: Mapping[str, Any]) -> bool:
    """
    Insert a row into chat_event using a SQLAlchemy/SQLModel Session.
    - Unknown keys are ignored.
    - Types are normalized (user_id -> TEXT, chat_session_id -> UUID, arrays -> TEXT[], etc.)
    - Does NOT commit: call db.commit() at the end of your request lifecycle.
    - Respects env:
        ANALYTICS_DISABLED=true  -> skip logging (returns False)
        ANALYTICS_STRICT=true    -> re-raise on error
    Returns True on successful insert, False otherwise.
    """
    if ANALYTICS_DISABLED:
        if APP_ENV in {"dev", "qa"}:
            log.info("analytics disabled by env; skipping insert")
        return False

    data = sanitize_payload(payload)

    try:
        res = db.execute(chat_event_table.insert().values(**data))
        # rowcount may be -1 depending on driver; treat non-exception as success.
        rc = getattr(res, "rowcount", None)
        if APP_ENV in {"dev", "qa"}:
            log.info("chat_event wrote (rowcount=%s): %s", rc, _debug_preview(data))
        return True
    except SQLAlchemyError as e:
        # Never crash unless strict mode is enabled
        log.error("chat_event insert failed: %s | data=%s", e, _debug_preview(data))
        if ANALYTICS_STRICT:
            raise
        return False


def log_assistant_turn(
    db: Session,
    *,
    user_id: str | int | UUID,
    model: str,
    plan: Optional[str] = None,
    chat_session_id: Optional[str | UUID] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_cost: Optional[float] = None,
    in_cost: Optional[float] = None,
    out_cost: Optional[float] = None,
    latency_ms: Optional[int] = None,
    response_code: int = 200,
    retrieved: Optional[bool] = None,
    rag_hit: Optional[bool] = None,
    thumb: Optional[int | str | bool] = None,
    csat: Optional[int] = None,
    feedback_comment: Optional[str] = None,
    request_id: Optional[str] = None,
    rag_source_kinds: Optional[Iterable[str]] = None,
    rag_doc_ids_hash: Optional[Iterable[str]] = None,
) -> bool:
    """
    Convenience wrapper for common assistant message logging.
    """
    payload: Dict[str, Any] = {
        "event_id": uuid.uuid4(),
        "ts": _now_utc(),
        "request_id": request_id,
        "user_id": user_id,
        "plan": plan,
        "chat_session_id": chat_session_id,
        "model": model,
        "input_tokens": input_tokens or 0,
        "output_tokens": output_tokens or 0,
        "total_cost": total_cost,
        "in_cost": in_cost,
        "out_cost": out_cost,
        "latency_ms": latency_ms or 0,
        "response_code": response_code,
        "retrieved": retrieved,
        "rag_hit": rag_hit,
        "thumb": thumb,
        "csat": csat,
        "feedback_comment": feedback_comment,
        "rag_source_kinds": list(rag_source_kinds) if rag_source_kinds is not None else None,
        "rag_doc_ids_hash": list(rag_doc_ids_hash) if rag_doc_ids_hash is not None else None,
    }
    return log_chat_event(db, payload)


__all__ = ["log_chat_event", "log_assistant_turn", "sanitize_payload", "heartbeat"]
