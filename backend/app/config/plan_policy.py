# app/config/plan_policy.py
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Tuple, Optional

from sqlmodel import Session, select, func

from app.models import User, DailyUsage
from app import config as settings  # your existing settings holder


# ---- Canonical tiers (two-tier world) ----
PLAN_BASE = "base"
PLAN_PRO  = "pro"
TIERS = {PLAN_BASE, PLAN_PRO}

# Legacy aliases we may still see in DB/env; normalized to BASE
LEGACY_BASE_ALIASES = {"free", "mini", ""}


# ---- Feature caps (policy-level; not SlowAPI decorator limits) ----
@dataclass(frozen=True)
class PlanCaps:
    # Feature switches
    allow_cross_chat_search: bool
    allow_global_corpus: bool
    allow_model_only_fallback: bool  # gated by env & user toggle in Pro
    # Policy RPM/RPH (separate from endpoint decorators)
    rpm_limit: int
    rph_limit: int
    # Monthly token caps (0 → treat as unlimited)
    monthly_token_limit: int


def _get_int_from_settings(first_choice: str, *fallbacks: str, default: int = 0) -> int:
    for name in (first_choice, *fallbacks):
        if not name:
            continue
        if hasattr(settings, name):
            try:
                v = int(getattr(settings, name))
                return v
            except Exception:
                pass
    # final env fallback
    try:
        v = int(os.getenv(first_choice, ""))
        return v
    except Exception:
        return default


def _get_str_from_settings(*names: str, default: str = "") -> str:
    for name in names:
        if not name:
            continue
        if hasattr(settings, name):
            v = getattr(settings, name)
            if isinstance(v, str) and v.strip():
                return v.strip()
    # env fallback
    for name in names:
        v = os.getenv(name, "")
        if v.strip():
            return v.strip()
    return default


def caps_for(tier: str) -> PlanCaps:
    t = (tier or PLAN_BASE).strip().lower()
    if t in LEGACY_BASE_ALIASES:
        t = PLAN_BASE

    if t == PLAN_PRO:
        return PlanCaps(
            allow_cross_chat_search=True,
            allow_global_corpus=True,
            allow_model_only_fallback=(os.getenv("PRO_ALLOW_MODEL_ONLY", "false").lower() in ("1", "true", "yes")),
            rpm_limit=_get_int_from_settings("PRO_RPM_LIMIT", default=10),
            rph_limit=_get_int_from_settings("PRO_RPH_LIMIT", default=240),
            monthly_token_limit=_get_int_from_settings("PLAN_PRO_MONTHLY_TOKEN_LIMIT", default=0),
        )

    # Base
    return PlanCaps(
        allow_cross_chat_search=False,
        allow_global_corpus=False,
        allow_model_only_fallback=False,
        rpm_limit=_get_int_from_settings("BASE_RPM_LIMIT", "FREE_RPM_LIMIT", default=5),
        rph_limit=_get_int_from_settings("BASE_RPH_LIMIT", "FREE_RPH_LIMIT", default=120),
        monthly_token_limit=_get_int_from_settings(
            "PLAN_BASE_MONTHLY_TOKEN_LIMIT", "PLAN_FREE_MONTHLY_TOKEN_LIMIT", default=0
        ),
    )


# ---- Daily chat limits (-1 = unlimited) ----
def plan_limit(tier: str) -> int:
    """
    Daily chat count for the tier. -1 means unlimited.
    Falls back to legacy FREE/MINI envs if BASE/PRO not present.
    """
    t = (tier or PLAN_BASE).strip().lower()
    if t in LEGACY_BASE_ALIASES:
        t = PLAN_BASE

    if t == PLAN_PRO:
        return _get_int_from_settings("PRO_DAILY_CHATS", default=-1)

    # Base
    return _get_int_from_settings("BASE_DAILY_CHATS", "FREE_DAILY_CHATS", default=25)


# ---- Model per tier (with robust fallbacks) ----
def plan_model(tier: str) -> str:
    """
    Primary generation model per tier.
    - Pro: OPENAI_MODEL_PRO or MODEL_PRO
    - Base: OPENAI_MODEL_BASE or MODEL_BASE, falling back to MODEL_FREE
    """
    t = (tier or PLAN_BASE).strip().lower()
    if t in LEGACY_BASE_ALIASES:
        t = PLAN_BASE

    if t == PLAN_PRO:
        return _get_str_from_settings("OPENAI_MODEL_PRO", "MODEL_PRO", default="gpt-5")

    # Base
    return _get_str_from_settings("OPENAI_MODEL_BASE", "MODEL_BASE", "MODEL_FREE", default="gpt-4.1-mini")


