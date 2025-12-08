# app/config/plan_policy.py
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

__all__ = [
    "PLAN_BASE", "PLAN_PRO", "PLAN_FREE", "PLAN_MINI",
    "plan_for",
    "plan_limit",
    "plan_model",
    "is_session_scoped",
    "monthly_token_limit_for",
    "summarize_only",
    "is_pro_active",
    "plan_features",
]

# ---------------- Plans & constants ----------------

# Canonical tier names (env-overridable if you ever need to)
PLAN_BASE = os.getenv("PLAN_BASE_NAME", "base")
PLAN_PRO  = os.getenv("PLAN_PRO_NAME",  "pro")

# Back-compat aliases for older code
PLAN_FREE = PLAN_BASE
PLAN_MINI = PLAN_BASE

# Default model names (overridable via env)
DEFAULT_MODEL_BASE = os.getenv("OPENAI_MODEL_BASE", "gpt-4o-mini")
DEFAULT_MODEL_PRO  = os.getenv("OPENAI_MODEL_PRO",  os.getenv("OPENAI_MODEL", "gpt-5"))

# Safety: if any import looks for one of the constants but the module
# file is stale/partially written, this ensures graceful fallback.
def __getattr__(name: str):
    if name == "PLAN_BASE": return PLAN_BASE
    if name == "PLAN_PRO":  return PLAN_PRO
    if name == "PLAN_FREE": return PLAN_FREE
    if name == "PLAN_MINI": return PLAN_MINI
    raise AttributeError(name)

# ---------------- Env helpers ----------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _to_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}

def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    try:
        return int(v) if v is not None else default
    except Exception:
        return default

# ---------------- Normalizers (guard against bad envs) ----------------

def _norm_daily_limit(plan: str, val: int) -> int:
    """
    Normalize misconfigured env limits.
    - PRO: <=0 should mean unlimited (-1)
    - BASE: <=0 should fall back to sane default (50)
    """
    plan = (plan or "").lower()
    if plan == PLAN_PRO:
        return -1 if val <= 0 else val
    # For base, do not allow "0/day" hard-blocks from bad envs
    if val <= 0:
        return 50
    return val

# ---------------- User → plan resolution ----------------

@dataclass(frozen=True)
class _PlanInfo:
    name: str  # "base" | "pro"

def plan_for(user: Any) -> _PlanInfo:
    """
    Resolve a user's current plan in a tolerant way.
    Accepts user.tier or user.plan; maps legacy 'free'/'mini' -> 'base'.
    """
    raw = getattr(user, "tier", None) or getattr(user, "plan", None) or PLAN_BASE
    name = str(raw).strip().lower()
    if name in {"free", "mini"}:
        name = PLAN_BASE
    if name not in {PLAN_BASE, PLAN_PRO}:
        name = PLAN_BASE
    return _PlanInfo(name=name)

# ---------------- Feature policy switches ----------------

def plan_limit(user_or_tier: Any) -> int:
    """
    Daily chat hard limit:
      - BASE: default 50/day (override PLAN_BASE_DAILY_LIMIT)
      - PRO : default unlimited (-1, override PLAN_PRO_DAILY_LIMIT)
    """
    if isinstance(user_or_tier, str):
        p = user_or_tier.strip().lower()
        if p in {"free", "mini"}:
            p = PLAN_BASE
    else:
        p = plan_for(user_or_tier).name

    if p == PLAN_PRO:
        raw = _int_env("PLAN_PRO_DAILY_LIMIT", -1)
        return _norm_daily_limit(PLAN_PRO, raw)

    raw = _int_env("PLAN_BASE_DAILY_LIMIT", 50)
    return _norm_daily_limit(PLAN_BASE, raw)

def plan_model(user_or_tier: Any) -> str:
    """Default completion model by plan (override with env)."""
    if isinstance(user_or_tier, str):
        p = user_or_tier.strip().lower()
        if p in {"free", "mini"}:
            p = PLAN_BASE
    else:
        p = plan_for(user_or_tier).name
    return DEFAULT_MODEL_PRO if p == PLAN_PRO else DEFAULT_MODEL_BASE

