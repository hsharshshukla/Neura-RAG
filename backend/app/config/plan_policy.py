# app/config/plan_policy.py
from __future__ import annotations

from datetime import date, datetime
from typing import Tuple, Optional

from sqlmodel import Session, select, func

from app.models import User, DailyUsage
# app/config/plan_policy.py
from app import config as settings

# from app.config.settings import settings  # ensure your Settings instance is here


# ---- Tiers ----
PLAN_FREE = "free"
PLAN_MINI = "mini"    # Mini+
PLAN_PRO  = "pro"
TIERS = {PLAN_FREE, PLAN_MINI, PLAN_PRO}


# ---- Daily chat limits (-1 = unlimited) ----
def plan_limit(tier: str) -> int:
    if tier == PLAN_FREE: return settings.FREE_DAILY_CHATS
    if tier == PLAN_MINI: return settings.MINI_DAILY_CHATS
    if tier == PLAN_PRO:  return settings.PRO_DAILY_CHATS
    return 0  # default deny


# ---- Model per tier ----
def plan_model(tier: str) -> str:
    if tier == PLAN_FREE: return settings.MODEL_FREE
    if tier == PLAN_MINI: return settings.MODEL_MINI
    if tier == PLAN_PRO:  return settings.MODEL_PRO
    return settings.MODEL_FREE


# ---- Search scope ----
def is_session_scoped(tier: str) -> bool:
    """Free & Mini+ are session-only; Pro is global."""
    return tier in {PLAN_FREE, PLAN_MINI}


# ---- Daily usage counter (your original behavior) ----
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


# ---- Monthly token caps (set via .env) ----
def monthly_token_limit_for(tier: str) -> int:
    if tier == PLAN_FREE: return settings.PLAN_FREE_MONTHLY_TOKEN_LIMIT
    if tier == PLAN_MINI: return settings.PLAN_MINI_MONTHLY_TOKEN_LIMIT
    if tier == PLAN_PRO:  return settings.PLAN_PRO_MONTHLY_TOKEN_LIMIT
    return 0


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
    # Lazy import to avoid circular import at module import time
    from app.models_billing_analytics import LLMUsageEvent

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


# ---- Backward-compat names (if any old code expects these) ----
# (Your old module exported plan_limits_for / model_for.)
def plan_limits_for(tier: str) -> int:
    return plan_limit(tier)

def model_for(tier: str) -> str:
    return plan_model(tier)
