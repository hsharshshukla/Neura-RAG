# app/deps/plan_policy.py
from app.config.plan_policy import (
    PLAN_FREE, PLAN_MINI, PLAN_PRO,
    plan_limit, plan_model, is_session_scoped,
    get_or_create_usage, check_and_increment_chat_quota,
    monthly_token_limit_for, monthly_tokens_used, monthly_usage_percent,
)

# Backward compat
def plan_limits_for(tier: str) -> int:
    return plan_limit(tier)

def model_for(tier: str) -> str:
    return plan_model(tier)
