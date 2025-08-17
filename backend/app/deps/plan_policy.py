from datetime import date
from sqlmodel import Session, select
from app.models import User, DailyUsage
from app.config import settings

PLAN_FREE = "free"
PLAN_MINI = "mini"    # a.k.a. Mini+
PLAN_PRO  = "pro"

def plan_limits_for(tier: str) -> int:
    if tier == PLAN_FREE: return settings.FREE_DAILY_CHATS
    if tier == PLAN_MINI: return settings.MINI_DAILY_CHATS
    if tier == PLAN_PRO:  return settings.PRO_DAILY_CHATS
    return 0  # default deny if unknown

def model_for(tier: str) -> str:
    if tier == PLAN_FREE: return settings.MODEL_FREE
    if tier == PLAN_MINI: return settings.MODEL_MINI
    if tier == PLAN_PRO:  return settings.MODEL_PRO
    return settings.MODEL_FREE

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

def check_and_increment_chat_quota(db: Session, user: User) -> tuple[bool, int, int]:
    """Returns (allowed, used, limit). Increments counter only if allowed."""
    limit = plan_limits_for(user.tier)
    if limit == -1:  # unlimited
        return True, 0, -1
    usage = get_or_create_usage(db, user.id, date.today())
    if usage.chats_count >= limit:
        return False, usage.chats_count, limit
    usage.chats_count += 1
    db.add(usage)
    db.commit()
    return True, usage.chats_count, limit

def is_session_scoped(tier: str) -> bool:
    """Free & Mini+ are session-only; Pro is global."""
    return tier in {PLAN_FREE, PLAN_MINI}