def is_session_scoped(user_or_tier: Any) -> bool:
    """
    Retrieval scope:
      - BASE: session-only (True)
      - PRO : global (False)
    Override:
      - PLAN_BASE_SESSION_SCOPED (default True)
      - PLAN_PRO_SESSION_SCOPED  (default False)
    """
    if isinstance(user_or_tier, str):
        p = user_or_tier.strip().lower()
        if p in {"free", "mini"}:
            p = PLAN_BASE
    else:
        p = plan_for(user_or_tier).name

    if p == PLAN_PRO:
        return _bool_env("PLAN_PRO_SESSION_SCOPED", False)
    return _bool_env("PLAN_BASE_SESSION_SCOPED", True)

def monthly_token_limit_for(user_or_tier: Any) -> int:
    """
    Hard cap on tokens/month (caller enforces if desired).
      - BASE: default 1_000_000
      - PRO : default 50_000_000
    Override PLAN_BASE_MONTHLY_TOKENS / PLAN_PRO_MONTHLY_TOKENS.
    """
    if isinstance(user_or_tier, str):
        p = user_or_tier.strip().lower()
        if p in {"free", "mini"}:
            p = PLAN_BASE
    else:
        p = plan_for(user_or_tier).name

    if p == PLAN_PRO:
        return _int_env("PLAN_PRO_MONTHLY_TOKENS", 50_000_000)
    return _int_env("PLAN_BASE_MONTHLY_TOKENS", 1_000_000)

def summarize_only(user_or_tier: Any) -> bool:
    """
    BASE users can only summarize retrieved content.
    PRO users get full Q&A.
    Override PLAN_BASE_SUMMARIZE_ONLY / PLAN_PRO_SUMMARIZE_ONLY.
    """
    if isinstance(user_or_tier, str):
        p = user_or_tier.strip().lower()
        if p in {"free", "mini"}:
            p = PLAN_BASE
    else:
        p = plan_for(user_or_tier).name

    if p == PLAN_PRO:
        return _bool_env("PLAN_PRO_SUMMARIZE_ONLY", False)
    return _bool_env("PLAN_BASE_SUMMARIZE_ONLY", True)

# ---------------- Status checks (billing/expiry/cancel) ----------------

def is_pro_active(user: Any) -> bool:
    """
    True if user's PRO plan is currently active.
    Uses:
      - user.tier
      - user.cancel_at_period_end: bool
      - user.next_renewal_at: datetime | None
      - user.scheduled_plan: str | None
    """
    if plan_for(user).name != PLAN_PRO:
        return False

    nxt = _to_aware(getattr(user, "next_renewal_at", None))
    cancel_at_period_end = bool(getattr(user, "cancel_at_period_end", False))
    scheduled_plan = (getattr(user, "scheduled_plan", None) or "").strip().lower()

    # Renewal in past -> inactive
    if nxt and nxt <= _now_utc():
        return False

    # Cancel at period end -> active until renewal passes
    if cancel_at_period_end:
        return True if nxt is None else (nxt > _now_utc())

    # Scheduled downgrade -> active until renewal passes
    if scheduled_plan and scheduled_plan != PLAN_PRO:
        return True if nxt is None else (nxt > _now_utc())

    # Default: PRO is active
    return True

# ---------------- Feature matrix (optional/diagnostic) ----------------

def plan_features(user: Any) -> Dict[str, Any]:
    p = plan_for(user).name
    return {
        "plan": p,
        "daily_limit": plan_limit(user),
        "monthly_token_cap": monthly_token_limit_for(user),
        "model": plan_model(user),
        "session_scoped": is_session_scoped(user),
        "summarize_only": summarize_only(user),
        "pro_active": is_pro_active(user),
    }