# ---- Search scope policy ----
def is_session_scoped(tier: str) -> bool:
    """
    Base: session-only retrieval
    Pro : user-wide (and later org/public) retrieval
    """
    t = (tier or PLAN_BASE).strip().lower()
    if t in LEGACY_BASE_ALIASES:
        t = PLAN_BASE
    return t == PLAN_BASE


# ---- Monthly token caps helpers ----
def monthly_token_limit_for(tier: str) -> int:
    t = (tier or PLAN_BASE).strip().lower()
    if t in LEGACY_BASE_ALIASES:
        t = PLAN_BASE
    if t == PLAN_PRO:
        return _get_int_from_settings("PLAN_PRO_MONTHLY_TOKEN_LIMIT", default=0)
    return _get_int_from_settings("PLAN_BASE_MONTHLY_TOKEN_LIMIT", "PLAN_FREE_MONTHLY_TOKEN_LIMIT", default=0)


def _month_bounds(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    now = now or datetime.utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month < 12:
        end = start.replace(month=start.month + 1, day=1)
    else:
        end = start.replace(year=start.year + 1, month=1, day=1)
    return start, end


def monthly_tokens_used(db: Session, user_id: int, now: Optional[datetime] = None) -> int:
    """
    Sums total_tokens from LLMUsageEvent for the current month.
    """
    from app.models_billing_analytics import LLMUsageEvent  # lazy import

    start, end = _month_bounds(now)
    q = select(func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0)).where(
        LLMUsageEvent.user_id == user_id,
        LLMUsageEvent.created_at >= start,
        LLMUsageEvent.created_at < end,
    )
    return int(db.exec(q).one())


def monthly_usage_percent(db: Session, user: User, now: Optional[datetime] = None) -> float:
    cap = monthly_token_limit_for(user.tier)
    if cap <= 0:
        return 0.0
    used = monthly_tokens_used(db, user.id, now)
    return min(100.0, (used / cap) * 100.0)


# ---- Daily usage counter (unchanged behavior) ----
def get_or_create_usage(db: Session, user_id: int, d: date) -> DailyUsage:
    usage = db.exec(
        select(DailyUsage).where(DailyUsage.user_id == user_id, DailyUsage.day == d)
    ).first()
    if not usage:
        usage = DailyUsage(user_id=user_id, day=d, chats_count=0)
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage


def check_and_increment_chat_quota(db: Session, user: User) -> Tuple[bool, int, int]:
    """
    Returns (allowed, used, limit). Increments counter only if allowed.
    """
    limit = plan_limit(user.tier)
    if limit == -1:  # unlimited
        return True, 0, -1
    usage = get_or_create_usage(db, user.id, date.today())
    if usage.chats_count >= limit:
        return False, usage.chats_count, limit
    usage.chats_count += 1
    db.add(usage)
    db.commit()
    return True, usage.chats_count, limit


# ---- Convenience used by routes (removes ad-hoc fallbacks there) ----
class _PlanInfo:
    def __init__(self, name: str): self.name = name

def _normalize_tier(raw: str | None) -> str:
    t = (raw or PLAN_BASE).strip().lower()
    if t in LEGACY_BASE_ALIASES:
        return PLAN_BASE
    return t if t in TIERS else PLAN_BASE

def plan_for(user: User) -> _PlanInfo:
    """
    Returns the user's declared plan label, normalized to {base|pro}.
    """
    return _PlanInfo(_normalize_tier(getattr(user, "tier", None)))


def is_pro_active(user: User) -> bool:
    """
    True if the user is effectively on Pro:
      - explicit tier == 'pro', OR
      - paid flag set, OR
      - active trial started and not cancelled.
    """
    t = _normalize_tier(getattr(user, "tier", None))
    if t == PLAN_PRO:
        return True
    try:
        if bool(getattr(user, "is_pro_paid_active", False)):
            return True
    except Exception:
        pass
    try:
        started = getattr(user, "pro_trial_started_at", None)
        cancelled = bool(getattr(user, "pro_trial_cancelled", False))
        if started and not cancelled:
            return True
    except Exception:
        pass
    return False


# ---- Backward-compat names for any older imports ----
def plan_limits_for(tier: str) -> int:
    return plan_limit(tier)

def model_for(tier: str) -> str:
    return plan_model(tier)
